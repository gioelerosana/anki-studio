/*
 * Albero dei mazzi con i conteggi: lo usano la schermata dei mazzi e il telecomando
 * (che apre il mazzo sul computer invece che qui).
 */
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { ChevronRight, Eye, EyeOff } from 'lucide-react';
import { cn } from '@anki-studio/ui-kit';
import type { DeckNode } from '../api/types';
import { DeckContextMenu } from './DeckContextMenu';
import { QueueCounts } from './QueueCounts';

/*
 * Mazzi chiusi, per dispositivo. Il campo `collapsed` del backend non si usa:
 * è lo stato di Anki desktop e qui l'albero si apre e chiude con il dito
 * senza toccare la collezione (e senza generare modifiche da sincronizzare).
 */
const COLLAPSED_KEY = 'anki-studio.collapsed-decks';
/*
 * Mazzi nascosti dall'elenco (clic destro o tocco lungo), per dispositivo. Nascondere non
 * tocca la collezione: il mazzo, le sue carte e la sync restano com'erano, e si può
 * rimostrare. Un mazzo nascosto porta con sé i sottomazzi.
 */
const HIDDEN_KEY = 'anki-studio.hidden-decks';
const LONG_PRESS_MS = 500;
// Oltre questa distanza il dito sta scorrendo la lista, non premendo sul mazzo.
const LONG_PRESS_SLOP_PX = 8;

function readIds(key: string): Set<number> {
  try {
    const raw = JSON.parse(localStorage.getItem(key) ?? '[]') as unknown;
    return new Set(Array.isArray(raw) ? raw.filter((x): x is number => typeof x === 'number') : []);
  } catch {
    return new Set();
  }
}

function saveIds(key: string, ids: Set<number>) {
  try {
    localStorage.setItem(key, JSON.stringify([...ids]));
  } catch {
    // storage non disponibile: vale per questa sessione
  }
}

/** Righe da mostrare. Con `showHidden` i nascosti restano, attenuati; senza, spariscono con i loro figli. */
function visible(nodes: DeckNode[], collapsed: Set<number>, hidden: Set<number>, showHidden: boolean): DeckNode[] {
  return nodes.flatMap((n) =>
    hidden.has(n.id) && !showHidden
      ? []
      : [n, ...(collapsed.has(n.id) ? [] : visible(n.children, collapsed, hidden, showHidden))],
  );
}

/** Quanti mazzi nascosti ci sono ancora nella collezione (gli id di mazzi spariti non contano). */
function countHidden(nodes: DeckNode[], hidden: Set<number>): number {
  return nodes.reduce((n, d) => n + (hidden.has(d.id) ? 1 : 0) + countHidden(d.children, hidden), 0);
}

/** Il mazzo è nascosto lui stesso o lo è un antenato (mostrato solo in modalità «mostra nascosti»). */
function isHiddenBranch(nodes: DeckNode[], hidden: Set<number>, inherited = false): Map<number, boolean> {
  const out = new Map<number, boolean>();
  for (const n of nodes) {
    const h = inherited || hidden.has(n.id);
    out.set(n.id, h);
    for (const [id, v] of isHiddenBranch(n.children, hidden, h)) out.set(id, v);
  }
  return out;
}

export function DeckList({
  decks,
  onOpen,
  disabled = false,
}: {
  decks: DeckNode[];
  onOpen: (deck: DeckNode) => void;
  disabled?: boolean;
}) {
  const [collapsed, setCollapsed] = useState(() => readIds(COLLAPSED_KEY));
  const [hidden, setHidden] = useState(() => readIds(HIDDEN_KEY));
  const [showHidden, setShowHidden] = useState(false);
  const [menu, setMenu] = useState<{ deck: DeckNode; x: number; y: number } | null>(null);

  function toggle(id: number) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      saveIds(COLLAPSED_KEY, next);
      return next;
    });
  }

  function setDeckHidden(id: number, value: boolean) {
    setHidden((prev) => {
      const next = new Set(prev);
      if (value) next.add(id);
      else next.delete(id);
      saveIds(HIDDEN_KEY, next);
      return next;
    });
  }

  const hiddenCount = countHidden(decks, hidden);
  const branch = isHiddenBranch(decks, hidden);
  // Senza più nulla di nascosto la modalità «mostra» non ha senso: si torna all'elenco normale,
  // altrimenti resterebbe accesa e il prossimo mazzo nascosto resterebbe in vista.
  useEffect(() => {
    if (hiddenCount === 0) setShowHidden(false);
  }, [hiddenCount]);
  const reveal = showHidden && hiddenCount > 0;

  return (
    <>
      <ul className="divide-y overflow-hidden rounded-lg border bg-card">
        {visible(decks, collapsed, hidden, reveal).map((deck) => (
          <DeckRow
            key={deck.id}
            deck={deck}
            collapsed={collapsed.has(deck.id)}
            dimmed={branch.get(deck.id) === true}
            disabled={disabled}
            onToggle={() => toggle(deck.id)}
            onOpen={() => onOpen(deck)}
            onMenu={(x, y) => setMenu({ deck, x, y })}
          />
        ))}
      </ul>
      {hiddenCount > 0 ? (
        <button
          type="button"
          onClick={() => setShowHidden((v) => !v)}
          className="mt-3 flex h-10 w-full items-center justify-center gap-2 rounded-control text-xs text-muted-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring coarse:h-12"
        >
          {reveal ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          {reveal
            ? 'Nascondi di nuovo i mazzi nascosti'
            : hiddenCount === 1
              ? 'Mostra 1 mazzo nascosto'
              : `Mostra ${hiddenCount} mazzi nascosti`}
        </button>
      ) : null}
      {menu ? (
        <DeckContextMenu
          x={menu.x}
          y={menu.y}
          title={menu.deck.full_name}
          onClose={() => setMenu(null)}
          items={
            hidden.has(menu.deck.id)
              ? [{ id: 'show', label: 'Mostra mazzo', icon: <Eye />, onSelect: () => setDeckHidden(menu.deck.id, false) }]
              : [{ id: 'hide', label: 'Nascondi mazzo', icon: <EyeOff />, onSelect: () => setDeckHidden(menu.deck.id, true) }]
          }
        />
      ) : null}
    </>
  );
}

