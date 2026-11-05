import { useCallback, useEffect, useState } from 'react';
import { ChevronRight, Layers, RefreshCw } from 'lucide-react';
import { Banner, EmptyHint, HeaderBar, IconButton, Spinner, cn } from '@anki-studio/ui-kit';
import { api, ApiError } from '../api/client';
import type { DeckNode } from '../api/types';
import { updateSettings } from '../settings';

export function DecksScreen() {
  const [decks, setDecks] = useState<DeckNode[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const load = useCallback(async () => {
    try {
      setDecks(await api.decks());
      setError(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) updateSettings({ apiToken: '' });
      else setError(err instanceof Error ? err.message : 'Errore');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function sync() {
    setSyncing(true);
    try {
      await api.sync();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sync fallita');
    } finally {
      setSyncing(false);
    }
  }

  return (
    <>
      <HeaderBar
        title="Mazzi"
        rightContent={
          <IconButton label="Sincronizza" onClick={sync} disabled={syncing}>
            <RefreshCw className={cn('size-4', syncing && 'animate-spin')} />
          </IconButton>
        }
      />
      <main className="mx-auto w-full max-w-2xl flex-1 p-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
        {error ? <Banner variant="error" className="mb-4">{error}</Banner> : null}
        {decks === null ? (
          <div className="flex justify-center p-8 text-muted-foreground">
            <Spinner />
          </div>
        ) : decks.length === 0 ? (
          <EmptyHint icon={<Layers />} title="Nessun mazzo" description="Sincronizza con AnkiWeb per scaricare la collezione." />
        ) : (
          <ul className="divide-y overflow-hidden rounded-lg border bg-card">
            {flatten(decks).map((deck) => (
              <DeckRow key={deck.id} deck={deck} />
            ))}
          </ul>
        )}
      </main>
    </>
  );
}

function flatten(nodes: DeckNode[]): DeckNode[] {
  return nodes.flatMap((n) => [n, ...(n.collapsed ? [] : flatten(n.children))]);
}

function DeckRow({ deck }: { deck: DeckNode }) {
  const { new: n, learning, review } = deck.counts;
  return (
    <li>
      <button
        type="button"
        className="flex h-14 w-full items-center gap-3 px-4 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        style={{ paddingLeft: `${1 + (deck.level - 1) * 1.25}rem` }}
      >
        <span className="flex-1 truncate text-sm font-medium">{deck.name}</span>
        <span className="flex gap-3 font-mono text-xs tabular-nums">
          <Count value={n} className="text-info-foreground" label="Nuove" />
          <Count value={learning} className="text-error-foreground" label="In apprendimento" />
          <Count value={review} className="text-success-foreground" label="Da ripassare" />
        </span>
        <ChevronRight className="size-4 text-muted-foreground" />
      </button>
    </li>
  );
}

function Count({ value, className, label }: { value: number; className: string; label: string }) {
  return (
    <span title={label} className={cn('w-8 text-right', value === 0 ? 'text-muted-foreground/50' : className)}>
      {value}
    </span>
  );
}
