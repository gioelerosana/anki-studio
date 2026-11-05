/*
 * Linea di separazione hairline.
 *
 * Perché `bg-border` e non `border-t`: un elemento con altezza/larghezza di
 * 1px funziona uguale in orizzontale e in verticale dentro contenitori flex e
 * non dipende dal bordo del genitore.
 */
import type { HTMLAttributes } from 'react';
import { cn } from './utils.js';

export interface SeparatorProps extends HTMLAttributes<HTMLDivElement> {
  orientation?: 'horizontal' | 'vertical';
  /** Solo decorativo: nasconde il separatore agli screen reader. */
  decorative?: boolean;
}

export function Separator({
  orientation = 'horizontal',
  decorative = false,
  className,
  ...props
}: SeparatorProps) {
  return (
    <div
      role={decorative ? 'none' : 'separator'}
      aria-orientation={decorative || orientation === 'horizontal' ? undefined : orientation}
      className={cn(
        'shrink-0 bg-border',
        orientation === 'horizontal' ? 'h-px w-full' : 'w-px self-stretch',
        className,
      )}
      {...props}
    />
  );
}
