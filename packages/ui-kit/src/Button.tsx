/*
 * Bottone base del design system T3 Code.
 *
 * Perché una tabella di varianti invece di classi sparse: il bottone è il
 * controllo più usato e deve restare coerente (un solo `default` blu per vista,
 * `ghost` per le toolbar, `destructive` solo per azioni irreversibili). Il
 * padding è il passo di dimensione meno 1px di bordo, così tutte le varianti
 * (con o senza bordo visibile) hanno la stessa altezza.
 */
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { cn } from './utils.js';
import { Spinner } from './Spinner.js';

export type ButtonVariant =
  | 'default'
  | 'outline'
  | 'secondary'
  | 'ghost'
  | 'ghost-muted'
  | 'destructive'
  | 'destructive-outline'
  | 'ghost-destructive'
  | 'link';

export type ButtonSize =
  | 'xs'
  | 'sm'
  | 'default'
  | 'lg'
  | 'icon-xs'
  | 'icon-sm'
  | 'icon'
  | 'icon-lg';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** `default` è il primario pieno: uno solo per vista. */
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Icona prima della label. */
  icon?: ReactNode;
  /** Icona dopo la label. */
  iconRight?: ReactNode;
  /** Mostra uno spinner al posto dell'icona e disabilita il bottone. */
  loading?: boolean;
  /** Stato "acceso" per i toggle in toolbar (`bg-accent text-foreground`). */
  active?: boolean;
}

const BASE = [
  'group/button relative inline-flex shrink-0 select-none items-center justify-center gap-2',
  'whitespace-nowrap rounded-control border border-transparent text-sm font-medium',
  'transition-[background-color,color,border-color,box-shadow,transform,opacity] duration-150',
  'active:scale-[0.97]',
  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
  'disabled:pointer-events-none disabled:opacity-disabled',
  // Le icone Lucide sono 16px salvo che il chiamante ne imponga la misura.
  '[&_svg]:pointer-events-none [&_svg]:shrink-0',
  '[&_svg:not([class*=size-]):not([class*=w-])]:size-4',
].join(' ');

const VARIANTS: Record<ButtonVariant, string> = {
  default:
    'border-primary bg-primary text-primary-foreground shadow-[shadow:var(--inset-shadow-control-highlight),0_1px_2px_color-mix(in_oklab,var(--primary)_24%,transparent)] hover:bg-primary/90',
  outline:
    'border-input bg-popover text-foreground shadow-control hover:bg-accent/50 dark:bg-input/32 dark:hover:bg-input/50',
  secondary: 'border-border bg-secondary text-secondary-foreground hover:bg-accent',
  ghost: 'text-foreground hover:bg-accent hover:text-accent-foreground',
  'ghost-muted': 'text-muted-foreground hover:bg-accent hover:text-foreground',
  destructive:
    'border-error bg-error text-primary-foreground shadow-control-highlight hover:bg-error/90',
  'destructive-outline':
    'border-input bg-popover text-error-foreground shadow-control hover:bg-error/8 dark:bg-input/32 dark:hover:bg-error/16',
  'ghost-destructive': 'text-error-foreground hover:bg-error/8 dark:hover:bg-error/16',
  link: 'text-primary underline-offset-4 hover:underline',
};

const SIZES: Record<ButtonSize, string> = {
  xs: 'h-6 gap-1 px-[7px] text-xs [&_svg:not([class*=size-]):not([class*=w-])]:size-3.5',
  sm: 'h-7 gap-1.5 px-[9px]',
  default: 'h-8 px-[11px]',
  lg: 'h-9 px-[13px]',
  'icon-xs': 'size-6 px-0 text-xs [&_svg:not([class*=size-]):not([class*=w-])]:size-3.5',
  'icon-sm': 'size-7 px-0',
  icon: 'size-8 px-0',
  'icon-lg': 'size-9 px-0',
};

/**
 * Le icone dei bottoni outline/ghost restano mute e si accendono all'hover,
 * così l'attenzione cade sulla label e non sul glifo.
 */
const MUTED_ICON =
  'text-muted-foreground transition-colors group-hover/button:text-foreground group-data-[active]/button:text-foreground';
const ICON_TONE: Partial<Record<ButtonVariant, string>> = {
  outline: MUTED_ICON,
  ghost: MUTED_ICON,
};

/** Classi di un bottone, riusabili da elementi che non sono `<button>` (es. link). */
export function buttonVariants({
  variant = 'default',
  size = 'default',
  active = false,
  className,
}: {
  variant?: ButtonVariant;
  size?: ButtonSize;
  active?: boolean;
  className?: string;
} = {}): string {
  return cn(BASE, SIZES[size], VARIANTS[variant], active && 'bg-accent text-foreground', className);
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'default',
    size = 'default',
    icon,
    iconRight,
    loading = false,
    active = false,
    className,
    children,
    disabled,
    type = 'button',
    ...props
  },
  ref,
) {
  const iconTone = ICON_TONE[variant];
  const iconOnly = size.startsWith('icon');

  const renderSlot = (node: ReactNode) =>
    node ? (
      <span
        data-slot="icon"
        className={cn('inline-flex shrink-0 items-center justify-center', iconTone)}
      >
        {node}
      </span>
    ) : null;

  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      data-active={active || undefined}
      data-loading={loading || undefined}
      className={buttonVariants({ variant, size, active, className })}
      {...props}
    >
      {loading ? <Spinner /> : renderSlot(icon)}
      {/* Nei bottoni solo-icona lo spinner prende il posto del contenuto. */}
      {loading && iconOnly ? null : children}
      {renderSlot(iconRight)}
    </button>
  );
});
