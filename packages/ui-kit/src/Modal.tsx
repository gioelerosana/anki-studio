/*
 * Dialog modale opaco: niente vetro, il testo della pagina sotto non deve
 * trasparire e confondersi con il contenuto.
 *
 * Perché un portale e un focus trap minimo: il dialog vive sotto `document.body`
 * per non essere intrappolato da antenati con `transform`/`backdrop-filter`
 * (le toolbar in vetro creano un contesto di posizionamento per i `fixed`).
 * All'apertura il focus va al dialog (non al primo bottone, per non attivare per
 * sbaglio un'azione distruttiva), Tab resta dentro e alla chiusura il focus
 * torna dov'era. Esc e clic sul backdrop chiudono.
 */
import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { cn } from './utils.js';
import { IconButton } from './IconButton.js';
import { FOCUSABLE_SELECTOR } from './shared.js';

export interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  /** Classe Tailwind di larghezza massima (default `max-w-md`). Ignorata se c'è `size`. */
  maxWidth?: string;
  /** `sm` max-w-sm · `md` max-w-md · `lg` max-w-2xl; ha la precedenza su `maxWidth`. */
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

const SIZES = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-2xl',
} as const;

export function Modal({
  isOpen,
  onClose,
  title,
  description,
  children,
  footer,
  maxWidth = 'max-w-md',
  size,
  className,
}: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    if (!isOpen) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    // Rispetta un eventuale `autoFocus` di un campo interno.
    if (dialog && !dialog.contains(document.activeElement)) dialog.focus();

    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented) onCloseRef.current();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      previouslyFocused?.focus?.();
    };
  }, [isOpen]);

  if (!isOpen || typeof document === 'undefined') return null;

  const trapFocus = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Tab') return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === dialog)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex animate-fade-in items-center justify-center bg-black/32 p-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-[max(1rem,env(safe-area-inset-top))]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        onKeyDown={trapFocus}
        className={cn(
          'flex max-h-[calc(100dvh-2rem)] w-full animate-pop-in flex-col overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-dialog outline-none',
          size ? SIZES[size] : maxWidth,
          className,
        )}
      >
        <div className="flex shrink-0 items-start justify-between gap-3 px-5 pb-3 pt-5">
          <div className="min-w-0">
            <h2 id={titleId} className="text-base font-semibold">
              {title}
            </h2>
            {description ? (
              <p id={descriptionId} className="mt-1 text-sm text-muted-foreground">
                {description}
              </p>
            ) : null}
          </div>
          <IconButton
            label="Chiudi"
            size="sm"
            className="-mr-1.5 -mt-0.5"
            onClick={onClose}
          >
            <X />
          </IconButton>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-5">{children}</div>

        {footer ? (
          <div className="flex shrink-0 items-center justify-end gap-2 border-t px-5 py-3">
            {footer}
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}
