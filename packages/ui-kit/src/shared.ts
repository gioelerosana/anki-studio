/*
 * Helper interni del ui-kit (NON esportati da `index.ts`).
 *
 * Perché un file a parte: tinte di stato, guscio dei campi di input, merge
 * delle ref e stato controllato/non controllato servono a più componenti.
 * Tenerli qui evita che Badge, Banner e Toast divergano sui colori di stato e
 * che Input, Textarea e Select abbiano tre focus ring leggermente diversi.
 */
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Info,
  type LucideIcon,
} from 'lucide-react';
import { useCallback, useState, type Ref, type RefCallback } from 'react';

/* ------------------------------------------------------------------ */
/* Stati (info / success / warning / error)                            */
/* ------------------------------------------------------------------ */

export type StatusTone = 'info' | 'success' | 'warning' | 'error';

/** Tinta di sfondo: 8% in chiaro, 16% in scuro ("lo stato si tinge, non si urla"). */
export const STATUS_TINT: Record<StatusTone, string> = {
  info: 'bg-info/8 dark:bg-info/16',
  success: 'bg-success/8 dark:bg-success/16',
  warning: 'bg-warning/8 dark:bg-warning/16',
  error: 'bg-error/8 dark:bg-error/16',
};

/** Colore del testo/icona leggibile sopra la tinta. */
export const STATUS_TEXT: Record<StatusTone, string> = {
  info: 'text-info-foreground',
  success: 'text-success-foreground',
  warning: 'text-warning-foreground',
  error: 'text-error-foreground',
};

/** Bordo hairline dello stato, appena più marcato della tinta. */
export const STATUS_BORDER: Record<StatusTone, string> = {
  info: 'border-info/24',
  success: 'border-success/24',
  warning: 'border-warning/24',
  error: 'border-error/24',
};

export const STATUS_ICON: Record<StatusTone, LucideIcon> = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  error: AlertCircle,
};

/* ------------------------------------------------------------------ */
/* Guscio dei campi (Input, Textarea, Select)                          */
/* ------------------------------------------------------------------ */

export type ControlSize = 'sm' | 'default' | 'lg';

const SHELL_BASE =
  'relative inline-flex w-full rounded-lg border bg-background text-foreground shadow-control transition-shadow dark:bg-input/32';

/**
 * Classi del contenitore di un campo. Il focus ring è un alone interno al 24%
 * (`focus-within`), così vale anche quando il focus è su un figlio nativo.
 */
export function controlShell(invalid: boolean, disabled: boolean): string {
  return [
    SHELL_BASE,
    invalid
      ? 'border-[color-mix(in_oklab,var(--error)_36%,transparent)] focus-within:border-error focus-within:shadow-[inset_0_0_0_3px_color-mix(in_oklab,var(--error)_24%,transparent)]'
      : 'border-input focus-within:border-ring focus-within:shadow-[inset_0_0_0_3px_color-mix(in_oklab,var(--ring)_24%,transparent)]',
    disabled && 'pointer-events-none opacity-disabled',
  ]
    .filter(Boolean)
    .join(' ');
}

/** Altezza del contenuto (il bordo di 1px per lato porta il totale a 28/32/36). */
export const CONTROL_HEIGHT: Record<ControlSize, string> = {
  sm: 'h-[26px]',
  default: 'h-[30px]',
  lg: 'h-[34px]',
};

/** Padding orizzontale = scala dei bottoni meno 1px di bordo. */
export const CONTROL_PADDING_X: Record<ControlSize, string> = {
  sm: 'px-[9px]',
  default: 'px-[11px]',
  lg: 'px-[13px]',
};

/** Aspetto del testo nativo dentro il guscio. */
export const CONTROL_FIELD =
  'min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed';

/** Slot per icone a sinistra/destra del campo. */
export const CONTROL_SLOT =
  'flex shrink-0 items-center text-muted-foreground [&_svg:not([class*=size-])]:size-4';

/* ------------------------------------------------------------------ */
/* Ref e stato                                                          */
/* ------------------------------------------------------------------ */

type AnyRef<T> = Ref<T> | undefined;

/** Unisce più ref (callback o oggetto) in una sola callback ref. */
export function useMergedRefs<T>(...refs: AnyRef<T>[]): RefCallback<T> {
  // La callback viene ricreata solo quando cambia davvero una delle ref.
  return useCallback(
    (node: T | null) => {
      for (const ref of refs) {
        if (typeof ref === 'function') ref(node);
        else if (ref) (ref as { current: T | null }).current = node;
      }
    },
    refs,
  );
}

/**
 * Stato booleano controllato (`checked` + `onCheckedChange`) o non controllato
 * (`defaultChecked`), come i controlli nativi.
 */
export function useControllableChecked(
  checked: boolean | undefined,
  defaultChecked: boolean | undefined,
  onCheckedChange: ((checked: boolean) => void) | undefined,
): [boolean, (next: boolean) => void] {
  const [inner, setInner] = useState(defaultChecked ?? false);
  const controlled = checked !== undefined;
  const value = controlled ? checked : inner;
  const set = useCallback(
    (next: boolean) => {
      if (!controlled) setInner(next);
      onCheckedChange?.(next);
    },
    [controlled, onCheckedChange],
  );
  return [value, set];
}

/** Selettore degli elementi raggiungibili con Tab (trap del focus nei dialog). */
export const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
