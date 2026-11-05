/*
 * Card e Section: i due mattoni dei pannelli.
 *
 * Perché `Card` è solo bordo + sfondo e `Section` non ha padding: l'Inspector e
 * le schermate di impostazioni compongono pannelli diversi; chi usa questi
 * componenti decide spaziature e divisori, ma titoli, descrizioni e azioni di
 * sezione hanno sempre la stessa tipografia.
 */
import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';
import { cn } from './utils.js';

export const Card = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(function Card(
  { className, ...props },
  ref,
) {
  return (
    <div
      ref={ref}
      className={cn('rounded-lg border bg-card text-card-foreground', className)}
      {...props}
    />
  );
});

export interface SectionProps extends Omit<HTMLAttributes<HTMLElement>, 'title'> {
  title: ReactNode;
  description?: ReactNode;
  /** Azioni a destra del titolo (es. `IconButton size="xs"`). */
  actions?: ReactNode;
  children?: ReactNode;
}

export const Section = forwardRef<HTMLElement, SectionProps>(function Section(
  { title, description, actions, className, children, ...props },
  ref,
) {
  return (
    <section ref={ref} className={cn('flex flex-col gap-2', className)} {...props}>
      <header className="flex min-h-6 items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-medium text-foreground">{title}</h3>
          {description ? <p className="text-2xs text-muted-foreground">{description}</p> : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-1">{actions}</div> : null}
      </header>
      {children}
    </section>
  );
});
