/*
 * Notifiche temporanee in basso a destra.
 *
 * Perché il timer legge `onDismiss` da una ref: i chiamanti passano spesso una
 * funzione nuova a ogni render; con `onDismiss` tra le dipendenze dell'effetto
 * il conto alla rovescia ripartirebbe a ogni render dell'app e il toast non
 * scomparirebbe mai.
 */
import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import { cn } from './utils.js';
import { IconButton } from './IconButton.js';
import { STATUS_ICON, STATUS_TEXT, type StatusTone } from './shared.js';

export type ToastType = StatusTone;

export interface ToastMessage {
  id: string;
  type: ToastType;
  message: string;
  /** Durata in ms prima della chiusura automatica (default 4000). */
  duration?: number;
}

export interface ToastProps {
  toast: ToastMessage;
  onDismiss: (id: string) => void;
}

export function Toast({ toast, onDismiss }: ToastProps) {
  const onDismissRef = useRef(onDismiss);
  onDismissRef.current = onDismiss;

  useEffect(() => {
    const timer = setTimeout(() => onDismissRef.current(toast.id), toast.duration ?? 4000);
    return () => clearTimeout(timer);
  }, [toast.id, toast.duration]);

  const Icon = STATUS_ICON[toast.type];

  return (
    <div
      role={toast.type === 'error' ? 'alert' : 'status'}
      className="pointer-events-auto flex animate-pop-in items-start gap-2.5 rounded-lg border bg-popover py-2 pl-3 pr-2 text-sm text-popover-foreground shadow-composer"
    >
      <Icon aria-hidden className={cn('mt-0.5 size-4 shrink-0', STATUS_TEXT[toast.type])} />
      <span className="max-w-md flex-1 py-px">{toast.message}</span>
      <IconButton label="Chiudi notifica" size="xs" onClick={() => onDismiss(toast.id)}>
        <X />
      </IconButton>
    </div>
  );
}

export function ToastContainer({
  toasts,
  onDismiss,
}: {
  toasts: ToastMessage[];
  onDismiss: (id: string) => void;
}) {
  if (toasts.length === 0) return null;
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed bottom-4 right-4 z-[60] flex flex-col items-end gap-2 max-sm:inset-x-3 max-sm:bottom-[calc(4.5rem+env(safe-area-inset-bottom))] max-sm:items-stretch"
    >
      {toasts.map((toast) => (
        <Toast key={toast.id} toast={toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
}
