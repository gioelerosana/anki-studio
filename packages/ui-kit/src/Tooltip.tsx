/*
 * Tooltip leggero, senza dipendenze.
 *
 * Perché non una libreria di posizionamento: l'app ha solo toolbar e barre
 * dove il tooltip sta sopra o sotto il bersaglio. Un contenitore `relative`
 * con una bolla assoluta basta, e il ritardo di 400ms evita che i tooltip
 * scattino mentre il puntatore attraversa la barra. Per default compare sotto
 * (la barra superiore sta a filo del bordo della finestra).
 */
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type HTMLAttributes,
  type ReactNode,
} from 'react';
import { cn } from './utils.js';
import { Shortcut } from './Kbd.js';

export interface TooltipProps extends Omit<HTMLAttributes<HTMLSpanElement>, 'content'> {
  content: ReactNode;
  /** Scorciatoia mostrata accanto al testo, es. `"Ctrl+S"`. */
  shortcut?: string;
  side?: 'top' | 'bottom';
  align?: 'start' | 'center' | 'end';
  /** Ritardo di comparsa in ms. */
  delay?: number;
  disabled?: boolean;
  children: ReactNode;
}

const SIDE: Record<NonNullable<TooltipProps['side']>, string> = {
  top: 'bottom-full pb-1.5',
  bottom: 'top-full pt-1.5',
};

const ALIGN: Record<NonNullable<TooltipProps['align']>, string> = {
  start: 'left-0 justify-start',
  center: 'inset-x-0 justify-center',
  end: 'right-0 justify-end',
};

export function Tooltip({
  content,
  shortcut,
  side = 'bottom',
  align = 'center',
  delay = 400,
  disabled = false,
  className,
  children,
  onMouseEnter,
  onMouseLeave,
  onMouseDown,
  onFocus,
  onBlur,
  onKeyDown,
  ...props
}: TooltipProps) {
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const id = useId();
  // Il focus causato da un clic non deve riaprire il tooltip appena chiuso.
  const pointerFocus = useRef(false);

  const show = useCallback(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setOpen(true), delay);
  }, [delay]);

  const hide = useCallback(() => {
    clearTimeout(timer.current);
    setOpen(false);
  }, []);

  useEffect(() => () => clearTimeout(timer.current), []);

  if (disabled || !content) return <>{children}</>;

  return (
    <span
      className={cn('relative inline-flex', className)}
      onMouseEnter={(event) => {
        onMouseEnter?.(event);
        show();
      }}
      onMouseLeave={(event) => {
        onMouseLeave?.(event);
        hide();
      }}
      // Un clic è già un'azione: il tooltip non deve restare sopra il risultato.
      onMouseDown={(event) => {
        onMouseDown?.(event);
        pointerFocus.current = true;
        setTimeout(() => {
          pointerFocus.current = false;
        }, 0);
        hide();
      }}
      onFocus={(event) => {
        onFocus?.(event);
        if (!pointerFocus.current) show();
      }}
      onBlur={(event) => {
        onBlur?.(event);
        hide();
      }}
      onKeyDown={(event) => {
        onKeyDown?.(event);
        if (event.key === 'Escape') hide();
      }}
      aria-describedby={open ? id : undefined}
      {...props}
    >
      {children}
      {open ? (
        <span
          role="tooltip"
          id={id}
          className={cn('pointer-events-none absolute z-[60] flex', SIDE[side], ALIGN[align])}
        >
          <span className="surface-glass flex animate-pop-in items-center gap-2 whitespace-nowrap rounded-md border px-2 py-1 text-xs text-popover-foreground shadow-composer">
            {content}
            {shortcut ? <Shortcut keys={shortcut} /> : null}
          </span>
        </span>
      ) : null}
    </span>
  );
}
