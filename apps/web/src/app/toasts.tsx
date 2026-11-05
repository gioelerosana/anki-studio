/*
 * Notifiche temporanee condivise da tutte le schermate.
 *
 * Perché un contesto: lo studio, l'aggiunta carte e la sync devono poter
 * segnalare un esito senza passare callback attraverso tutta la shell.
 */
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { ToastContainer, type ToastMessage } from '@anki-studio/ui-kit';

export type AddToast = (type: ToastMessage['type'], message: string) => void;

const ToastContext = createContext<AddToast>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const addToast = useCallback<AddToast>((type, message) => {
    const id = Math.random().toString(36).slice(2);
    // Un solo toast per messaggio: premere due volte «Annulla» a vuoto non deve impilarne due.
    setToasts((prev) => [...prev.filter((t) => t.message !== message), { id, type, message }]);
  }, []);
  const remove = useCallback((id: string) => setToasts((prev) => prev.filter((t) => t.id !== id)), []);
  const value = useMemo(() => addToast, [addToast]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* In alto, sotto la barra: in basso ci sono i pulsanti di risposta e il toast li coprirebbe. */}
      <ToastContainer
        toasts={toasts}
        onDismiss={remove}
        className="bottom-auto top-[calc(var(--topbar-height)+env(safe-area-inset-top)+0.5rem)] right-[max(1rem,env(safe-area-inset-right))] max-sm:bottom-auto"
      />
    </ToastContext.Provider>
  );
}

export function useToast(): AddToast {
  return useContext(ToastContext);
}
