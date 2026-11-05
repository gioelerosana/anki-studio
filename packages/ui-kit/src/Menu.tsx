/*
 * Menu a comparsa con navigazione da tastiera.
 *
 * Perché non un portale: il chiamante posiziona il wrapper (`relative`) e il
 * pannello gli si ancora sotto, come nelle barre di Electron dove le regioni
 * trascinabili escludono già `[role=menu]`. L'Esc è intercettato in fase di
 * cattura per chiudere solo il menu, non anche un Modal che lo contiene.
 */
import {
  Fragment,
  cloneElement,
  isValidElement,
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactElement,
  type ReactNode,
} from 'react';
import { cn } from './utils.js';
import { Separator } from './Separator.js';
import { Shortcut } from './Kbd.js';

export interface MenuItem {
  id: string;
  label: string;
  icon?: ReactNode;
  /** Scorciatoia mostrata a destra, es. `"Ctrl+O"`. */
  shortcut?: string;
  disabled?: boolean;
  /** Azione distruttiva: testo `error-foreground`. */
  danger?: boolean;
  separatorBefore?: boolean;
  onSelect: () => void;
}

export interface MenuProps {
  items: MenuItem[];
  trigger: ReactNode;
  align?: 'start' | 'end';
  className?: string;
  widthClass?: string;
}

const ITEM_SELECTOR = '[role="menuitem"]:not([disabled])';
const TRIGGER_FOCUS_SELECTOR = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

export function Menu({ items, trigger, align = 'end', className, widthClass = 'w-60' }: MenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const close = useCallback((restoreFocus: boolean) => {
    setOpen(false);
    if (restoreFocus) {
      triggerRef.current?.querySelector<HTMLElement>(TRIGGER_FOCUS_SELECTOR)?.focus();
    }
  }, []);

  const enabledItems = () =>
    Array.from(panelRef.current?.querySelectorAll<HTMLElement>(ITEM_SELECTOR) ?? []);

  // Chiusura con clic fuori ed Esc (in cattura, vedi nota in testa al file).
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.stopPropagation();
      close(true);
    };
    window.addEventListener('mousedown', onPointerDown);
    window.addEventListener('keydown', onKey, true);
    return () => {
      window.removeEventListener('mousedown', onPointerDown);
      window.removeEventListener('keydown', onKey, true);
    };
  }, [open, close]);

  // All'apertura il focus va alla prima voce abilitata.
  useEffect(() => {
    if (open) enabledItems()[0]?.focus();
  }, [open]);

  const onPanelKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const list = enabledItems();
    if (list.length === 0) return;
    const index = list.indexOf(document.activeElement as HTMLElement);
    let target: HTMLElement | undefined;
    switch (event.key) {
      case 'ArrowDown':
        target = list[(index + 1) % list.length];
        break;
      case 'ArrowUp':
        target = list[(index - 1 + list.length) % list.length];
        break;
      case 'Home':
        target = list[0];
        break;
      case 'End':
        target = list[list.length - 1];
        break;
      case 'Tab':
        setOpen(false);
        return;
      default:
        return;
    }
    event.preventDefault();
    target?.focus();
  };

  const onTriggerKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!open && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
      event.preventDefault();
      setOpen(true);
    }
  };

  // Il trigger espone lo stato del menu agli ausili senza che il chiamante lo sappia.
  const decoratedTrigger =
    isValidElement(trigger) && trigger.type !== Fragment
      ? cloneElement(trigger as ReactElement<Record<string, unknown>>, {
          'aria-haspopup': (trigger.props as Record<string, unknown>)['aria-haspopup'] ?? 'menu',
          'aria-expanded': open,
        })
      : trigger;

  return (
    <div ref={rootRef} className={cn('relative', className)}>
      <div ref={triggerRef} onClick={() => setOpen((value) => !value)} onKeyDown={onTriggerKeyDown}>
        {decoratedTrigger}
      </div>
      {open && (
        <div
          ref={panelRef}
          role="menu"
          aria-orientation="vertical"
          onKeyDown={onPanelKeyDown}
          className={cn(
            'surface-glass absolute top-[calc(100%+6px)] z-50 max-h-[calc(100dvh-4rem)] animate-pop-in overflow-y-auto rounded-lg border p-1 text-sm text-popover-foreground shadow-dialog',
            widthClass,
            align === 'end' ? 'right-0' : 'left-0',
          )}
        >
          {items.map((item) => (
            <Fragment key={item.id}>
              {item.separatorBefore && <Separator className="my-1" />}
              <button
                type="button"
                role="menuitem"
                disabled={item.disabled}
                onClick={() => {
                  close(true);
                  item.onSelect();
                }}
                className={cn(
                  'flex h-8 w-full select-none items-center gap-2 rounded-md px-2 text-left text-sm outline-none transition-colors',
                  'disabled:pointer-events-none disabled:opacity-disabled',
                  item.danger
                    ? 'text-error-foreground hover:bg-error/8 focus-visible:bg-error/8 dark:hover:bg-error/16 dark:focus-visible:bg-error/16'
                    : 'text-foreground hover:bg-accent focus-visible:bg-accent',
                )}
              >
                {item.icon ? (
                  <span
                    className={cn(
                      'flex shrink-0 items-center [&_svg:not([class*=size-]):not([class*=w-])]:size-4',
                      item.danger ? 'text-error-foreground' : 'text-muted-foreground',
                    )}
                  >
                    {item.icon}
                  </span>
                ) : null}
                <span className="flex-1 truncate">{item.label}</span>
                {item.shortcut ? <Shortcut keys={item.shortcut} className="shrink-0 max-sm:hidden coarse:hidden" /> : null}
              </button>
            </Fragment>
          ))}
        </div>
      )}
    </div>
  );
}
