/*
 * Stato vuoto compatto.
 *
 * Perché un componente piccolo: elenchi, sidebar e inspector senza contenuto
 * mostrano un suggerimento breve (icona, titolo, descrizione, azione) invece di
 * un'illustrazione. Resta silenzioso: colori mute, nessun riempimento.
 */
import type { HTMLAttributes, ReactNode } from 'react';
import { cn } from './utils.js';

export interface EmptyHintProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}

export function EmptyHint({ icon, title, description, action, className, ...props }: EmptyHintProps) {
  return (
    <div
      className={cn('flex flex-col items-center gap-3 px-4 py-8 text-center', className)}
      {...props}
    >
      {icon ? (
        <span className="flex size-9 items-center justify-center rounded-lg border bg-muted text-muted-foreground [&_svg:not([class*=size-])]:size-4">
          {icon}
        </span>
      ) : null}
      <div className="flex max-w-xs flex-col gap-1">
        <p className="text-sm font-medium text-foreground">{title}</p>
        {description ? (
          <p className="text-balance text-xs text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {action ? <div className="flex items-center gap-2">{action}</div> : null}
    </div>
  );
}
