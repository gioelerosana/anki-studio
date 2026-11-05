/*
 * Badge e pillole di stato.
 *
 * Perché le tinte invece dei riempimenti: lo stato si legge ma non urla
 * (principio 4 del design system). Le varianti di stato condividono le tinte
 * con Banner e Toast tramite `shared.ts`.
 */
import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';
import { cn } from './utils.js';
import { STATUS_TEXT, STATUS_TINT } from './shared.js';

export type BadgeVariant =
  | 'default'
  | 'secondary'
  | 'outline'
  | 'error'
  | 'info'
  | 'success'
  | 'warning';

export type BadgeSize = 'sm' | 'default' | 'lg';

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  /** `sm` 16px · `default` 18px · `lg` 22px. */
  size?: BadgeSize;
  /** Icona da 12px prima del testo. */
  icon?: ReactNode;
}

const BASE =
  'inline-flex shrink-0 items-center justify-center gap-1 whitespace-nowrap rounded-sm border border-transparent font-medium [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*=size-])]:size-3';

const VARIANTS: Record<BadgeVariant, string> = {
  default: 'bg-primary text-primary-foreground',
  secondary: 'border-border bg-secondary text-secondary-foreground',
  outline: 'border-input bg-background text-foreground',
  error: cn(STATUS_TINT.error, STATUS_TEXT.error),
  info: cn(STATUS_TINT.info, STATUS_TEXT.info),
  success: cn(STATUS_TINT.success, STATUS_TEXT.success),
  warning: cn(STATUS_TINT.warning, STATUS_TEXT.warning),
};

const SIZES: Record<BadgeSize, string> = {
  sm: 'h-4 min-w-4 px-[3px] text-3xs',
  default: 'h-[18px] min-w-[18px] px-[3px] text-xs',
  lg: 'h-[22px] min-w-[22px] px-[5px] text-sm',
};

export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(function Badge(
  { variant = 'default', size = 'default', icon, className, children, ...props },
  ref,
) {
  return (
    <span ref={ref} className={cn(BASE, SIZES[size], VARIANTS[variant], className)} {...props}>
      {icon}
      {children}
    </span>
  );
});
