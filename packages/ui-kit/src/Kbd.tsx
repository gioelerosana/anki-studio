/*
 * Tasti e scorciatoie da tastiera.
 *
 * Perché `formatShortcut`: le scorciatoie arrivano come stringhe ("Ctrl+Shift+S")
 * dai menu e dai tooltip. Normalizzarle in un array di tasti in un solo punto
 * garantisce che ovunque "Esc", "Enter" o le frecce abbiano la stessa resa.
 */
import { forwardRef, type HTMLAttributes } from 'react';
import { cn } from './utils.js';

export type KbdProps = HTMLAttributes<HTMLElement>;

export const Kbd = forwardRef<HTMLElement, KbdProps>(function Kbd(
  { className, ...props },
  ref,
) {
  return (
    <kbd
      ref={ref}
      className={cn(
        'pointer-events-none inline-flex h-5 min-w-5 select-none items-center justify-center gap-1 rounded-[4px] bg-muted px-1 font-sans text-xs font-medium text-muted-foreground [&_svg:not([class*=size-])]:size-3',
        className,
      )}
      {...props}
    />
  );
});

export const KbdGroup = forwardRef<HTMLSpanElement, HTMLAttributes<HTMLSpanElement>>(
  function KbdGroup({ className, ...props }, ref) {
    return (
      <span ref={ref} className={cn('inline-flex items-center gap-1', className)} {...props} />
    );
  },
);

/** Alias di visualizzazione per i nomi di tasto più comuni. */
const KEY_LABELS: Record<string, string> = {
  control: 'Ctrl',
  ctrl: 'Ctrl',
  option: 'Alt',
  alt: 'Alt',
  shift: 'Shift',
  meta: 'Super',
  super: 'Super',
  cmd: '⌘',
  command: '⌘',
  enter: '↵',
  return: '↵',
  escape: 'Esc',
  esc: 'Esc',
  delete: 'Del',
  del: 'Del',
  backspace: '⌫',
  tab: 'Tab',
  space: 'Spazio',
  arrowup: '↑',
  up: '↑',
  arrowdown: '↓',
  down: '↓',
  arrowleft: '←',
  left: '←',
  arrowright: '→',
  right: '→',
  pageup: 'PgSu',
  pagedown: 'PgGiù',
  home: 'Home',
  end: 'Fine',
};

function isMac(): boolean {
  return typeof navigator !== 'undefined' && /mac|iphone|ipad/i.test(navigator.platform ?? '');
}

/**
 * Scompone una scorciatoia ("Ctrl+Shift+S") nei tasti da mostrare.
 * `Mod` è il modificatore primario della piattaforma (⌘ su macOS, Ctrl altrove);
 * le lettere singole diventano maiuscole.
 */
export function formatShortcut(shortcut: string): string[] {
  return shortcut
    .split('+')
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const lower = part.toLowerCase();
      if (lower === 'mod') return isMac() ? '⌘' : 'Ctrl';
      if (KEY_LABELS[lower]) return KEY_LABELS[lower];
      return part.length === 1 ? part.toUpperCase() : part;
    });
}

export interface ShortcutProps extends Omit<HTMLAttributes<HTMLSpanElement>, 'children'> {
  /** Stringa ("Ctrl+S") oppure array di tasti già pronti. */
  keys: string | readonly string[];
}

export function Shortcut({ keys, className, ...props }: ShortcutProps) {
  const parts = typeof keys === 'string' ? formatShortcut(keys) : keys;
  if (parts.length === 0) return null;
  return (
    <KbdGroup className={className} {...props}>
      {parts.map((key, index) => (
        <Kbd key={`${key}-${index}`}>{key}</Kbd>
      ))}
    </KbdGroup>
  );
}
