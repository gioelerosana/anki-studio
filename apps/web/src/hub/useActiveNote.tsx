/*
 * Nota aperta nel dettaglio, con la guardia delle modifiche non salvate: passare a un'altra
 * nota (o chiudere il pannello) con dei campi cambiati chiede prima conferma, invece di
 * buttare via in silenzio ciò che si è scritto.
 */
import { useCallback, useRef, useState, type ReactNode } from 'react';
import { ConfirmDialog } from './ConfirmDialog';

export function useActiveNote(): {
  active: number | null;
  /** Apre (o chiude, con `null`) il dettaglio; con modifiche non salvate chiede conferma. */
  select: (id: number | null) => void;
  /**
   * Come `select(null)` ma senza conferma: per quando le modifiche non servono più
   * (nota cancellata, o scelta esplicita di buttarle). Mai per «sparita dall'elenco»
   * con modifiche in corso: lì la nota resta aperta (vedi `dirty`).
   */
  reset: () => void;
  /** Da passare a `NoteInspector`. Stabile. */
  onDirtyChange: (dirty: boolean) => void;
  /** La nota aperta ha modifiche non salvate. Reattivo: chi tiene la nota aperta anche se sparisce dall'elenco lo legge da qui. */
  dirty: boolean;
  guard: ReactNode;
} {
  const [active, setActive] = useState<number | null>(null);
  const [pending, setPending] = useState<{ id: number | null } | null>(null);
  // ref per `select` (deve vedere il valore subito), state per chi deve reagire (vedi `dirty` sopra)
  const dirtyRef = useRef(false);
  const [dirty, setDirty] = useState(false);

  const onDirtyChange = useCallback((value: boolean) => {
    dirtyRef.current = value;
    setDirty(value);
  }, []);

  const select = useCallback(
    (id: number | null) => {
      if (id === active) return;
      if (dirtyRef.current) setPending({ id });
      else setActive(id);
    },
    [active],
  );

  const reset = useCallback(() => {
    dirtyRef.current = false;
    setDirty(false);
    setActive(null);
  }, []);

  const guard = (
    <ConfirmDialog
      isOpen={pending !== null}
      title="Modifiche non salvate"
      description="Nella nota aperta ci sono modifiche che non hai salvato. Se continui, vanno perse."
      confirmLabel="Scarta le modifiche"
      onClose={() => setPending(null)}
      onConfirm={() => {
        dirtyRef.current = false;
        setDirty(false);
        setActive(pending?.id ?? null);
        setPending(null);
      }}
    />
  );

  return { active, select, reset, onDirtyChange, dirty, guard };
}
