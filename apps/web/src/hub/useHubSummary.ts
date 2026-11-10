/*
 * Numero di bozze da approvare, per il badge dell'Inbox sulla schermata dei mazzi.
 *
 * Un badge è un di più: se la rotta non c'è (backend più vecchio), risponde errore o la
 * collezione è occupata da una sync, il numero sparisce in silenzio. Mai un errore a schermo.
 * Si rinfresca all'apertura, quando la finestra torna visibile o prende il focus, con un
 * intervallo minimo per non fare due richieste per lo stesso rientro (visibilitychange e
 * focus arrivano quasi insieme).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';

const MIN_INTERVAL_MS = 2000;

export function useHubSummary(): { drafts: number | null; refresh: () => void } {
  const [drafts, setDrafts] = useState<number | null>(null);
  const lastRun = useRef(0);
  const alive = useRef(true);

  const refresh = useCallback(() => {
    const now = Date.now();
    if (now - lastRun.current < MIN_INTERVAL_MS) return;
    lastRun.current = now;
    api
      .hubSummary()
      .then((s) => alive.current && setDrafts(typeof s.drafts === 'number' ? s.drafts : null))
      .catch(() => alive.current && setDrafts(null));
  }, []);

  useEffect(() => {
    alive.current = true;
    refresh();
    const onVisible = () => !document.hidden && refresh();
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', onVisible);
    return () => {
      alive.current = false;
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', onVisible);
    };
  }, [refresh]);

  return { drafts, refresh };
}
