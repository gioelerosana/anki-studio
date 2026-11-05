/*
 * Casella di spunta.
 *
 * Perché non `<input type="checkbox">` stilizzato: gli stili nativi non si
 * lasciano tematizzare in modo uniforme tra Chromium e Electron. Il `<button
 * role="checkbox">` dà lo stesso comportamento (tastiera, label cliccabile) e
 * supporta lo stato intermedio per le selezioni parziali.
 */
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { Check, Minus } from 'lucide-react';
import { cn } from './utils.js';
import { useControllableChecked } from './shared.js';

export interface CheckboxProps
  extends Omit<
    ButtonHTMLAttributes<HTMLButtonElement>,
    'onChange' | 'role' | 'children' | 'defaultChecked'
  > {
  checked?: boolean;
  defaultChecked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
  /** Selezione parziale (mostra un trattino, `aria-checked="mixed"`). */
  indeterminate?: boolean;
  /** Testo accanto alla casella; cliccandolo si commuta. */
  label?: ReactNode;
}

export const Checkbox = forwardRef<HTMLButtonElement, CheckboxProps>(function Checkbox(
  {
    checked,
    defaultChecked,
    onCheckedChange,
    indeterminate = false,
    label,
    disabled,
    className,
    onClick,
    type = 'button',
    ...props
  },
  ref,
) {
  const [value, setValue] = useControllableChecked(checked, defaultChecked, onCheckedChange);
  const on = value || indeterminate;

  const control = (
    <button
      ref={ref}
      type={type}
      role="checkbox"
      aria-checked={indeterminate ? 'mixed' : value}
      disabled={disabled}
      data-state={indeterminate ? 'indeterminate' : value ? 'checked' : 'unchecked'}
      onClick={(event) => {
        onClick?.(event);
        if (!event.defaultPrevented) setValue(indeterminate ? true : !value);
      }}
      className={cn(
        'inline-flex size-4 shrink-0 cursor-pointer items-center justify-center rounded-sm border transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background',
        'disabled:pointer-events-none disabled:opacity-disabled',
        on
          ? 'border-primary bg-primary text-primary-foreground'
          : 'border-input bg-background shadow-control dark:bg-input/32',
        !label && className,
      )}
      {...props}
    >
      {indeterminate ? (
        <Minus aria-hidden className="size-3" strokeWidth={3} />
      ) : value ? (
        <Check aria-hidden className="size-3" strokeWidth={3} />
      ) : null}
    </button>
  );

  if (!label) return control;

  return (
    <label
      className={cn(
        'inline-flex cursor-pointer select-none items-center gap-2 text-sm text-foreground',
        disabled && 'pointer-events-none opacity-disabled',
        className,
      )}
    >
      {control}
      <span>{label}</span>
    </label>
  );
});
