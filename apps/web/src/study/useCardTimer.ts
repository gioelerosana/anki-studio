/*
 * Tempo di risposta per `time_taken_ms`.
 *
 * Perché togliere il tempo in background: su iPad si lascia spesso l'app aperta
 * su una carta e si torna dopo ore; quel tempo non è studio. Il backend lo
 * limita comunque al massimo del preset del mazzo, come Anki desktop.
 */
import { useCallback, useEffect, useRef } from 'react';

export function useCardTimer(cardId: number | null) {
  const start = useRef(performance.now());
  const hiddenSince = useRef<number | null>(null);
  const hiddenTotal = useRef(0);

  useEffect(() => {
    start.current = performance.now();
    hiddenTotal.current = 0;
    hiddenSince.current = document.hidden ? performance.now() : null;
  }, [cardId]);

  useEffect(() => {
    const onVisibility = () => {
      if (document.hidden) hiddenSince.current = performance.now();
      else if (hiddenSince.current !== null) {
        hiddenTotal.current += performance.now() - hiddenSince.current;
        hiddenSince.current = null;
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, []);

  return useCallback(() => {
    const hidden = hiddenTotal.current + (hiddenSince.current !== null ? performance.now() - hiddenSince.current : 0);
    return Math.max(0, Math.round(performance.now() - start.current - hidden));
  }, []);
}
