/*
 * Telecomando: il telefono come tastiera dello studio aperto sul computer.
 *
 * Si guarda la carta sullo schermo grande e si risponde dal telefono in mano, invece di
 * tenere le dita su Spazio e 1–4. Il telefono non mostra la carta e non decide niente:
 * disegna i pulsanti dallo stato che pubblica la schermata di studio e le manda i tasti
 * (backend/app/remote.py). Nessun abbinamento: stesso account Authentik, stessa collezione.
 *
 * Pulsanti grandi e in basso, per il pollice, e schermo sempre acceso (Wake Lock) finché
 * il telecomando è aperto. Seppellisci, sospendi e flag stanno nel menu in alto: lontani
 * dal pollice, così non si sospende una carta per sbaglio (e c'è comunque «Annulla»).
 *
 * Se sul computer c'è l'elenco dei mazzi, il telefono lo mostra e ne apre uno lì; durante
 * lo studio «Cambia mazzo» (menu, o a fine mazzo) riporta il computer all'elenco.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { ChevronLeft, CircleCheck, EyeOff, Flag, Layers, Monitor, MoreHorizontal, Pause, Undo2, Volume2, VolumeOff } from 'lucide-react';
import { Banner, Button, EmptyHint, HeaderBar, IconButton, Menu, Spinner, cn, type MenuItem } from '@anki-studio/ui-kit';
import { api } from '../api/client';
import type { DeckNode, Rating, RemoteCommand, RemoteScreenState } from '../api/types';
import { navigate } from '../app/route';
import { useToast } from '../app/toasts';
import { DeckList } from '../components/DeckList';
import { QueueCounts } from '../components/QueueCounts';
import { useRemoteSocket } from '../remote/useRemoteSocket';
import { FlagModal } from '../study/FlagModal';
import { flagColor, flagLabel } from '../study/flags';

const RATINGS: { rating: Rating; label: string }[] = [
  { rating: 1, label: 'Di nuovo' },
  { rating: 2, label: 'Difficile' },
  { rating: 3, label: 'Bene' },
  { rating: 4, label: 'Facile' },
];

/** Dopo un tasto, i pulsanti restano spenti finché lo schermo non cambia stato (o per questo tempo). */
const PENDING_TIMEOUT_MS = 2500;

const stepKey = (s: RemoteScreenState | null) => (s ? `${s.view}:${s.deck_id}:${s.card_id}:${s.revealed}:${s.done}` : '');

/** Schermo acceso finché il telecomando è aperto: iOS lo rilascia quando la PWA va in background. */
function useWakeLock() {
  useEffect(() => {
    if (!('wakeLock' in navigator)) return;
    let lock: WakeLockSentinel | null = null;
    let disposed = false;
    const acquire = async () => {
      if (document.hidden || disposed || (lock && !lock.released)) return;
      try {
        const next = await navigator.wakeLock.request('screen');
        if (disposed) void next.release();
        else lock = next;
      } catch {
        // batteria scarsa o permesso negato: lo schermo si spegnerà come sempre
      }
    };
    void acquire();
    document.addEventListener('visibilitychange', acquire);
    return () => {
      disposed = true;
      document.removeEventListener('visibilitychange', acquire);
      void lock?.release();
    };
  }, []);
}

