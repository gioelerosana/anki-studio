/*
 * WebSocket del telecomando (backend/app/remote.py), con riconnessione.
 *
 * Il telefono va in standby, iOS sospende la PWA, il Wi‑Fi cambia: la connessione cade
 * spesso e in silenzio. Per questo:
 * - si riconnette da sola, con attesa crescente (0,5 s → 10 s);
 * - al ritorno in primo piano (o in rete) manda un ping: se il pong non arriva entro
 *   pochi secondi la connessione è morta anche se il browser la dice aperta, e si rifà;
 * - se l'handshake viene rifiutato chiede `/auth/me`: con la sessione scaduta il 401
 *   fa partire il login come nel resto dell'app (app/auth.tsx).
 *
 * L'accesso è il cookie di sessione, come per le altre richieste: niente token nell'URL.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import type { RemoteServerMessage } from '../api/types';

export type SocketStatus = 'connecting' | 'open';

const PONG_TIMEOUT_MS = 4000;
/** Lo stesso id di schermata si è ricollegato altrove: questa connessione non serve più. */
const CLOSE_REPLACED = 4409;

export function useRemoteSocket(
  query: string,
  onMessage: (message: RemoteServerMessage) => void,
  { onOpen, enabled = true }: { onOpen?: () => void; enabled?: boolean } = {},
) {
  const [status, setStatus] = useState<SocketStatus>('connecting');
  const wsRef = useRef<WebSocket | null>(null);
  const handlers = useRef({ onMessage, onOpen });
  handlers.current = { onMessage, onOpen };

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    let attempts = 0;
    let retryTimer: number | undefined;
    let pongTimer: number | undefined;

    const connect = () => {
      window.clearTimeout(retryTimer);
      if (disposed) return;
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const ws = new WebSocket(`${scheme}://${window.location.host}/api/remote?${query}`);
      wsRef.current = ws;
      let opened = false;
      setStatus('connecting');

      ws.onopen = () => {
        opened = true;
        attempts = 0;
        setStatus('open');
        handlers.current.onOpen?.();
      };
      ws.onmessage = (event) => {
        let message: RemoteServerMessage;
        try {
          message = JSON.parse(String(event.data)) as RemoteServerMessage;
        } catch {
          return;
        }
        if (message.type === 'pong') window.clearTimeout(pongTimer);
        else handlers.current.onMessage(message);
      };
      ws.onclose = (event) => {
        if (wsRef.current !== ws) return; // già sostituita da una connessione nuova
        wsRef.current = null;
        window.clearTimeout(pongTimer);
        if (disposed || event.code === CLOSE_REPLACED) return;
        setStatus('connecting');
        // handshake rifiutato: forse la sessione è scaduta (un 401 fa ripartire il login)
        if (!opened) api.me().catch(() => {});
        const delay = Math.min(10_000, 500 * 2 ** attempts++);
        retryTimer = window.setTimeout(connect, delay);
      };
    };

    const check = () => {
      if (document.hidden || disposed) return;
      const ws = wsRef.current;
      if (!ws || ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
        attempts = 0;
        connect();
        return;
      }
      if (ws.readyState !== WebSocket.OPEN) return;
      ws.send(JSON.stringify({ type: 'ping' }));
      window.clearTimeout(pongTimer);
      pongTimer = window.setTimeout(() => {
        // connessione "zombie" dopo lo standby: si butta e si rifà subito
        if (wsRef.current !== ws) return;
        wsRef.current = null;
        ws.close();
        attempts = 0;
        connect();
      }, PONG_TIMEOUT_MS);
    };

    connect();
    document.addEventListener('visibilitychange', check);
    window.addEventListener('online', check);
    return () => {
      disposed = true;
      window.clearTimeout(retryTimer);
      window.clearTimeout(pongTimer);
      document.removeEventListener('visibilitychange', check);
      window.removeEventListener('online', check);
      const ws = wsRef.current;
      wsRef.current = null;
      ws?.close();
    };
  }, [query, enabled]);

  /** Manda un messaggio se la connessione è aperta; false altrimenti. */
  const send = useCallback((message: unknown) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(message));
    return true;
  }, []);

  return { status, send };
}
