/*
 * Studio a tutto schermo.
 *
 * La PWA non decide niente: mostra la carta che il backend mette in cima alla
 * coda, gira la carta, misura il tempo e manda la valutazione. La risposta
 * contiene già la carta successiva, quindi ogni valutazione è un solo giro.
 *
 * Tocco: tap sulla carta = mostra risposta; quattro pulsanti in basso per i
 * pollici. Tastiera (Magic Keyboard): Spazio/Invio, 1–4, Z annulla, R audio,
 * E modifica, A aggiungi, - seppellisci, @ sospendi, Ctrl+1–7 flag, Esc torna ai mazzi.
 *
 * Telecomando: la stessa sessione si comanda dal telefono (RemoteScreen). I tasti del
 * telefono arrivano qui e passano dalle stesse funzioni della tastiera.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ChevronLeft,
  CircleCheck,
  EyeOff,
  Flag,
  MoreHorizontal,
  Pause,
  Pencil,
  Plus,
  Smartphone,
  Undo2,
  Volume2,
  VolumeOff,
} from 'lucide-react';
import { Banner, Button, HeaderBar, IconButton, Menu, Spinner, cn, type MenuItem } from '@anki-studio/ui-kit';
import { api, ApiError } from '../api/client';
import { findDeck } from '../api/decks';
import type { Rating, RemoteCommand, StudyState, TodayStats } from '../api/types';
import { formatDuration, plural } from '../app/format';
import { navigate } from '../app/route';
import { useToast } from '../app/toasts';
import { QueueCounts } from '../components/QueueCounts';
import { EditNoteModal } from '../notes/EditNoteModal';
import { useRemoteStudy, type RemoteStudyState } from '../remote/RemoteScreenProvider';
import { useSettings } from '../settings';
import { CardView } from '../study/CardView';
import { FlagModal } from '../study/FlagModal';
import { playAv, primeAudio, stopAv, useAudioUnlocked } from '../study/audio';
import { flagColor, flagLabel } from '../study/flags';
import { useCardTimer } from '../study/useCardTimer';
import { useSync } from '../sync/SyncProvider';

const RATINGS: { rating: Rating; label: string }[] = [
  { rating: 1, label: 'Di nuovo' },
  { rating: 2, label: 'Difficile' },
  { rating: 3, label: 'Bene' },
  { rating: 4, label: 'Facile' },
];

/** Anki isola i numeri con U+2068/U+2069 per il testo bidirezionale: in un bottone non servono. */
const cleanLabel = (label: string | undefined) => (label ?? '').replace(/[⁨⁩]/g, '');