function DeckRow({
  deck,
  collapsed,
  dimmed,
  disabled,
  onToggle,
  onOpen,
  onMenu,
}: {
  deck: DeckNode;
  collapsed: boolean;
  dimmed: boolean;
  disabled: boolean;
  onToggle: () => void;
  onOpen: () => void;
  onMenu: (x: number, y: number) => void;
}) {
  const hasChildren = deck.children.length > 0;
  const indent = (deck.level - 1) * 1.25;

  /*
   * Su iPad il tocco lungo non genera `contextmenu` (lo fa solo il clic destro del
   * trackpad o del mouse): lo si ricostruisce. Dopo uno scatto lungo il `click` che
   * segue il rilascio va ignorato, altrimenti aprirebbe il mazzo.
   */
  const press = useRef<{ timer: number; x: number; y: number } | null>(null);
  const longPressed = useRef(false);

  function cancelPress() {
    if (press.current) window.clearTimeout(press.current.timer);
    press.current = null;
  }

  function onPointerDown(e: ReactPointerEvent) {
    if (e.pointerType === 'mouse') return; // il mouse ha il clic destro
    longPressed.current = false;
    const { clientX: x, clientY: y } = e;
    press.current = {
      x,
      y,
      timer: window.setTimeout(() => {
        longPressed.current = true;
        press.current = null;
        onMenu(x, y);
      }, LONG_PRESS_MS),
    };
  }

  function onPointerMove(e: ReactPointerEvent) {
    const p = press.current;
    if (p && Math.hypot(e.clientX - p.x, e.clientY - p.y) > LONG_PRESS_SLOP_PX) cancelPress();
  }

  return (
    <li className={cn('flex items-stretch', dimmed && 'opacity-50')}>
      <span className="flex shrink-0 items-center" style={{ paddingLeft: `${0.25 + indent}rem` }}>
        {hasChildren ? (
          <button
            type="button"
            onClick={onToggle}
            aria-label={collapsed ? `Apri ${deck.name}` : `Chiudi ${deck.name}`}
            aria-expanded={!collapsed}
            className="flex size-10 items-center justify-center rounded-control text-muted-foreground hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
          >
            <ChevronRight className={cn('size-4 transition-transform duration-150', !collapsed && 'rotate-90')} />
          </button>
        ) : (
          <span className="w-10" />
        )}
      </span>
      <button
        type="button"
        onClick={() => {
          if (longPressed.current) {
            longPressed.current = false;
            return;
          }
          onOpen();
        }}
        onContextMenu={(e) => {
          e.preventDefault();
          cancelPress();
          onMenu(e.clientX, e.clientY);
        }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={cancelPress}
        onPointerCancel={cancelPress}
        onPointerLeave={cancelPress}
        disabled={disabled}
        // select-none e touch-callout: il tocco lungo non deve selezionare il testo né aprire l'anteprima di iOS
        className="flex h-14 min-w-0 flex-1 select-none items-center gap-3 pr-4 text-left [-webkit-touch-callout:none] hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:opacity-disabled"
      >
        <span className={cn('flex-1 truncate text-sm', deck.level === 1 ? 'font-medium' : 'text-foreground')}>{deck.name}</span>
        <QueueCounts counts={deck.counts} cellClassName="w-8" />
        <ChevronRight className="size-4 shrink-0 text-muted-foreground/60" />
      </button>
    </li>
  );
}
