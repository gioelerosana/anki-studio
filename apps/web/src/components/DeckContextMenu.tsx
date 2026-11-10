/*
 * Menu contestuale di un mazzo, ancorato al punto del clic destro (o del tocco lungo).
 *
 * Perché non il `Menu` del ui-kit: quello si àncora a un trigger, qui il punto è del
 * puntatore. Il pannello è `fixed` e si tiene dentro lo schermo; Esc, clic fuori e
 * scroll lo chiudono, le frecce spostano il focus come nel Menu.
 */
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from 'react';
import { cn } from '@anki-studio/ui-kit';

export interface DeckContextItem {
  id: string;
  label: string;
  icon?: ReactNode;
  onSelect: () => void;
}

const MARGIN = 8;

export function DeckContextMenu({
  x,
  y,
  title,
  items,
  onClose,
}: {
  x: number;
  y: number;
  title: string;
  items: DeckContextItem[];
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: x, top: y });

  // Dopo il primo render si conosce la dimensione: si riporta il pannello dentro lo schermo.
  useLayoutEffect(() => {
    const el = panelRef.current;
    if (!el) return;
    const { width, height } = el.getBoundingClientRect();
    setPos({
      left: Math.max(MARGIN, Math.min(x, window.innerWidth - width - MARGIN)),
      top: Math.max(MARGIN, Math.min(y, window.innerHeight - height - MARGIN)),
    });
    el.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
  }, [x, y]);

  useEffect(() => {
    const onPointerDown = (e: PointerEvent) => {
      if (!panelRef.current?.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onClose();
      }
    };
    // Il capture serve a vedere lo scroll della lista (che non risale fino a window).
    window.addEventListener('pointerdown', onPointerDown, true);
    window.addEventListener('keydown', onKey, true);
    window.addEventListener('scroll', onClose, true);
    window.addEventListener('resize', onClose);
    return () => {
      window.removeEventListener('pointerdown', onPointerDown, true);
      window.removeEventListener('keydown', onKey, true);
      window.removeEventListener('scroll', onClose, true);
      window.removeEventListener('resize', onClose);
    };
  }, [onClose]);

  function onKeyDown(e: ReactKeyboardEvent) {
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    const list = Array.from(panelRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []);
    const i = list.indexOf(document.activeElement as HTMLElement);
    const step = e.key === 'ArrowDown' ? 1 : -1;
    e.preventDefault();
    list[(i + step + list.length) % list.length]?.focus();
  }

  return (
    <div
      ref={panelRef}
      role="menu"
      aria-label={`Azioni per ${title}`}
      onKeyDown={onKeyDown}
      // Il clic destro sul pannello non deve aprire il menu del browser sopra il nostro.
      onContextMenu={(e) => e.preventDefault()}
      style={pos}
      className="surface-glass fixed z-50 w-56 animate-pop-in rounded-lg border p-1 text-sm text-popover-foreground shadow-dialog"
    >
      <div className="truncate px-2 pb-1 pt-1.5 text-2xs text-muted-foreground">{title}</div>
      {items.map((item) => (
        <button
          key={item.id}
          type="button"
          role="menuitem"
          onClick={() => {
            onClose();
            item.onSelect();
          }}
          className={cn(
            'flex h-8 w-full select-none items-center gap-2 rounded-md px-2 text-left text-sm outline-none transition-colors coarse:h-11',
            'text-foreground hover:bg-accent focus-visible:bg-accent',
          )}
        >
          {item.icon ? (
            <span className="flex shrink-0 items-center text-muted-foreground [&_svg]:size-4">{item.icon}</span>
          ) : null}
          <span className="flex-1 truncate">{item.label}</span>
        </button>
      ))}
    </div>
  );
}