export function StudyScreen({ deckId }: { deckId: number }) {
  const toast = useToast();
  const { darkMode } = useSettings();
  const { status: syncStatus, runSync, dataVersion } = useSync();
  const [state, setState] = useState<StudyState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [deckName, setDeckName] = useState('');
  const [revealed, setRevealed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [flagging, setFlagging] = useState(false);
  const [answeredInSession, setAnsweredInSession] = useState(0);
  const card = state?.card ?? null;
  const elapsed = useCardTimer(card?.card_id ?? null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const load = useCallback(
    async ({ keepRevealed = false } = {}) => {
      try {
        const next = await api.study(deckId);
        setState((prev) => {
          if (!keepRevealed || prev?.card?.card_id !== next.card?.card_id) setRevealed(false);
          return next;
        });
        setLoadError(null);
      } catch (err) {
        setLoadError(err instanceof ApiError && err.status === 404 ? 'Mazzo non trovato' : err instanceof Error ? err.message : 'Errore');
      }
    },
    [deckId],
  );

  useEffect(() => {
    void load();
    api
      .decks()
      .then((decks) => setDeckName(findDeck(decks, deckId)?.name ?? ''))
      .catch(() => {});
    return stopAv;
  }, [deckId, load]);

  // Una sync (anche partita da un altro schermo) può aver cambiato la coda.
  const firstVersion = useRef(dataVersion);
  useEffect(() => {
    if (dataVersion !== firstVersion.current) void load({ keepRevealed: true });
  }, [dataVersion, load]);

  // Audio automatico: domanda quando arriva la carta, risposta quando si gira.
  useEffect(() => {
    if (!card) return;
    scrollRef.current?.scrollTo({ top: 0 });
    if (!revealed) {
      if (card.autoplay) playAv(card.question_av);
      else stopAv();
    } else if (card.autoplay) playAv(card.answer_av);
    else stopAv();
  }, [card, revealed]);

  // Fine sessione: sync automatica in silenzio, se AnkiWeb è collegato.
  const done = state?.done ?? false;
  useEffect(() => {
    if (done && answeredInSession > 0 && syncStatus?.logged_in) void runSync({ quiet: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- solo all'arrivo alla fine
  }, [done]);

  const reveal = useCallback(() => {
    primeAudio();
    setRevealed(true);
  }, []);

  const answer = useCallback(
    async (rating: Rating) => {
      if (!card || busy) return;
      primeAudio();
      setBusy(true);
      stopAv();
      try {
        const next = await api.answer(deckId, card.card_id, rating, elapsed());
        setState(next);
        setRevealed(false);
        setAnsweredInSession((n) => n + 1);
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          toast('info', 'La coda è cambiata: carta ricaricata');
          await load();
        } else toast('error', err instanceof Error ? err.message : 'Risposta non registrata');
      } finally {
        setBusy(false);
      }
    },
    [busy, card, deckId, elapsed, load, toast],
  );

  const undo = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    stopAv();
    try {
      setState(await api.undo(deckId));
      setRevealed(false);
      setAnsweredInSession((n) => Math.max(0, n - 1));
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) toast('info', 'Niente da annullare');
      else toast('error', err instanceof Error ? err.message : 'Annullamento non riuscito');
    } finally {
      setBusy(false);
    }
  }, [busy, deckId, toast]);

  const cardAction = useCallback(
    async (kind: 'bury' | 'suspend') => {
      if (!card || busy) return;
      setBusy(true);
      stopAv();
      try {
        await (kind === 'bury' ? api.bury(card.card_id) : api.suspend(card.card_id));
        toast('success', kind === 'bury' ? 'Carta seppellita fino a domani' : 'Carta sospesa');
        await load();
      } catch (err) {
        toast('error', err instanceof Error ? err.message : 'Azione non riuscita');
      } finally {
        setBusy(false);
      }
    },
    [busy, card, load, toast],
  );

  const setFlag = useCallback(
    async (flag: number) => {
      if (!card) return;
      setFlagging(false);
      const value = flag === card.flag ? 0 : flag;
      try {
        await api.flag(card.card_id, value);
        setState((prev) => (prev?.card ? { ...prev, card: { ...prev.card, flag: value } } : prev));
      } catch (err) {
        toast('error', err instanceof Error ? err.message : 'Flag non impostato');
      }
    },
    [card, toast],
  );

  const replay = useCallback(() => {
    if (!card) return;
    primeAudio();
    playAv(revealed ? [...card.question_av, ...card.answer_av] : card.question_av);
  }, [card, revealed]);

  const onPlay = useCallback(
    (side: 'q' | 'a', index: number) => {
      if (!card) return;
      primeAudio();
      const item = (side === 'a' ? card.answer_av : card.question_av)[index];
      if (item) playAv([item]);
    },
    [card],
  );

  // Tastiera: si legge lo stato più recente da una ref, il listener è uno solo.
  const keys = useRef({ revealed, card, done, reveal, answer, undo, replay, cardAction, setFlag });
  keys.current = { revealed, card, done, reveal, answer, undo, replay, cardAction, setFlag };
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const target = e.target;
      if (target instanceof Element && target.closest('input, textarea, select, [contenteditable="true"]')) return;
      if (document.querySelector('[role="dialog"], [role="menu"]')) return;
      const k = keys.current;
      if (e.ctrlKey && !e.metaKey && /^[1-7]$/.test(e.key) && k.card) {
        e.preventDefault();
        void k.setFlag(Number(e.key));
        return;
      }
      if (e.altKey || e.ctrlKey) return;
      if ((e.key === 'z' || e.key === 'Z') && !e.shiftKey) {
        e.preventDefault();
        void k.undo();
        return;
      }
      if (e.metaKey) return;
      if (e.key === 'Escape') return navigate({ name: 'decks' });
      if (!k.card) return;
      if (e.key === ' ' || e.key === 'Enter') {
        e.preventDefault();
        if (e.repeat) return;
        if (!k.revealed) k.reveal();
        else void k.answer(3);
      } else if (k.revealed && /^[1-4]$/.test(e.key)) {
        e.preventDefault();
        void k.answer(Number(e.key) as Rating);
      } else if (e.key === 'r' || e.key === 'R') k.replay();
      else if (e.key === 'e' || e.key === 'E') setEditing(k.card.note_id);
      else if (e.key === 'a' || e.key === 'A') navigate({ name: 'add', deckId });
      else if (e.key === '-') void k.cardAction('bury');
      else if (e.key === '@') void k.cardAction('suspend');
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [deckId]);

  // Telecomando: lo stato che vede il telefono e i suoi tasti, eseguiti come quelli della tastiera.
  const hasAudio = !!card && card.question_av.length + card.answer_av.length > 0;
  const audioUnlocked = useAudioUnlocked();
  // Appena il clic sblocca l'audio, la carta suona come avrebbe fatto all'arrivo.
  useEffect(() => {
    const k = keys.current;
    if (audioUnlocked && k.card?.autoplay) playAv(k.revealed ? k.card.answer_av : k.card.question_av);
  }, [audioUnlocked]);
  const canUndo = !!state?.undo_label || answeredInSession > 0;
  const remoteState = useMemo<RemoteStudyState | null>(
    () =>
      state
        ? {
            deck_id: deckId,
            deck_name: deckName || state.deck_name || '',
            done: state.done || !card,
            card_id: card?.card_id ?? null,
            revealed,
            queue: card?.queue ?? null,
            counts: state.counts,
            button_labels: (card?.button_labels ?? []).map(cleanLabel),
            has_audio: hasAudio,
            audio_blocked: hasAudio && !audioUnlocked,
            flag: card?.flag ?? 0,
            can_undo: canUndo,
            busy,
          }
        : null,
    [audioUnlocked, busy, canUndo, card, deckId, deckName, hasAudio, revealed, state],
  );
  // finestre aperte, "apri mazzo" e "torna ai mazzi" li gestisce RemoteScreenProvider
  const onRemoteCommand = useCallback((command: RemoteCommand) => {
    const k = keys.current;
    const sameCard = !!k.card && command.card_id === k.card.card_id;
    if (command.action === 'reveal' && sameCard && !k.revealed) k.reveal();
    else if (command.action === 'answer' && sameCard && k.revealed && command.rating) void k.answer(command.rating);
    else if (command.action === 'undo') void k.undo();
    else if (command.action === 'replay') k.replay();
    else if ((command.action === 'bury' || command.action === 'suspend') && sameCard) void k.cardAction(command.action);
    else if (command.action === 'flag' && sameCard && command.flag != null) void k.setFlag(command.flag);
  }, []);
  const remotes = useRemoteStudy(remoteState, onRemoteCommand);

  const menuItems: MenuItem[] = card
    ? [
        { id: 'edit', label: 'Modifica nota', icon: <Pencil />, shortcut: 'E', onSelect: () => setEditing(card.note_id) },
        { id: 'add', label: 'Aggiungi carta', icon: <Plus />, shortcut: 'A', onSelect: () => navigate({ name: 'add', deckId }) },
        { id: 'flag', label: 'Flag…', icon: <Flag />, shortcut: 'Ctrl+1', onSelect: () => setFlagging(true) },
        ...(hasAudio ? [{ id: 'replay', label: 'Riproduci audio', icon: <Volume2 />, shortcut: 'R', onSelect: replay }] : []),
        { id: 'bury', label: 'Seppellisci', icon: <EyeOff />, shortcut: '-', separatorBefore: true, onSelect: () => void cardAction('bury') },
        { id: 'suspend', label: 'Sospendi', icon: <Pause />, shortcut: '@', onSelect: () => void cardAction('suspend') },
      ]
    : [];

  return (
    <div className="flex h-full flex-col">
      <HeaderBar
        title={deckName}
        leftContent={
          <Button variant="ghost" size="sm" icon={<ChevronLeft />} onClick={() => navigate({ name: 'decks' })} className="-ml-1.5 pl-1">
            Mazzi
          </Button>
        }
        rightContent={
          <>
            {state && !state.done ? <QueueCounts counts={state.counts} current={card?.queue} className="mr-2 max-sm:hidden" /> : null}
            {remotes > 0 ? (
              <span role="img" aria-label="Telecomando collegato" title="Telecomando collegato" className="mx-1 text-muted-foreground">
                <Smartphone className="size-4" />
              </span>
            ) : null}
            {card && card.flag > 0 ? (
              <span
                role="img"
                aria-label={`Flag ${flagLabel(card.flag).toLowerCase()}`}
                className="mx-1 size-2.5 rounded-full"
                style={{ backgroundColor: flagColor(card.flag) }}
              />
            ) : null}
            <IconButton label="Annulla (Z)" onClick={() => void undo()} disabled={busy || (!card && !answeredInSession)}>
              <Undo2 />
            </IconButton>
            {card ? (
              <Menu
                items={menuItems}
                trigger={
                  <IconButton label="Azioni sulla carta">
                    <MoreHorizontal />
                  </IconButton>
                }
              />
            ) : null}
          </>
        }
      />

      {loadError ? (
        <main className="flex flex-1 flex-col items-center justify-center gap-4 p-6">
          <Banner variant="error" className="w-full max-w-sm">
            {loadError}
          </Banner>
          <Button variant="outline" onClick={() => void load()}>
            Riprova
          </Button>
        </main>
      ) : !state ? (
        <main className="flex flex-1 items-center justify-center text-muted-foreground">
          <Spinner />
        </main>
      ) : state.done || !card ? (
        <DoneView deckName={deckName} answered={answeredInSession} onUndo={() => void undo()} />
      ) : (
        <>
          <div ref={scrollRef} className="relative flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain">
            {/* key: ogni carta e ogni lato entrano con il fade, e lo Shadow DOM riparte pulito. */}
            {hasAudio && !audioUnlocked ? (
              // Mazzo aperto dal telecomando senza un clic su questa pagina: il browser tace.
              // Qualunque clic sblocca (study/audio.ts); il pulsante dice dove farlo.
              <div className="sticky top-0 z-10 flex justify-center p-2">
                <Button variant="outline" size="sm" icon={<VolumeOff />} onClick={primeAudio} className="bg-background shadow-control">
                  Clicca per attivare l’audio
                </Button>
              </div>
            ) : null}
            <CardView
              key={`${card.card_id}-${revealed ? 'a' : 'q'}`}
              html={revealed ? card.answer_html : card.question_html}
              css={card.css}
              cardClass={card.card_class}
              dark={darkMode}
              onTap={revealed ? undefined : reveal}
              onPlay={onPlay}
              className={cn('flex flex-1 animate-fade-in flex-col', !revealed && 'cursor-pointer')}
            />
            <QueueCounts
              counts={state.counts}
              current={card.queue}
              className="pointer-events-none absolute right-3 top-2 rounded-sm bg-background/80 px-1.5 py-0.5 sm:hidden"
            />
          </div>
          <AnswerBar revealed={revealed} labels={card.button_labels} busy={busy} onReveal={reveal} onAnswer={(r) => void answer(r)} />
        </>
      )}

      <EditNoteModal
        noteId={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          toast('success', 'Nota salvata');
          void load({ keepRevealed: true });
        }}
      />
      <FlagModal isOpen={flagging} current={card?.flag ?? 0} onClose={() => setFlagging(false)} onSelect={(f) => void setFlag(f)} />
    </div>
  );
}

