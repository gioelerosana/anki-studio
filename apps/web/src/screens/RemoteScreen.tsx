/*
 * Telecomando: il telefono come tastiera dello studio aperto sul computer.
 *
 * Si guarda la carta sullo schermo grande e si risponde dal telefono in mano, invece di
 * tenere le dita su Spazio e 1–4. Il telefono non mostra la carta e non decide niente:
 * disegna i pulsanti dallo stato che pubblica la schermata di studio e le manda i tasti
 * (backend/app/remote.py). Nessun abbinamento: stesso account Authentik, stessa collezione.
 *
 * Pulsanti grandi e in basso, per il pollice, e schermo sempre acceso (Wake Lock) finché
 * il telecomando è aperto.
 */
import { useCallback, useEffect, useState } from 'react';
import { ChevronLeft, CircleCheck, Monitor, Undo2, Volume2 } from 'lucide-react';
import { Button, EmptyHint, HeaderBar, Spinner, cn } from '@anki-studio/ui-kit';
import type { Rating, RemoteCommand, RemoteScreenState } from '../api/types';
import { navigate } from '../app/route';
import { QueueCounts } from '../components/QueueCounts';
import { useRemoteSocket } from '../remote/useRemoteSocket';

const RATINGS: { rating: Rating; label: string }[] = [
  { rating: 1, label: 'Di nuovo' },
  { rating: 2, label: 'Difficile' },
  { rating: 3, label: 'Bene' },
  { rating: 4, label: 'Facile' },
];

/** Dopo un tasto, i pulsanti restano spenti finché lo schermo non cambia stato (o per questo tempo). */
const PENDING_TIMEOUT_MS = 2500;

const stepKey = (s: RemoteScreenState | null) => (s ? `${s.card_id}:${s.revealed}:${s.done}` : '');

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
  useWakeLock();

  const { status, send } = useRemoteSocket('role=remote', (message) => {
    if (message.type !== 'state') return;
    setScreen(message.screen);
    setReceived(true);
  });

  // lo stato è cambiato (carta girata, carta nuova): il tasto è arrivato
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
  const deckLabel = screen?.deck_name.split('::').pop() ?? '';

  return (
    <div className="flex h-full flex-col">
      <HeaderBar
        title="Telecomando"
        subtitle={screen ? deckLabel : undefined}
        leftContent={
          <Button variant="ghost" size="sm" icon={<ChevronLeft />} onClick={() => navigate({ name: 'decks' })} className="-ml-1.5 pl-1">
            Mazzi
          </Button>
        }
        rightContent={
          screen && !screen.done ? <QueueCounts counts={screen.counts} current={screen.queue ?? undefined} className="mr-1" /> : null
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
            title="Nessuno studio aperto"
            description="Apri un mazzo sul computer o sull’iPad, con lo stesso account: il telefono lo comanda da solo."
            action={!connected ? <span className="flex items-center gap-2 text-xs text-muted-foreground"><Spinner /> Riconnessione…</span> : null}
          />
        </main>
      ) : (
        <main className="flex min-h-0 flex-1 flex-col gap-3 p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pl-[max(0.75rem,env(safe-area-inset-left))] pr-[max(0.75rem,env(safe-area-inset-right))]">
          {!connected ? (
            <p className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
              <Spinner /> Riconnessione…
            </p>
          ) : null}

          {screen.done || screen.card_id === null ? (
            <div className="flex flex-1 animate-fade-in flex-col items-center justify-center gap-3 text-center">
              <CircleCheck className="size-10 text-muted-foreground" strokeWidth={1.5} />
              <p className="text-base font-semibold">Per oggi hai finito{deckLabel ? ` con ${deckLabel}` : ''}</p>
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
    </div>
  );
}
