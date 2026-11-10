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
  /** Come `select` ma senza conferma: la nota non esiste più. */
  reset: () => void;
  /** Da passare a `NoteInspector`. Stabile. */
  onDirtyChange: (dirty: boolean) => void;
  guard: ReactNode;
} {
  const [active, setActive] = useState<number | null>(null);
  const [pending, setPending] = useState<{ id: number | null } | null>(null);
  const dirty = useRef(false);

  const onDirtyChange = useCallback((value: boolean) => {
    dirty.current = value;
  }, []);

  const select = useCallback(
    (id: number | null) => {
      if (id === active) return;
      if (dirty.current) setPending({ id });
      else setActive(id);
    },
    [active],
  );

  const reset = useCallback(() => {
    dirty.current = false;
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
        dirty.current = false;
        setActive(pending?.id ?? null);
        setPending(null);
      }}
    />
  );

  return { active, select, reset, onDirtyChange, guard };
}
