/*
 * Albero dei mazzi con i conteggi: lo usano la schermata dei mazzi e il telecomando
 * (che apre il mazzo sul computer invece che qui).
 */
import { useState } from 'react';
import { ChevronRight } from 'lucide-react';
import { cn } from '@anki-studio/ui-kit';
import type { DeckNode } from '../api/types';
import { QueueCounts } from './QueueCounts';

/*
 * Mazzi chiusi, per dispositivo. Il campo `collapsed` del backend non si usa:
 * è lo stato di Anki desktop e qui l'albero si apre e chiude con il dito
 * senza toccare la collezione (e senza generare modifiche da sincronizzare).
 */
const COLLAPSED_KEY = 'anki-studio.collapsed-decks';

function readCollapsed(): Set<number> {
  try {
    const raw = JSON.parse(localStorage.getItem(COLLAPSED_KEY) ?? '[]') as unknown;
    return new Set(Array.isArray(raw) ? raw.filter((x): x is number => typeof x === 'number') : []);
  } catch {
    return new Set();
  }
}

function visible(nodes: DeckNode[], collapsed: Set<number>): DeckNode[] {
  return nodes.flatMap((n) => [n, ...(collapsed.has(n.id) ? [] : visible(n.children, collapsed))]);
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
  const [collapsed, setCollapsed] = useState(readCollapsed);

  function toggle(id: number) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      try {
        localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...next]));
      } catch {
        // storage non disponibile: vale per questa sessione
      }
      return next;
    });
  }

  return (
    <ul className="divide-y overflow-hidden rounded-lg border bg-card">
      {visible(decks, collapsed).map((deck) => (
        <DeckRow
          key={deck.id}
          deck={deck}
          collapsed={collapsed.has(deck.id)}
          disabled={disabled}
          onToggle={() => toggle(deck.id)}
          onOpen={() => onOpen(deck)}
        />
      ))}
    </ul>
  );
}

function DeckRow({
  deck,
  collapsed,
  disabled,
  onToggle,
  onOpen,
}: {
  deck: DeckNode;
  collapsed: boolean;
  disabled: boolean;
  onToggle: () => void;
  onOpen: () => void;
}) {
  const hasChildren = deck.children.length > 0;
  const indent = (deck.level - 1) * 1.25;
  return (
    <li className="flex items-stretch">
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
        onClick={onOpen}
        disabled={disabled}
        className="flex h-14 min-w-0 flex-1 items-center gap-3 pr-4 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:opacity-disabled"
      >
        <span className={cn('flex-1 truncate text-sm', deck.level === 1 ? 'font-medium' : 'text-foreground')}>{deck.name}</span>
        <QueueCounts counts={deck.counts} cellClassName="w-8" />
        <ChevronRight className="size-4 shrink-0 text-muted-foreground/60" />
      </button>
    </li>
  );
}
