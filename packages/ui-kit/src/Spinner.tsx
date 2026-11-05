/*
 * Indicatore di attività.
 *
 * Perché un componente dedicato: Button (stato `loading`), Banner e le schermate
 * di caricamento devono mostrare lo stesso spinner, con la stessa animazione e
 * senza ripetere l'icona e le classi in ogni punto.
 */
import { Loader2 } from 'lucide-react';
import { cn } from './utils.js';

export interface SpinnerProps {
  className?: string;
  /**
   * Testo per gli screen reader. Se assente lo spinner è decorativo
   * (`aria-hidden`), come quando sta dentro un bottone che ha già una label.
   */
  label?: string;
}

export function Spinner({ className, label }: SpinnerProps) {
  return (
    <Loader2
      className={cn('size-4 shrink-0 animate-spin', className)}
      {...(label ? { role: 'status', 'aria-label': label } : { 'aria-hidden': true })}
    />
  );
}