function AnswerBar({
  revealed,
  labels,
  busy,
  onReveal,
  onAnswer,
}: {
  revealed: boolean;
  labels: string[];
  busy: boolean;
  onReveal: () => void;
  onAnswer: (rating: Rating) => void;
}) {
  return (
    <div className="shrink-0 border-t bg-background pb-[max(0.75rem,env(safe-area-inset-bottom))] pl-[max(0.75rem,env(safe-area-inset-left))] pr-[max(0.75rem,env(safe-area-inset-right))] pt-3">
      <div className="mx-auto max-w-2xl">
        {revealed ? (
          <div className="grid grid-cols-4 gap-2">
            {RATINGS.map(({ rating, label }) => (
              <button
                key={rating}
                type="button"
                disabled={busy}
                onClick={() => onAnswer(rating)}
                aria-keyshortcuts={String(rating)}
                className={cn(
                  'flex h-14 select-none flex-col items-center justify-center gap-0.5 rounded-control border text-sm font-medium transition-[background-color,transform] duration-150 active:scale-[0.97] coarse:h-16',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-disabled',
                  rating === 1 && 'border-transparent bg-error/8 text-error-foreground hover:bg-error/16 dark:bg-error/16 dark:hover:bg-error/24',
                  (rating === 2 || rating === 4) && 'border-input bg-popover text-foreground shadow-control hover:bg-accent/50 dark:bg-input/32 dark:hover:bg-input/50',
                  rating === 3 && 'border-primary bg-primary text-primary-foreground hover:bg-primary/90',
                )}
              >
                <span>{label}</span>
                <span className={cn('font-mono text-2xs tabular-nums', rating === 3 ? 'text-primary-foreground/80' : 'text-muted-foreground')}>
                  {cleanLabel(labels[rating - 1])}
                </span>
              </button>
            ))}
          </div>
        ) : (
          <Button size="lg" onClick={onReveal} disabled={busy} className="h-14 w-full text-base coarse:h-16" aria-keyshortcuts="Space">
            Mostra risposta
          </Button>
        )}
      </div>
    </div>
  );
}

