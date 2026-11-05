/*
 * Utility di classi condivise da tutti i componenti.
 *
 * Perché `extendTailwindMerge`: le classi personalizzate del design system
 * (`text-2xs`, `rounded-control`, `shadow-dialog`, `opacity-disabled`…) non
 * sono nella configurazione di default di tailwind-merge. Senza registrarle,
 * `text-2xs` verrebbe scambiata per un colore del testo e cancellata da un
 * `text-primary` successivo (o viceversa), e le ombre custom verrebbero
 * trattate come colori d'ombra. Il nome in `theme` è la chiave dell'estensione
 * Tailwind corrispondente (apps/web/tailwind.config.js).
 */
import { clsx, type ClassValue } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';

const twMerge = extendTailwindMerge({
  extend: {
    theme: {
      // Dimensioni del testo: devono battere il gruppo "colore del testo".
      text: ['2xs', '3xs'],
      radius: ['control'],
      shadow: ['control', 'composer', 'dialog', 'control-highlight', 'control-pressed'],
      ease: ['sheet'],
      // Misure di layout (`h-topbar`, `w-sidebar`, `w-inspector`).
      spacing: ['topbar', 'sidebar', 'inspector'],
    },
    classGroups: {
      opacity: [{ opacity: ['disabled'] }],
      z: [{ z: ['sheet'] }],
    },
  },
});

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
