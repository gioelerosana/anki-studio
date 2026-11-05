/*
 * Bottone solo-icona.
 *
 * Perché esiste accanto a `Button`: un bottone senza testo non ha nome
 * accessibile, quindi `label` va sempre fornita (diventa `aria-label` e
 * `title`). Il tipo la lascia opzionale solo per non rompere i vecchi punti
 * d'uso che passano `title`/`aria-label`: i nuovi devono usare `label`.
 */
import { forwardRef, type ReactNode } from 'react';
import { Button, type ButtonProps } from './Button.js';
import { cn } from './utils.js';

export type IconButtonVariant = 'ghost' | 'outline' | 'default' | 'ghost-destructive';
export type IconButtonSize = 'xs' | 'sm' | 'md' | 'lg';

export interface IconButtonProps
  extends Omit<ButtonProps, 'variant' | 'size' | 'icon' | 'iconRight' | 'children'> {
  /**
   * Nome accessibile e tooltip nativo. OBBLIGATORIO a livello di contratto
   * (opzionale nel tipo solo per compatibilità). Per sopprimere il tooltip
   * nativo, ad esempio dentro un `Tooltip`, passa `title=""`.
   */
  label?: string;
  variant?: IconButtonVariant;
  /** `xs` 24 · `sm` 28 · `md` 32 (default) · `lg` 36. */
  size?: IconButtonSize;
  children?: ReactNode;
}

const SIZE_MAP = {
  xs: 'icon-xs',
  sm: 'icon-sm',
  md: 'icon',
  lg: 'icon-lg',
} as const;

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, variant = 'ghost', size = 'md', title, className, children, ...props },
  ref,
) {
  const name = label ?? title ?? props['aria-label'];
  return (
    <Button
      ref={ref}
      // L'icona è muta di default e si accende all'hover (come `ghost-muted`).
      variant={variant === 'ghost' ? 'ghost-muted' : variant}
      size={SIZE_MAP[size]}
      title={title ?? label}
      aria-label={props['aria-label'] ?? name}
      className={cn(
        variant === 'outline' && 'text-muted-foreground hover:text-foreground',
        className,
      )}
      {...props}
    >
      {children}
    </Button>
  );
});
