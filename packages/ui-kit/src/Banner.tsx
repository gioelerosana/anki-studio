/*
 * Avviso in linea (non modale) con tinta di stato.
 *
 * Perché un componente e non classi sparse: errori di salvataggio, XMind aperto
 * o file non valido compaiono in più viste e devono avere la stessa
 * gerarchia: icona, titolo, testo, azione opzionale a destra.
 */
import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';
import { cn } from './utils.js';
import { STATUS_BORDER, STATUS_ICON, STATUS_TEXT, STATUS_TINT, type StatusTone } from './shared.js';

export interface BannerProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  variant?: StatusTone;
  title?: ReactNode;
  /** Icona personalizzata; `null` la nasconde. Di default dipende dalla variante. */
  icon?: ReactNode;
  /** Azione a destra (es. un `Button size="xs"`). */
  action?: ReactNode;
  children?: ReactNode;
}

export const Banner = forwardRef<HTMLDivElement, BannerProps>(function Banner(
  { variant = 'info', title, icon, action, className, children, ...props },
  ref,
) {
  const DefaultIcon = STATUS_ICON[variant];
  return (
    <div
      ref={ref}
      role={variant === 'error' || variant === 'warning' ? 'alert' : 'status'}
      className={cn(
        'flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-sm',
        STATUS_TINT[variant],
        STATUS_BORDER[variant],
        STATUS_TEXT[variant],
        className,
      )}
      {...props}
    >
      {icon === null ? null : (
        <span className="mt-0.5 flex shrink-0 items-center [&_svg:not([class*=size-])]:size-4">
          {icon ?? <DefaultIcon aria-hidden />}
        </span>
      )}
      <div className="min-w-0 flex-1">
        {title ? <p className="font-medium">{title}</p> : null}
        {children ? <div className={cn(title && 'mt-0.5 text-xs/5')}>{children}</div> : null}
      </div>
      {action ? <div className="flex shrink-0 items-center gap-1">{action}</div> : null}
    </div>
  );
});
