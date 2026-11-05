/*
 * Interruttore on/off.
 *
 * Perché `role="switch"` su un `<button>`: ha tastiera (Spazio/Invio), focus e
 * stato `disabled` nativi e si può avvolgere in una `<label>` per rendere
 * cliccabile il testo. La traccia è `primary` solo da attiva: è l'unico colore
 * d'azione dell'interfaccia, quindi acceso = "questa opzione è in vigore".
 */
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cn } from './utils.js';
import { useControllableChecked } from './shared.js';

export interface SwitchProps
  extends Omit<
    ButtonHTMLAttributes<HTMLButtonElement>,
    'onChange' | 'role' | 'children' | 'defaultChecked'
  > {
  checked?: boolean;
  /** Valore iniziale se non controllato. */
  defaultChecked?: boolean;
  onCheckedChange?: (checked: boolean) => void;
  /** Testo accanto all'interruttore; cliccandolo si commuta. */
  label?: ReactNode;
}

export const Switch = forwardRef<HTMLButtonElement, SwitchProps>(function Switch(
  {
    checked,
    defaultChecked,
    onCheckedChange,
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

  const control = (
    <button
      ref={ref}
      type={type}
      role="switch"
      aria-checked={value}
      disabled={disabled}
      data-state={value ? 'checked' : 'unchecked'}
      onClick={(event) => {
        onClick?.(event);
        if (!event.defaultPrevented) setValue(!value);
      }}
      className={cn(
        'inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border border-transparent transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background',
        'disabled:pointer-events-none disabled:opacity-disabled',
        value ? 'bg-primary' : 'bg-input',
        !label && className,
      )}
      {...props}
    >
      <span
        aria-hidden
        className={cn(
          'pointer-events-none block size-4 rounded-full bg-primary-foreground shadow-control transition-transform duration-150',
          value ? 'translate-x-4' : 'translate-x-0.5',
        )}
      />
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