export function RemoteScreen() {
  const [screen, setScreen] = useState<RemoteScreenState | null>(null);
  const [received, setReceived] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [flagging, setFlagging] = useState(false);
  const toast = useToast();
  useWakeLock();

  const { status, send } = useRemoteSocket('role=remote', (message) => {
    if (message.type !== 'state') return;
    setScreen(message.screen);
    setReceived(true);
  });

  // lo stato è cambiato (carta girata, carta nuova, mazzo aperto): il tasto è arrivato
  useEffect(() => setPending(null), [screen]);
  useEffect(() => {
    if (pending === null) return;
    const timer = window.setTimeout(() => setPending(null), PENDING_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [pending]);

  const press = useCallback(
    (command: RemoteCommand, waitForChange = true) => {
      if (!send({ type: 'command', command })) return;
      if (waitForChange) setPending(stepKey(screen));
    },
    [screen, send],
  );

  const connected = status === 'open';
  const locked = !connected || !screen || screen.busy || (pending !== null && pending === stepKey(screen));
  const study = screen?.view === 'study' ? screen : null;
  const card = study && !study.done && study.card_id !== null ? study : null;
  const deckLabel = study?.deck_name.split('::').pop() ?? '';

  const cardAction = (action: 'bury' | 'suspend') => {
    if (!card) return;
    press({ action, card_id: card.card_id });
    toast('success', action === 'bury' ? 'Carta seppellita fino a domani' : 'Carta sospesa: «Annulla» la riporta');
  };
  const changeDeck = () => press({ action: 'close' });
  const menuItems: MenuItem[] = [
    ...(card
      ? [
          { id: 'flag', label: 'Flag…', icon: <Flag />, onSelect: () => setFlagging(true) },
          { id: 'bury', label: 'Seppellisci', icon: <EyeOff />, separatorBefore: true, onSelect: () => cardAction('bury') },
          { id: 'suspend', label: 'Sospendi', icon: <Pause />, onSelect: () => cardAction('suspend') },
        ]
      : []),
    { id: 'decks', label: 'Cambia mazzo', icon: <Layers />, separatorBefore: !!card, onSelect: changeDeck },
  ];

  const reconnecting = !connected ? (
    <p className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
      <Spinner /> Riconnessione…
    </p>
  ) : null;

  return (
    <div className="flex h-full flex-col">
      <HeaderBar
        title="Telecomando"
        subtitle={study ? deckLabel : screen?.view === 'decks' ? 'Scegli il mazzo' : undefined}
        leftContent={
          <Button variant="ghost" size="sm" icon={<ChevronLeft />} onClick={() => navigate({ name: 'decks' })} className="-ml-1.5 pl-1">
            Esci
          </Button>
        }
        rightContent={
          study ? (
            <>
              {card?.counts ? <QueueCounts counts={card.counts} current={card.queue ?? undefined} className="mr-1" /> : null}
              {card && card.flag > 0 ? (
                <span
                  role="img"
                  aria-label={`Flag ${flagLabel(card.flag).toLowerCase()}`}
                  className="mx-1 size-2.5 rounded-full"
                  style={{ backgroundColor: flagColor(card.flag) }}
                />
              ) : null}
              <Menu
                items={menuItems}
                trigger={
                  <IconButton label="Azioni" disabled={locked}>
                    <MoreHorizontal />
                  </IconButton>
                }
              />
            </>
          ) : null
        }
      />

      {!received ? (
        <main className="flex flex-1 flex-col items-center justify-center gap-3 text-sm text-muted-foreground">
          <Spinner />
          Collegamento…
        </main>
      ) : !screen ? (
        <main className="flex flex-1 items-center justify-center p-6">
          <EmptyHint
            icon={<Monitor />}
            title="Nessuno schermo collegato"
            description="Apri Anki Studio sul computer o sull’iPad, con lo stesso account: il telefono lo trova da solo."
            action={reconnecting}
          />
        </main>
      ) : screen.view === 'decks' ? (
        <RemoteDeckPicker locked={locked} reconnecting={reconnecting} onOpen={(deck) => press({ action: 'open_deck', deck_id: deck.id })} />
      ) : screen.view === 'other' ? (
        <main className="flex flex-1 items-center justify-center p-6">
          <EmptyHint
            icon={<Monitor />}
            title="Sul computer è aperta un’altra schermata"
            description="Torna all’elenco dei mazzi sul computer per sceglierne uno da qui."
            action={reconnecting}
          />
        </main>
      ) : (
        <main className="flex min-h-0 flex-1 flex-col gap-3 p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pl-[max(0.75rem,env(safe-area-inset-left))] pr-[max(0.75rem,env(safe-area-inset-right))]">
          {reconnecting}
          {screen.audio_blocked ? (
            <Banner variant="warning" icon={<VolumeOff />}>
              Il browser del computer tiene l’audio spento finché non fai un clic sulla sua pagina: basta una volta.
            </Banner>
          ) : null}

          {screen.done ? (
            <div className="flex flex-1 animate-fade-in flex-col items-center justify-center gap-4 text-center">
              <CircleCheck className="size-10 text-muted-foreground" strokeWidth={1.5} />
              <p className="text-base font-semibold">Per oggi hai finito{deckLabel ? ` con ${deckLabel}` : ''}</p>
              <Button size="lg" icon={<Layers />} disabled={locked} onClick={changeDeck} className="h-12 px-5 text-base">
                Cambia mazzo
              </Button>
            </div>
          ) : screen.card_id === null ? (
            <div className="flex flex-1 items-center justify-center text-muted-foreground">
              <Spinner />
            </div>
          ) : !screen.revealed ? (
            <button
              type="button"
              disabled={locked}
              onClick={() => press({ action: 'reveal', card_id: screen.card_id })}
              className={cn(
                'flex flex-1 select-none items-center justify-center rounded-xl bg-primary text-lg font-medium text-primary-foreground transition-[background-color,transform] duration-150 active:scale-[0.98]',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:opacity-disabled',
              )}
            >
              Mostra risposta
            </button>
          ) : (
            <div className="grid flex-1 grid-cols-2 grid-rows-2 gap-3">
              {RATINGS.map(({ rating, label }) => (
                <button
                  key={rating}
                  type="button"
                  disabled={locked}
                  onClick={() => press({ action: 'answer', rating, card_id: screen.card_id })}
                  className={cn(
                    'flex select-none flex-col items-center justify-center gap-1 rounded-xl border text-lg font-medium transition-[background-color,transform] duration-150 active:scale-[0.97]',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:opacity-disabled',
                    rating === 1 && 'border-transparent bg-error/8 text-error-foreground active:bg-error/16 dark:bg-error/16',
                    (rating === 2 || rating === 4) && 'border-input bg-popover text-foreground shadow-control active:bg-accent/50 dark:bg-input/32',
                    rating === 3 && 'border-primary bg-primary text-primary-foreground active:bg-primary/90',
                  )}
                >
                  <span>{label}</span>
                  <span className={cn('font-mono text-sm tabular-nums', rating === 3 ? 'text-primary-foreground/80' : 'text-muted-foreground')}>
                    {screen.button_labels[rating - 1] ?? ''}
                  </span>
                </button>
              ))}
            </div>
          )}

          <div className="flex shrink-0 gap-3">
            <Button
              variant="outline"
              size="lg"
              icon={<Undo2 />}
              disabled={!connected || !screen.can_undo || screen.busy}
              onClick={() => press({ action: 'undo' })}
              className="h-14 flex-1 text-base"
            >
              Annulla
            </Button>
            {screen.has_audio && !screen.done ? (
              <Button
                variant="outline"
                size="lg"
                icon={<Volume2 />}
                disabled={!connected}
                onClick={() => press({ action: 'replay' }, false)}
                className="h-14 flex-1 text-base"
              >
                Audio
              </Button>
            ) : null}
          </div>
        </main>
      )}

      <FlagModal
        isOpen={flagging && !!card}
        current={card?.flag ?? 0}
        onClose={() => setFlagging(false)}
        onSelect={(flag) => {
          setFlagging(false);
          if (card) press({ action: 'flag', flag, card_id: card.card_id });
        }}
      />
    </div>
  );
}


/**
 * L'elenco dei mazzi quando sul computer c'è la schermata dei mazzi: il telefono lo legge
 * dall'API (la collezione è la stessa) e il tocco apre il mazzo sul computer.
 */
function RemoteDeckPicker({
  locked,
  reconnecting,
  onOpen,
}: {
  locked: boolean;
  reconnecting: ReactNode;
  onOpen: (deck: DeckNode) => void;
}) {
  const [decks, setDecks] = useState<DeckNode[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .decks()
      .then((d) => {
        if (!cancelled) setDecks(d);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Mazzi non disponibili');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-3 p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pl-[max(0.75rem,env(safe-area-inset-left))] pr-[max(0.75rem,env(safe-area-inset-right))]">
        {reconnecting}
        <p className="px-1 text-xs text-muted-foreground">Tocca un mazzo per studiarlo sul computer.</p>
        {error ? <Banner variant="error">{error}</Banner> : null}
        {decks === null ? (
          error ? null : (
            <div className="flex justify-center p-8 text-muted-foreground">
              <Spinner />
            </div>
          )
        ) : decks.length === 0 ? (
          <EmptyHint icon={<Layers />} title="Nessun mazzo" />
        ) : (
          <DeckList decks={decks} disabled={locked} onOpen={onOpen} />
        )}
      </div>
    </main>
  );
}
