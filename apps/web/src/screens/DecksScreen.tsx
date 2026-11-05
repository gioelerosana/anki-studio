import { useCallback, useEffect, useState } from 'react';
import { ChevronRight, Cloud, CloudAlert, CloudOff, Layers, Plus, Settings } from 'lucide-react';
import { Banner, EmptyHint, HeaderBar, IconButton, Spinner, cn } from '@anki-studio/ui-kit';
import { api, ApiError } from '../api/client';
import type { DeckNode, TodayStats } from '../api/types';
import { formatDuration, plural } from '../app/format';
import { navigate } from '../app/route';
import { QueueCounts } from '../components/QueueCounts';
import { primeAudio } from '../study/audio';
import { useSync } from '../sync/SyncProvider';

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

export function DecksScreen() {
  const { status, running, runSync, openPanel, dataVersion } = useSync();
  const [decks, setDecks] = useState<DeckNode[] | null>(null);
  const [today, setToday] = useState<TodayStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(readCollapsed);

  const load = useCallback(async () => {
    try {
      const [d, t] = await Promise.all([api.decks(), api.todayStats().catch(() => null)]);
      setDecks(d);
      setToday(t);
      setError(null);
    } catch (err) {
      // 401: ci pensa app/auth.tsx, che rifà il login
      if (!(err instanceof ApiError && err.status === 401)) {
        setError(err instanceof Error ? err.message : 'Server non raggiungibile');
      }
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, dataVersion]);

  // I conteggi cambiano col giorno e con lo studio da altri dispositivi: si aggiornano al ritorno sull'app.
  useEffect(() => {
    const onVisible = () => !document.hidden && void load();
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [load]);

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

  const syncError = status?.last_result?.outcome === 'error' || !!status?.media.error || !!status?.full_sync_required;
  const SyncIcon = status && !status.logged_in ? CloudOff : syncError ? CloudAlert : Cloud;
  const syncLabel = status && !status.logged_in ? 'AnkiWeb non collegato' : 'Sincronizza';

  return (
    <div className="flex h-full flex-col">
      <HeaderBar
        title="Mazzi"
        leftContent={
          <IconButton label="Impostazioni" onClick={() => navigate({ name: 'settings' })}>
            <Settings />
          </IconButton>
        }
        rightContent={
          <>
            <IconButton label="Aggiungi carta" onClick={() => navigate({ name: 'add', deckId: null })}>
              <Plus />
            </IconButton>
            <IconButton
              label={syncLabel}
              // Con un problema da risolvere (conflitto, errore) il tap apre il pannello che lo spiega.
              onClick={() => (status?.logged_in && !syncError ? void runSync() : openPanel())}
              onContextMenu={(e) => {
                e.preventDefault();
                openPanel();
              }}
              disabled={running}
            >
              {running ? <Spinner /> : <SyncIcon className={cn(syncError && 'text-warning-foreground')} />}
            </IconButton>
          </>
        }
      />
      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-2xl p-4 pb-[max(1rem,env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))]">
          {error ? (
            <Banner variant="error" className="mb-4">
              {error}
            </Banner>
          ) : null}
          {decks === null ? (
            error ? null : (
              <div className="flex justify-center p-8 text-muted-foreground">
                <Spinner />
              </div>
            )
          ) : decks.length === 0 ? (
            <EmptyHint
              icon={<Layers />}
              title="Nessun mazzo"
              description="Collega AnkiWeb e sincronizza per scaricare la collezione."
            />
          ) : (
            <>
              <div className="mb-2 flex items-center justify-between px-1 text-2xs text-muted-foreground">
                <span>{today && today.reviews > 0 ? `Oggi ${plural(today.reviews, 'carta', 'carte')} in ${formatDuration(today.seconds)}` : 'Oggi nessuna carta studiata'}</span>
                <span className="flex gap-3 max-sm:hidden" aria-hidden>
                  <span className="w-8 text-right">Nuove</span>
                  <span className="w-8 text-right">Appr.</span>
                  <span className="w-8 text-right">Ripasso</span>
                  <span className="w-7" />
                </span>
              </div>
              <ul className="divide-y overflow-hidden rounded-lg border bg-card">
                {visible(decks, collapsed).map((deck) => (
                  <DeckRow key={deck.id} deck={deck} collapsed={collapsed.has(deck.id)} onToggle={() => toggle(deck.id)} />
                ))}
              </ul>
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function visible(nodes: DeckNode[], collapsed: Set<number>): DeckNode[] {
  return nodes.flatMap((n) => [n, ...(collapsed.has(n.id) ? [] : visible(n.children, collapsed))]);
}

function DeckRow({ deck, collapsed, onToggle }: { deck: DeckNode; collapsed: boolean; onToggle: () => void }) {
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
        onClick={() => {
          // Il tap sul mazzo è il gesto che sblocca l'audio automatico della prima carta (iPadOS).
          primeAudio();
          navigate({ name: 'study', deckId: deck.id });
        }}
        className="flex h-14 min-w-0 flex-1 items-center gap-3 pr-4 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
      >
        <span className={cn('flex-1 truncate text-sm', deck.level === 1 ? 'font-medium' : 'text-foreground')}>{deck.name}</span>
        <QueueCounts counts={deck.counts} cellClassName="w-8" />
        <ChevronRight className="size-4 shrink-0 text-muted-foreground/60" />
      </button>
    </li>
  );
}
