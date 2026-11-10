/*
 * Inbox: le bozze create dagli agenti, da controllare prima che entrino nello studio.
 *
 * Una bozza è una nota con le carte sospese e il tag `hub::bozza` (docs/PIANO-HUB.md).
 * Qui la si guarda com'è (anteprima della prima carta), la si corregge se serve e poi si
 * approva (le carte entrano nello studio) o si scarta (la nota viene cancellata: solo
 * dopo conferma, e il backend cancella solo note che sono davvero bozze).
 *
 * Un solo pulsante primario, «Approva», in una barra in basso che agisce sulle bozze
 * selezionate oppure, senza selezione, su quella aperta. «Approva tutte» sta in alto e
 * chiede conferma col numero.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Bot, Check, ChevronLeft, Inbox, Library, Trash2 } from 'lucide-react';
import { Badge, Button, Checkbox, EmptyHint, HeaderBar, IconButton, Spinner, cn } from '@anki-studio/ui-kit';
import { api } from '../api/client';
import type { DraftNote } from '../api/types';
import { formatRelative, plural } from '../app/format';
import { navigate } from '../app/route';
import { htmlToText } from '../app/text';
import { useToast } from '../app/toasts';
import { ConfirmDialog } from '../hub/ConfirmDialog';
import { ErrorBanner, describeError } from '../hub/errors';
import { useMediaQuery } from '../hub/hooks';
import { NoteInspector } from '../hub/NoteInspector';
import { Sheet } from '../hub/Sheet';
import { useActiveNote } from '../hub/useActiveNote';

const PAGE = 50;
/** Tetto di `NoteIdsIn` nel backend: oltre, le richieste si spezzano. */
const MAX_IDS = 500;

const titleOf = (draft: DraftNote) => {
  const first = Object.values(draft.fields)[0] ?? '';
  const text = htmlToText(first);
  return text.length > 140 ? `${text.slice(0, 140)}…` : text;
};

function chunk<T>(list: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < list.length; i += size) out.push(list.slice(i, i + size));
  return out;
}

