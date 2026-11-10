/*
 * La schermata di studio come "schermo" del telecomando: pubblica il proprio stato e
 * riceve i tasti premuti sul telefono.
 *
 * Nessun abbinamento: basta avere lo studio aperto. Se le schermate aperte sono più di
 * una (computer e iPad), il telefono comanda quella che era in primo piano per ultima:
 * per questo lo stato si "rivendica" (`claim`) solo quando la pagina è visibile, e di
 * nuovo quando torna visibile o riprende il focus.
 */
import { useEffect, useRef, useState } from 'react';
import type { RemoteCommand, RemoteScreenState } from '../api/types';
import { useRemoteSocket } from './useRemoteSocket';

function newScreenId(): string {
  // randomUUID solo nei contesti sicuri: in sviluppo via IP della LAN non c'è
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join('');
}

export function useRemoteScreen(state: RemoteScreenState | null, onCommand: (command: RemoteCommand) => void) {
  const [remotes, setRemotes] = useState(0);
  const [screenId] = useState(newScreenId);
  const latest = useRef({ state, onCommand });
  latest.current = { state, onCommand };
  const lastSent = useRef('');

  const { send } = useRemoteSocket(
    `role=screen&screen_id=${screenId}`,
    (message) => {
      if (message.type === 'remotes') setRemotes(message.count);
      else if (message.type === 'command') latest.current.onCommand(message.command);
    },
    {
      // connessione nuova (anche dopo una caduta): il server non sa più niente di noi
      onOpen: () => {
        lastSent.current = '';
        publish(true);
      },
    },
  );

  function publish(force = false) {
    const current = latest.current.state;
    if (!current) return;
    const body = JSON.stringify(current);
    if (!force && body === lastSent.current) return;
    if (send({ type: 'state', state: current, claim: document.visibilityState === 'visible' })) lastSent.current = body;
  }
  const publishRef = useRef(publish);
  publishRef.current = publish;

  useEffect(() => {
    publishRef.current();
  }, [state]);

  useEffect(() => {
    const claim = () => {
      if (document.visibilityState === 'visible') publishRef.current(true);
    };
    document.addEventListener('visibilitychange', claim);
    window.addEventListener('focus', claim);
    return () => {
      document.removeEventListener('visibilitychange', claim);
      window.removeEventListener('focus', claim);
    };
  }, []);

  return { remotes };
}