function DoneView({ deckName, answered, onUndo }: { deckName: string; answered: number; onUndo: () => void }) {
  const [today, setToday] = useState<TodayStats | null>(null);
  useEffect(() => {
    api.todayStats().then(setToday).catch(() => {});
  }, []);
  return (
    <main className="flex flex-1 animate-fade-in flex-col items-center justify-center gap-6 p-6 text-center">
      <CircleCheck className="size-10 text-muted-foreground" strokeWidth={1.5} />
      <div className="flex flex-col gap-1">
        <h1 className="text-base font-semibold">Per oggi hai finito{deckName ? ` con ${deckName}` : ''}</h1>
        <p className="text-sm text-muted-foreground">
          {today && today.reviews > 0
            ? `Oggi ${plural(today.reviews, 'carta', 'carte')} in ${formatDuration(today.seconds)}${today.again ? ` · ${today.again} «Di nuovo»` : ''}`
            : 'Non ci sono altre carte in scadenza in questo mazzo.'}
        </p>
      </div>
      <div className="flex gap-2">
        {answered > 0 ? (
          <Button variant="outline" size="lg" icon={<Undo2 />} onClick={onUndo} className="coarse:h-11">
            Annulla l’ultima
          </Button>
        ) : null}
        <Button size="lg" onClick={() => navigate({ name: 'decks' })} className="coarse:h-11">
          Torna ai mazzi
        </Button>
      </div>
    </main>
  );
}
