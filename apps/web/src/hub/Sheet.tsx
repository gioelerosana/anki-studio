/*
 * Foglio a tutto schermo per il dettaglio di una nota quando la finestra è stretta
 * (iPad in verticale, telefono). Da `lg` il dettaglio sta in una colonna accanto all'elenco.
 *
 * Non usa `Modal`: il dialog del ui-kit è piccolo e centrato, qui serve una pagina intera
 * con la sua barra (Indietro, titolo) e la safe area di iPad. Resta comunque un dialog
 * modale per la tastiera: il focus entra nel foglio, Tab non esce, Esc lo chiude e al
 * ritorno il focus torna dov'era. Se sopra c'è un altro dialog (conferma di cancellazione),
 * Esc spetta a quello.
 */
import { useEffect, useRef, type KeyboardEvent, type ReactNode } from 'react';
import { ChevronLeft } from 'lucide-react';
import { Button, HeaderBar } from '@anki-studio/ui-kit';

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function Sheet({
  title,
  backLabel,
  onClose,
  children,
  footer,
}: {
  title: string;
  backLabel: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return;
      const dialogs = document.querySelectorAll('[role="dialog"][aria-modal="true"]');
      if (dialogs[dialogs.length - 1] !== ref.current) return;
      onCloseRef.current();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      previous?.focus?.();
    };
  }, []);

  function trapFocus(event: KeyboardEvent<HTMLDivElement>) {
    const root = ref.current;
    // gli eventi dei dialog aperti sopra risalgono fin qui (portale React): non sono nostri
    if (event.key !== 'Tab' || !root || !root.contains(event.target as Node)) return;
    const items = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE));
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === root)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div
      ref={ref}
      role="dialog"
      aria-modal="true"
      aria-label={title}
      tabIndex={-1}
      onKeyDown={trapFocus}
      className="fixed inset-0 z-sheet flex animate-slide-in-right flex-col bg-background outline-none"
    >
      <HeaderBar
        title={title}
        leftContent={
          <Button variant="ghost" size="sm" icon={<ChevronLeft />} onClick={onClose} className="-ml-1.5 pl-1 coarse:h-10">
            {backLabel}
          </Button>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <div className="mx-auto w-full max-w-2xl p-4 pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))]">{children}</div>
      </div>
      {footer ? (
        <div className="shrink-0 border-t bg-background pb-[max(0.75rem,env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] pt-3">
          <div className="mx-auto flex max-w-2xl flex-wrap items-center justify-end gap-2">{footer}</div>
        </div>
      ) : null}
    </div>
  );
}
