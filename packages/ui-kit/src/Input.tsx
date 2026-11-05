/*
 * Campo di testo a riga singola.
 *
 * Perché un contenitore attorno all'`<input>`: bordo, ombra e focus ring
 * appartengono al guscio (`focus-within`), così le icone `leading`/`trailing`
 * stanno "dentro" il campo e l'alone di focus le avvolge. `className` va sul
 * guscio (larghezza, margini); per l'elemento nativo c'è `inputClassName`.
 */
import { forwardRef, useRef, type InputHTMLAttributes, type ReactNode } from 'react';
import { cn } from './utils.js';
import {
  CONTROL_FIELD,
  CONTROL_HEIGHT,
  CONTROL_PADDING_X,
  CONTROL_SLOT,
  controlShell,
  useMergedRefs,
  type ControlSize,
} from './shared.js';

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  /** `sm` 28px · `default` 32px · `lg` 36px. */
  size?: ControlSize;
  /** Font monospazio con cifre tabulari (LaTeX, id, numeri). */
  mono?: boolean;
  invalid?: boolean;
  /** Icona a sinistra (es. lente di ricerca). */
  leading?: ReactNode;
  /** Contenuto a destra (icona, unità, bottone di cancellazione). */
  trailing?: ReactNode;
  /** Classi dell'`<input>` nativo; `className` va sul contenitore. */
  inputClassName?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  {
    size = 'default',
    mono = false,
    invalid,
    leading,
    trailing,
    className,
    inputClassName,
    disabled,
    ...props
  },
  ref,
) {
  const innerRef = useRef<HTMLInputElement>(null);
  const mergedRef = useMergedRefs(innerRef, ref);
  const isInvalid = invalid ?? (props['aria-invalid'] === true || props['aria-invalid'] === 'true');

  return (
    <span
      className={cn(controlShell(isInvalid, !!disabled), 'items-center', className)}
      // Un clic sull'icona (o sul padding) porta il focus al campo.
      onMouseDown={(event) => {
        const target = event.target as HTMLElement;
        if (target !== innerRef.current && !target.closest('button, a, [role=button]')) {
          event.preventDefault();
          innerRef.current?.focus();
        }
      }}
    >
      {leading ? (
        <span className={cn(CONTROL_SLOT, 'pointer-events-none pl-[10px]')}>{leading}</span>
      ) : null}
      <input
        ref={mergedRef}
        disabled={disabled}
        aria-invalid={isInvalid || undefined}
        className={cn(
          CONTROL_FIELD,
          CONTROL_HEIGHT[size],
          CONTROL_PADDING_X[size],
          leading && 'pl-2',
          trailing && 'pr-2',
          mono && 'font-mono',
          inputClassName,
        )}
        {...props}
      />
      {trailing ? <span className={cn(CONTROL_SLOT, 'pr-[10px]')}>{trailing}</span> : null}
    </span>
  );
});
