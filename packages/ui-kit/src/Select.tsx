/*
 * Menu a tendina nativo con lo stile dei campi.
 *
 * Perché `<select>` nativo e non un popover custom: tastiera, accessibilità e
 * lettori di schermo funzionano gratis, e per elenchi corti (formato di
 * esportazione, tema) basta. Il chevron è decorativo e non intercetta clic.
 */
import { forwardRef, type SelectHTMLAttributes } from 'react';
import { ChevronDown } from 'lucide-react';
import { cn } from './utils.js';
import {
  CONTROL_FIELD,
  CONTROL_HEIGHT,
  controlShell,
  type ControlSize,
} from './shared.js';

export interface SelectOption {
  value: string | number;
  label: string;
  disabled?: boolean;
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'size'> {
  size?: ControlSize;
  invalid?: boolean;
  /** Alternativa ai children `<option>`. */
  options?: SelectOption[];
  /** Classi del `<select>` nativo; `className` va sul contenitore. */
  selectClassName?: string;
}

const PADDING: Record<ControlSize, string> = {
  sm: 'pl-[9px] pr-7',
  default: 'pl-[11px] pr-8',
  lg: 'pl-[13px] pr-9',
};

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { size = 'default', invalid, options, className, selectClassName, disabled, children, ...props },
  ref,
) {
  const isInvalid = invalid ?? (props['aria-invalid'] === true || props['aria-invalid'] === 'true');
  return (
    <span className={cn(controlShell(isInvalid, !!disabled), 'items-center', className)}>
      <select
        ref={ref}
        disabled={disabled}
        aria-invalid={isInvalid || undefined}
        className={cn(
          CONTROL_FIELD,
          'w-full cursor-pointer appearance-none',
          CONTROL_HEIGHT[size],
          PADDING[size],
          selectClassName,
        )}
        {...props}
      >
        {options
          ? options.map((option) => (
              <option key={String(option.value)} value={option.value} disabled={option.disabled}>
                {option.label}
              </option>
            ))
          : children}
      </select>
      <ChevronDown
        aria-hidden
        className="pointer-events-none absolute right-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
      />
    </span>
  );
});