export function InboxScreen() {
  const toast = useToast();
  const wide = useMediaQuery('(min-width: 1024px)');

  const [items, setItems] = useState<DraftNote[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const { active, select, reset, onDirtyChange, guard } = useActiveNote();

  const [confirm, setConfirm] = useState<{ kind: 'discard' | 'approve-all'; ids: number[] } | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  // Ogni richiesta ha un numero: una risposta che arriva dopo una più recente si scarta.
  const seq = useRef(0);

  /** Prima pagina. `silent`: dopo un'azione, senza spinner né azzeramento dell'elenco. */
  const load = useCallback(async (silent = false) => {
    const id = ++seq.current;
    if (!silent) {
      setLoading(true);
      setError(null);
    }
    try {
      const r = await api.drafts(PAGE, 0);
      if (id !== seq.current) return;
      setItems(r.notes);
      setTotal(r.total);
      setError(null);
      setSelected((prev) => new Set(r.notes.filter((n) => prev.has(n.id)).map((n) => n.id)));
    } catch (err) {
      if (id !== seq.current) return;
      if (!silent) {
        setItems([]);
        setTotal(0);
        setError(err);
      }
    } finally {
      if (id === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Tornando sull'app (altra scheda, standby di iPad) un agente può aver mandato nuove bozze.
  useEffect(() => {
    const onVisible = () => !document.hidden && void load(true);
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, [load]);

  async function loadMore() {
    if (loadingMore) return;
    const id = seq.current;
    setLoadingMore(true);
    try {
      const r = await api.drafts(PAGE, items.length);
      if (id !== seq.current) return;
      setItems((prev) => {
        const seen = new Set(prev.map((n) => n.id));
        return [...prev, ...r.notes.filter((n) => !seen.has(n.id))];
      });
      setTotal(r.total);
    } catch (err) {
      toast('error', describeError(err).message);
    } finally {
      setLoadingMore(false);
    }
  }

  const activeItem = useMemo(() => items.find((n) => n.id === active) ?? null, [items, active]);
  useEffect(() => {
    if (active !== null && !loading && !activeItem) reset();
  }, [active, activeItem, loading, reset]);

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const allSelected = items.length > 0 && selected.size === items.length;

  /** Su cosa agisce la barra: la selezione, o la bozza aperta se non c'è selezione. */
  const target = useMemo(() => (selected.size > 0 ? [...selected] : active !== null && activeItem ? [active] : []), [selected, active, activeItem]);

  async function inChunks(ids: number[], call: (part: number[]) => Promise<number>): Promise<number> {
    let done = 0;
    for (const part of chunk(ids, MAX_IDS)) done += await call(part);
    return done;
  }

  async function approve(ids: number[]) {
    if (ids.length === 0 || busy) return;
    setBusy(true);
    // Triage: approvando la bozza aperta si passa alla successiva (solo se non c'è una selezione)
    const index = items.findIndex((n) => n.id === active);
    const neighbour = selected.size === 0 && index >= 0 ? (items[index + 1] ?? items[index - 1])?.id : undefined;
    try {
      const approved = await inChunks(ids, async (part) => (await api.approveDrafts(part)).approved);
      toast('success', approved === 1 ? 'Bozza approvata' : `${approved} bozze approvate`);
      if (approved < ids.length) toast('info', 'Alcune note non erano più bozze (forse le ha già approvate un altro schermo).');
    } catch (err) {
      toast('error', describeError(err).message);
    }
    setSelected(new Set());
    await load(true);
    setBusy(false);
    if (ids.includes(active ?? -1)) {
      reset();
      if (wide && neighbour !== undefined && !ids.includes(neighbour)) select(neighbour);
    }
  }

  async function confirmAction() {
    if (!confirm) return;
    setConfirmBusy(true);
    setConfirmError(null);
    try {
      if (confirm.kind === 'discard') {
        const discarded = await inChunks(confirm.ids, async (part) => (await api.discardDrafts(part)).discarded);
        toast('success', discarded === 1 ? 'Bozza scartata' : `${discarded} bozze scartate`);
      } else {
        const approved = await inChunks(confirm.ids, async (part) => (await api.approveDrafts(part)).approved);
        toast('success', approved === 1 ? 'Bozza approvata' : `${approved} bozze approvate`);
      }
      setConfirm(null);
      setSelected(new Set());
      if (active !== null && confirm.ids.includes(active)) reset();
      await load(true);
    } catch (err) {
      setConfirmError(err);
      await load(true);
    } finally {
      setConfirmBusy(false);
    }
  }

  async function askApproveAll() {
    // le bozze sono più di una pagina: servono tutti gli id, non solo quelli caricati
    setBusy(true);
    try {
      const ids: number[] = [];
      let offset = 0;
      for (;;) {
        const r = await api.drafts(PAGE, offset);
        ids.push(...r.notes.map((n) => n.id));
        offset += r.notes.length;
        if (r.notes.length === 0 || offset >= r.total) break;
      }
      if (ids.length === 0) {
        toast('info', 'Nessuna bozza da approvare');
        await load(true);
      } else {
        setConfirmError(null);
        setConfirm({ kind: 'approve-all', ids });
      }
    } catch (err) {
      toast('error', describeError(err).message);
    } finally {
      setBusy(false);
    }
  }

  const targetLabel = selected.size > 0 ? plural(selected.size, 'bozza selezionata', 'bozze selezionate') : activeItem ? 'Bozza aperta' : 'Scegli una bozza';

  const bar = (ids: number[], label: string) => (
    <>
      <span className="mr-auto min-w-0 truncate text-xs text-muted-foreground">{label}</span>
      <Button variant="destructive-outline" icon={<Trash2 />} disabled={ids.length === 0 || busy} onClick={() => { setConfirmError(null); setConfirm({ kind: 'discard', ids }); }} className="coarse:h-11">
        Scarta{ids.length > 1 ? ` ${ids.length}` : ''}
      </Button>
      <Button icon={<Check />} loading={busy} disabled={ids.length === 0} onClick={() => void approve(ids)} className="coarse:h-11 coarse:px-5">
        Approva{ids.length > 1 ? ` ${ids.length}` : ''}
      </Button>
    </>
  );

  // Esc chiude il dettaglio a due colonne (sotto lo fa il foglio)
  useEffect(() => {
    if (!wide) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented || document.querySelector('[role="dialog"]')) return;
      const el = e.target as HTMLElement | null;
      if (el && /^(input|textarea|select)$/i.test(el.localName)) return;
      if (selected.size > 0) setSelected(new Set());
      else if (active !== null) select(null);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [wide, selected.size, active, select]);

  const detail = activeItem ? (
    <NoteInspector
      key={activeItem.id}
      noteId={activeItem.id}
      cardIds={activeItem.card_ids}
      saveIsPrimary={false}
      onDirtyChange={onDirtyChange}
      onSaved={(note) => {
        toast('success', 'Bozza salvata');
        setItems((prev) => prev.map((n) => (n.id === note.id ? { ...n, fields: note.fields, tags: note.tags } : n)));
      }}
      header={<DraftHeader draft={activeItem} />}
    />
  ) : null;

  const sheetOpen = !wide && detail !== null;

  return (
    <div className="flex h-full flex-col">
      <HeaderBar
        title="Inbox"
        subtitle={!loading && !error && total > 0 ? plural(total, 'bozza', 'bozze') : undefined}
        leftContent={
          <Button variant="ghost" size="sm" icon={<ChevronLeft />} onClick={() => navigate({ name: 'decks' })} className="-ml-1.5 pl-1">
            Mazzi
          </Button>
        }
        rightContent={
          <>
            {total > 0 ? (
              <Button variant="outline" size="sm" disabled={busy} onClick={() => void askApproveAll()} className="coarse:h-9">
                Approva tutte
              </Button>
            ) : null}
            <IconButton label="Libreria" onClick={() => navigate({ name: 'library' })}>
              <Library />
            </IconButton>
          </>
        }
      />

      <div className="flex min-h-0 flex-1">
        <section aria-label="Bozze da approvare" className={cn('flex min-h-0 min-w-0 flex-1 flex-col', wide && 'max-w-[28rem] shrink-0 border-r')}>
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain" aria-busy={loading}>
            {error ? <ErrorBanner error={error} onRetry={() => void load()} className="m-3" /> : null}
            {loading && items.length === 0 ? (
              <div className="flex justify-center p-8 text-muted-foreground">
                <Spinner />
              </div>
            ) : !error && items.length === 0 ? (
              <EmptyHint
                icon={<Inbox />}
                title="Nessuna bozza"
                description="Le carte create da Claude, Hermes o da uno script con un token «bozze» arrivano qui, con le carte sospese, e entrano nello studio solo dopo che le approvi."
                action={
                  <Button variant="outline" size="sm" onClick={() => navigate({ name: 'settings' })}>
                    Gestisci gli agenti
                  </Button>
                }
                className="mt-8"
              />
            ) : (
              <>
                <div className="flex items-center gap-3 border-b px-3 py-1.5 text-2xs text-muted-foreground">
                  <Checkbox checked={allSelected} indeterminate={selected.size > 0 && !allSelected} onCheckedChange={() => setSelected(allSelected ? new Set() : new Set(items.map((n) => n.id)))} aria-label="Seleziona tutte le bozze caricate" />
                  <span>{items.length < total ? `${items.length} di ${total}` : plural(total, 'bozza', 'bozze')}</span>
                </div>
                <ul className="divide-y">
                  {items.map((draft) => (
                    <DraftRow key={draft.id} draft={draft} selected={selected.has(draft.id)} active={draft.id === active} onToggle={() => toggle(draft.id)} onOpen={() => select(draft.id)} />
                  ))}
                </ul>
                {items.length < total ? (
                  <div className="flex justify-center p-3">
                    <Button variant="outline" size="sm" loading={loadingMore} onClick={() => void loadMore()} className="coarse:h-10">
                      Carica altre ({total - items.length})
                    </Button>
                  </div>
                ) : null}
              </>
            )}
          </div>
        </section>

        {wide ? (
          <aside aria-label="Dettaglio della bozza" className="min-h-0 min-w-0 flex-1 overflow-y-auto overscroll-contain">
            {detail ? (
              <div className="mx-auto w-full max-w-2xl p-4 pr-[max(1rem,env(safe-area-inset-right))]">{detail}</div>
            ) : (
              <EmptyHint icon={<Inbox />} title="Scegli una bozza" description="Guarda la carta, correggila se serve e poi approvala." className="mt-16" />
            )}
          </aside>
        ) : null}
      </div>

      {/* Barra in basso. Con il foglio aperto (schermo stretto) la mostra il foglio, così non ci sono due «Approva». */}
      {items.length > 0 && !sheetOpen ? (
        <div className="shrink-0 border-t bg-background pb-[max(0.75rem,env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] pt-3">
          <div className="flex items-center gap-2" role="toolbar" aria-label="Azioni sulle bozze">
            {bar(target, targetLabel)}
          </div>
        </div>
      ) : null}

      {sheetOpen ? (
        <Sheet
          title="Bozza"
          backLabel="Inbox"
          onClose={() => select(null)}
          footer={bar(active !== null ? [active] : [], '')}
        >
          {detail}
        </Sheet>
      ) : null}

      <ConfirmDialog
        isOpen={confirm !== null}
        title={
          confirm?.kind === 'discard'
            ? confirm.ids.length === 1
              ? 'Scartare la bozza?'
              : `Scartare ${confirm.ids.length} bozze?`
            : `Approvare tutte le ${confirm?.ids.length ?? 0} bozze?`
        }
        description={
          confirm?.kind === 'discard'
            ? 'Le bozze vengono cancellate con le loro carte. Non si può annullare da Anki Studio. Le note già approvate non vengono toccate.'
            : 'Le loro carte entrano nello studio. Potrai ancora modificarle o cancellarle dalla Libreria.'
        }
        confirmLabel={confirm?.kind === 'discard' ? `Scarta ${plural(confirm.ids.length, 'bozza', 'bozze')}` : `Approva ${plural(confirm?.ids.length ?? 0, 'bozza', 'bozze')}`}
        tone={confirm?.kind === 'discard' ? 'destructive' : 'default'}
        busy={confirmBusy}
        error={confirmError}
        onConfirm={() => void confirmAction()}
        onClose={() => !confirmBusy && setConfirm(null)}
      />
      {guard}
    </div>
  );
}

function DraftHeader({ draft }: { draft: DraftNote }) {
  const created = new Date(draft.created * 1000).toLocaleString('it', { dateStyle: 'medium', timeStyle: 'short' });
  const shown = draft.tags.filter((t) => !/^(agent|ext|hub)::/i.test(t));
  return (
    <div className="flex flex-col gap-1.5">
      <h2 className="break-words text-base font-semibold">{titleOf(draft) || '(senza testo)'}</h2>
      <p className="text-2xs text-muted-foreground">
        {draft.notetype_name}
        {draft.deck_name ? ` · ${draft.deck_name.replaceAll('::', ' › ')}` : ''} · {created}
      </p>
      <div className="flex flex-wrap items-center gap-1.5">
        {draft.agent ? (
          <Badge variant="outline" icon={<Bot />}>
            {draft.agent}
          </Badge>
        ) : null}
        {shown.map((t) => (
          <Badge key={t} variant="secondary">
            {t}
          </Badge>
        ))}
      </div>
    </div>
  );
}

function DraftRow({
  draft,
  selected,
  active,
  onToggle,
  onOpen,
}: {
  draft: DraftNote;
  selected: boolean;
  active: boolean;
  onToggle: () => void;
  onOpen: () => void;
}) {
  const title = titleOf(draft);
  return (
    <li className={cn('flex items-stretch', active && 'bg-sidebar-row-active')}>
      <div className="flex w-11 shrink-0 cursor-pointer items-center justify-center pl-[env(safe-area-inset-left)] coarse:w-12" onClick={onToggle}>
        <Checkbox checked={selected} onCheckedChange={onToggle} onClick={(e) => e.stopPropagation()} aria-label={`Seleziona «${title || 'bozza senza testo'}»`} />
      </div>
      <button
        type="button"
        onClick={onOpen}
        aria-current={active || undefined}
        className="flex min-h-14 min-w-0 flex-1 flex-col justify-center gap-0.5 py-2 pr-3 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
      >
        <span className="flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-sm">{title || '(senza testo)'}</span>
          {draft.agent ? (
            <Badge variant="outline" size="sm" icon={<Bot />} className="max-w-28 truncate">
              {draft.agent}
            </Badge>
          ) : null}
        </span>
        <span className="truncate text-2xs text-muted-foreground">
          {draft.deck_name ? `${draft.deck_name.replaceAll('::', ' › ')} · ` : ''}
          {draft.notetype_name} · {formatRelative(draft.created)}
        </span>
      </button>
    </li>
  );
}
