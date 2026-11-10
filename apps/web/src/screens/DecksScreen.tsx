import { useCallback, useEffect, useState } from 'react';
import { ChevronRight, Cloud, CloudAlert, CloudOff, Gamepad2, Inbox, Layers, Library, Plus, Settings } from 'lucide-react';
import { Badge, Banner, EmptyHint, HeaderBar, IconButton, Spinner, cn } from '@anki-studio/ui-kit';
import { api, ApiError } from '../api/client';
import type { DeckNode, TodayStats } from '../api/types';
import { formatDuration, plural } from '../app/format';
import { navigate } from '../app/route';
import { DeckList } from '../components/DeckList';
import { useHubSummary } from '../hub/useHubSummary';
import { primeAudio } from '../study/audio';
import { useSync } from '../sync/SyncProvider';

export function DecksScreen() {
  const { status, running, runSync, openPanel, dataVersion } = useSync();
  const [decks, setDecks] = useState<DeckNode[] | null>(null);
  const [today, setToday] = useState<TodayStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Bozze da approvare: se la rotta non risponde il numero sparisce in silenzio.
  const { drafts } = useHubSummary();

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
            {/* Il telefono come telecomando dello studio aperto sul computer (RemoteScreen). */}
            <IconButton label="Telecomando" onClick={() => navigate({ name: 'remote' })}>
              <Gamepad2 />
            </IconButton>
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
          {/* Libreria e Inbox (docs/PIANO-HUB.md): le carte create dagli agenti arrivano come bozze. */}
          <nav aria-label="Libreria e inbox" className="mb-4 grid grid-cols-2 gap-2 max-[380px]:grid-cols-1">
            <HubLink icon={<Library />} title="Libreria" hint="Cerca e sistema le note" onClick={() => navigate({ name: 'library' })} />
            <HubLink
              icon={<Inbox />}
              title="Inbox"
              hint={drafts ? 'Bozze da approvare' : 'Carte degli agenti'}
              badge={drafts ? drafts : undefined}
              onClick={() => navigate({ name: 'inbox' })}
            />
          </nav>
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
              <DeckList
                decks={decks}
                onOpen={(deck) => {
                  // Il tap sul mazzo è il gesto che sblocca l'audio automatico della prima carta (iPadOS).
                  primeAudio();
                  navigate({ name: 'study', deckId: deck.id });
                }}
              />
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function HubLink({
  icon,
  title,
  hint,
  badge,
  onClick,
}: {
  icon: React.ReactNode;
  title: string;
  hint: string;
  badge?: number;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={badge ? `${title}, ${badge} ${badge === 1 ? 'bozza' : 'bozze'} da approvare` : title}
      className="flex min-h-14 items-center gap-3 rounded-lg border bg-card p-3 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
    >
      <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-muted text-muted-foreground [&_svg]:size-4">{icon}</span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="text-sm font-medium">{title}</span>
        <span className="truncate text-2xs text-muted-foreground">{hint}</span>
      </span>
      {badge ? (
        <Badge variant="info" size="lg" className="font-mono tabular-nums" aria-hidden>
          {badge > 99 ? '99+' : badge}
        </Badge>
      ) : (
        <ChevronRight className="size-4 shrink-0 text-muted-foreground/60" />
      )}
    </button>
  );
}
