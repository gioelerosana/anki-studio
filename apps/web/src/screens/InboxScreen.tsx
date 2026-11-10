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
import { Badge, Banner, Button, Checkbox, EmptyHint, HeaderBar, IconButton, Modal, Spinner, cn } from '@anki-studio/ui-kit';
import { api } from '../api/client';
import type { DraftNote, Note } from '../api/types';
import { formatRelative, plural } from '../app/format';
import { navigate } from '../app/route';
import { isReservedTag } from '../notes/tags';
import { htmlToText } from '../app/text';
import { useToast } from '../app/toasts';
import { ConfirmDialog } from '../hub/ConfirmDialog';
import { ErrorBanner, describeError } from '../hub/errors';
import { useMediaQuery } from '../hub/hooks';
import { NoteInspector } from '../hub/NoteInspector';
import { Sheet } from '../hub/Sheet';
import { useActiveNote } from '../hub/useActiveNote';

const PAGE = 50;
/** Tetto di `limit` in `GET /hub/drafts` (`_MAX_LIMIT` in routers/hub.py). */
const MAX_PAGE = 200;
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

/** Le prime `count` bozze (a pagine del backend) e il totale. Senza duplicati: l'ordine scorre se qualcuno modifica. */
async function fetchDrafts(count: number): Promise<{ notes: DraftNote[]; total: number }> {
  const notes: DraftNote[] = [];
  const seen = new Set<number>();
  let total = 0;
  // `offset` conta ciò che il backend ha dato, non i `notes` senza doppioni: altrimenti una
  // pagina di soli doppioni rifarebbe all'infinito la stessa richiesta.
  let offset = 0;
  while (notes.length < count) {
    const r = await api.drafts(Math.min(MAX_PAGE, count - notes.length), offset);
    total = r.total;
    offset += r.notes.length;
    for (const n of r.notes) {
      if (!seen.has(n.id)) {
        seen.add(n.id);
        notes.push(n);
      }
    }
    if (r.notes.length === 0 || offset >= r.total) break;
  }
  return { notes, total };
}

type DraftAction = 'approve' | 'discard';

interface BatchOutcome {
  done: number;
  /** Note che il backend ha saltato: cambiate dopo che l'utente le ha viste, o non più bozze. */
  skipped: number[];
  /** Primo errore, se la richiesta è fallita a metà (le parti già fatte restano fatte). */
  error: unknown;
}

/**
 * Approva o scarta in blocchi, mandando per ogni nota il `modified` che l'utente ha visto:
 * il backend salta quelle cambiate nel frattempo (es. un agente le ha riscritte) invece di
 * approvare o cancellare un contenuto diverso da quello controllato.
 */
async function runDrafts(kind: DraftAction, ids: number[], mods: Record<number, number>): Promise<BatchOutcome> {
  const out: BatchOutcome = { done: 0, skipped: [], error: null };
  for (const part of chunk(ids, MAX_IDS)) {
    const expected: Record<number, number> = {};
    for (const id of part) if (mods[id] !== undefined) expected[id] = mods[id];
    try {
      if (kind === 'approve') {
        const r = await api.approveDrafts(part, expected);
        out.done += r.approved;
        out.skipped.push(...(r.skipped_ids ?? []));
      } else {
        const r = await api.discardDrafts(part, expected);
        out.done += r.discarded;
        out.skipped.push(...(r.skipped_ids ?? []));
      }
    } catch (err) {
      out.error = err;
      break;
    }
  }
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
  const { active, select, reset, onDirtyChange, dirty, guard } = useActiveNote();

  const [confirm, setConfirm] = useState<{ kind: 'discard' | 'approve-all'; ids: number[]; mods: Record<number, number> } | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  /** Approvare con la bozza aperta modificata e non salvata: aspetta la scelta (salva / no / annulla). */
  const [dirtyAsk, setDirtyAsk] = useState<number[] | null>(null);
  /** Bozze cambiate lato server mentre l'utente le guardava: non sono state approvate né scartate. */
  const [changed, setChanged] = useState<{ ids: Set<number>; kind: DraftAction } | null>(null);
  /** Per «Salva e approva»: salva l'editor del dettaglio aperto. */
  const saveHandle = useRef<(() => Promise<Note | null>) | null>(null);

  // Ogni richiesta ha un numero: una risposta che arriva dopo una più recente si scarta.
  const seq = useRef(0);
  const itemsRef = useRef<DraftNote[]>([]);
  itemsRef.current = items;

  /**
   * Ricarica l'elenco. `silent`: dopo un'azione o tornando sull'app, senza spinner e senza
   * perdere le pagine già caricate (chi ha aperto una bozza a pagina 3 non se la vede sparire).
   * Risponde con l'elenco nuovo, o `null` se la richiesta è fallita o superata da un'altra.
   */
  const load = useCallback(async (silent = false): Promise<DraftNote[] | null> => {
    const id = ++seq.current;
    if (!silent) {
      setLoading(true);
      setError(null);
    }
    try {
      const r = await fetchDrafts(silent ? Math.max(PAGE, itemsRef.current.length) : PAGE);
      if (id !== seq.current) return null;
      setItems(r.notes);
      setTotal(r.total);
      setError(null);
      setSelected((prev) => new Set(r.notes.filter((n) => prev.has(n.id)).map((n) => n.id)));
      return r.notes;
    } catch (err) {
      if (id !== seq.current) return null;
      if (!silent) {
        setItems([]);
        setTotal(0);
        setError(err);
      }
      return null;
    } finally {
      if (id === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Tornando sull'app (altra scheda, standby di iPad) un agente può aver mandato nuove bozze
  // o riscritto quelle che stavi guardando: le righe e `modified` si riallineano.
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

  /*
   * La bozza aperta. Se sparisce dall'elenco (approvata o scartata altrove, o fuori dalle pagine
   * caricate) ma l'editor ha modifiche non salvate, resta aperta com'era: chiuderla le butterebbe.
   * `lastActive` è l'ultima copia vista, per mostrarne l'intestazione.
   */
  const lastActive = useRef<DraftNote | null>(null);
  const found = useMemo(() => items.find((n) => n.id === active) ?? null, [items, active]);
  if (found) lastActive.current = found;
  const activeItem = found ?? (dirty && active !== null && lastActive.current?.id === active ? lastActive.current : null);
  const detached = active !== null && found === null && activeItem !== null;
  useEffect(() => {
    if (active !== null && !loading && !activeItem) reset();
  }, [active, activeItem, loading, reset]);

  /*
   * `modified` che il dettaglio sta mostrando. Se l'elenco si aggiorna con una versione più
   * recente e l'editor è pulito, il dettaglio si ricarica (cambia la `key`) e si allinea; se è
   * sporco resta con la versione vecchia e «Approva» manda quella, così il backend salta la
   * bozza invece di approvare un contenuto che non hai visto.
   */
  const [detailMod, setDetailMod] = useState<{ id: number; modified: number } | null>(null);
  useEffect(() => {
    if (!found) return;
    setDetailMod((prev) => {
      if (prev && prev.id === found.id && (dirty || prev.modified === found.modified)) return prev;
      return { id: found.id, modified: found.modified };
    });
  }, [found, dirty]);
  const seenMod = activeItem ? (detailMod?.id === activeItem.id ? detailMod.modified : activeItem.modified) : null;
  const staleDetail = dirty && found !== null && seenMod !== null && found.modified !== seenMod;

  /** `modified` visto per ogni id: quello dell'elenco, e per la bozza aperta quello del dettaglio. */
  const modsFor = (ids: number[], source: DraftNote[] = items) => {
    const byId = new Map(source.map((n) => [n.id, n.modified]));
    const mods: Record<number, number> = {};
    for (const id of ids) {
      const mod = id === active && seenMod !== null ? seenMod : byId.get(id);
      if (mod !== undefined) mods[id] = mod;
    }
    return mods;
  };

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const allSelected = items.length > 0 && selected.size === items.length;

  /** Su cosa agisce la barra: la selezione, o la bozza aperta se non c'è selezione. */
  const target = useMemo(() => (selected.size > 0 ? [...selected] : active !== null && found ? [active] : []), [selected, active, found]);

  /** Dopo un'azione: dice cosa è successo alle bozze saltate e le lascia selezionate per ricontrollarle. */
  function reportSkipped(skipped: number[], fresh: DraftNote[] | null, kind: DraftAction) {
    if (skipped.length === 0) return;
    const alive = new Set((fresh ?? itemsRef.current).map((n) => n.id));
    const stillThere = skipped.filter((id) => alive.has(id));
    if (stillThere.length > 0) {
      setChanged({ ids: new Set(stillThere), kind });
      setSelected(new Set(stillThere));
    }
    if (stillThere.length < skipped.length) toast('info', 'Alcune bozze non c’erano più (le ha già gestite un altro schermo).');
  }

  /** Approva. `mode`: «save» salva prima l'editor aperto, «drop» butta le sue modifiche (scelta esplicita). */
  async function approve(ids: number[], mode: 'plain' | 'save' | 'drop' = 'plain') {
    if (ids.length === 0 || busy) return;
    setBusy(true);
    setChanged(null);
    // Triage: approvando la bozza aperta si passa alla successiva (solo se non c'è una selezione)
    const index = items.findIndex((n) => n.id === active);
    const neighbour = selected.size === 0 && index >= 0 ? (items[index + 1] ?? items[index - 1])?.id : undefined;
    let mods = modsFor(ids);
    let after: DraftNote[] | null = null;
    try {
      if (mode === 'save' && active !== null) {
        const saved = saveHandle.current ? await saveHandle.current() : null;
        if (!saved) {
          toast('error', 'Le modifiche non sono state salvate, quindi la bozza non è stata approvata. Controlla il form.');
          return;
        }
        // il salvataggio cambia `modified`: l'approvazione deve valere per la versione appena salvata
        after = (await load(true)) ?? (await load(true));
        const fresh = after?.find((n) => n.id === active);
        if (!fresh) {
          toast('error', 'La bozza non è più nell’Inbox: non l’ho approvata.');
          return;
        }
        mods = { ...mods, [active]: fresh.modified };
      }
      const out = await runDrafts('approve', ids, mods);
      if (out.done > 0) toast('success', out.done === 1 ? 'Bozza approvata' : `${out.done} bozze approvate`);
      if (out.error) toast('error', describeError(out.error).message);
      setSelected(new Set(out.skipped));
      after = await load(true);
      reportSkipped(out.skipped, after, 'approve');
      if (out.done < ids.length && out.skipped.length === 0 && !out.error) toast('info', 'Alcune note non erano più bozze (forse le ha già approvate un altro schermo).');
      if (active !== null && ids.includes(active) && !out.skipped.includes(active) && !out.error) {
        // approvata: se l'utente ha scelto di buttare le modifiche, `reset` le butta; altrimenti l'editor è già pulito
        reset();
        if (wide && neighbour !== undefined && !ids.includes(neighbour)) select(neighbour);
      }
    } finally {
      setBusy(false);
    }
  }

  /** «Approva» sulla barra: con la bozza aperta modificata e non salvata chiede prima cosa farne. */
  function requestApprove(ids: number[]) {
    if (ids.length === 0 || busy) return;
    if (dirty && active !== null && ids.includes(active)) setDirtyAsk(ids);
    else void approve(ids);
  }

  async function confirmAction() {
    if (!confirm) return;
    setConfirmBusy(true);
    setConfirmError(null);
    setChanged(null);
    try {
      const kind = confirm.kind === 'discard' ? 'discard' : 'approve';
      // la bozza aperta ha il suo `modified` (quello che stai guardando), le altre quello confermato
      const mods = { ...confirm.mods };
      if (active !== null && seenMod !== null && confirm.ids.includes(active)) mods[active] = seenMod;
      const out = await runDrafts(kind, confirm.ids, mods);
      const word = kind === 'discard' ? 'scartat' : 'approvat';
      if (out.done > 0) toast('success', out.done === 1 ? `Bozza ${word}a` : `${out.done} bozze ${word}e`);
      if (out.error) {
        setConfirmError(out.error);
      } else {
        setConfirm(null);
      }
      const fresh = await load(true);
      reportSkipped(out.skipped, fresh, kind);
      if (!out.error) setSelected(new Set(out.skipped));
      // Scartata la bozza aperta (scelta esplicita) si chiude; se invece è stata approvata e ha
      // modifiche non salvate resta aperta: la tiene `activeItem`, con il suo avviso.
      if (kind === 'discard' && active !== null && confirm.ids.includes(active) && !out.skipped.includes(active) && !out.error) reset();
    } finally {
      setConfirmBusy(false);
    }
  }

  async function askApproveAll() {
    // le bozze sono più di una pagina: servono tutti gli id, e il `modified` di ciascuna
    setBusy(true);
    try {
      const all = await fetchDrafts(Infinity);
      // l'elenco sotto si riallinea con quello che si sta per confermare
      void load(true);
      if (all.notes.length === 0) {
        toast('info', 'Nessuna bozza da approvare');
      } else {
        setConfirmError(null);
        setConfirm({ kind: 'approve-all', ids: all.notes.map((n) => n.id), mods: modsFor(all.notes.map((n) => n.id), all.notes) });
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
      <Button
        variant="destructive-outline"
        icon={<Trash2 />}
        disabled={ids.length === 0 || busy}
        onClick={() => {
          setConfirmError(null);
          setConfirm({ kind: 'discard', ids, mods: modsFor(ids) });
        }}
        className="coarse:h-11"
      >
        Scarta{ids.length > 1 ? ` ${ids.length}` : ''}
      </Button>
      <Button icon={<Check />} loading={busy} disabled={ids.length === 0} onClick={() => requestApprove(ids)} className="coarse:h-11 coarse:px-5">
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
      // la `key` porta il `modified` mostrato: una bozza riscritta altrove (editor pulito) si ricarica
      key={`${activeItem.id}-${seenMod}`}
      noteId={activeItem.id}
      cardIds={activeItem.card_ids}
      saveIsPrimary={false}
      onDirtyChange={onDirtyChange}
      saveHandle={saveHandle}
      onSaved={(note) => {
        toast('success', 'Bozza salvata');
        setItems((prev) => prev.map((n) => (n.id === note.id ? { ...n, fields: note.fields, tags: note.tags } : n)));
        void load(true);
      }}
      header={
        <>
          {detached ? (
            <Banner variant="warning">Questa bozza non è più nell’Inbox (approvata o scartata altrove). Le tue modifiche non sono salvate: salvale o chiudi per scartarle.</Banner>
          ) : staleDetail ? (
            <Banner variant="warning">Questa bozza è cambiata dopo che l’hai aperta. Se la approvi ora non viene approvata; se salvi, sovrascrivi la nuova versione.</Banner>
          ) : null}
          <DraftHeader draft={activeItem} />
        </>
      }
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
            {changed ? (
              <Banner variant="warning" className="m-3" action={<Button size="xs" variant="outline" onClick={() => setChanged(null)} className="coarse:h-8">Ho capito</Button>}>
                {changed.ids.size === 1 ? '1 bozza è cambiata' : `${changed.ids.size} bozze sono cambiate`} nel frattempo e non {changed.ids.size === 1 ? 'è stata' : 'sono state'} {changed.kind === 'approve' ? 'approvat' : 'scartat'}{changed.ids.size === 1 ? 'a' : 'e'}: ricontrollale.
              </Banner>
            ) : null}
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
                    <DraftRow
                      key={draft.id}
                      draft={draft}
                      selected={selected.has(draft.id)}
                      active={draft.id === active}
                      changed={changed?.ids.has(draft.id) ?? false}
                      onToggle={() => toggle(draft.id)}
                      onOpen={() => {
                        setChanged((prev) => {
                          if (!prev?.ids.has(draft.id)) return prev;
                          const ids = new Set(prev.ids);
                          ids.delete(draft.id);
                          return ids.size > 0 ? { ...prev, ids } : null;
                        });
                        select(draft.id);
                      }}
                    />
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
          footer={bar(active !== null && found ? [active] : [], '')}
        >
          {detail}
        </Sheet>
      ) : null}

      <Modal
        isOpen={dirtyAsk !== null}
        onClose={() => setDirtyAsk(null)}
        title="Modifiche non salvate"
        description="La bozza aperta ha modifiche che non hai salvato. Approvandola adesso entra nello studio la versione salvata, senza le tue modifiche."
        size="sm"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDirtyAsk(null)} className="coarse:h-10">
              Annulla
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                const ids = dirtyAsk ?? [];
                setDirtyAsk(null);
                void approve(ids, 'drop');
              }}
              className="coarse:h-10"
            >
              Approva senza salvare
            </Button>
            <Button
              onClick={() => {
                const ids = dirtyAsk ?? [];
                setDirtyAsk(null);
                void approve(ids, 'save');
              }}
              className="coarse:h-10"
            >
              Salva e approva
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted-foreground">«Approva senza salvare» butta le modifiche; «Salva e approva» le tiene.</p>
      </Modal>

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
            ? 'Le bozze vengono cancellate con le loro carte. Non si può annullare da Anki Studio. Le note già approvate non vengono toccate. Quelle cambiate da quando le hai viste restano dove sono.'
            : 'Le loro carte entrano nello studio. Quelle cambiate da quando le hai viste restano in Inbox, da ricontrollare. Potrai ancora modificare o cancellare le altre dalla Libreria.'
        }
        confirmLabel={confirm?.kind === 'discard' ? `Scarta ${plural(confirm.ids.length, 'bozza', 'bozze')}` : `Approva ${plural(confirm?.ids.length ?? 0, 'bozza', 'bozze')}`}
        tone={confirm?.kind === 'discard' ? 'destructive' : 'default'}
        busy={confirmBusy}
        error={confirmError}
        onConfirm={() => void confirmAction()}
        onClose={() => !confirmBusy && setConfirm(null)}
      >
        {dirty && active !== null && confirm?.ids.includes(active) ? (
          <Banner variant="warning">
            La bozza aperta ha modifiche non salvate: {confirm.kind === 'discard' ? 'andranno perse con la bozza' : 'non entrano nello studio (si approva la versione salvata)'}.
          </Banner>
        ) : null}
      </ConfirmDialog>
      {guard}
    </div>
  );
}

function DraftHeader({ draft }: { draft: DraftNote }) {
  const created = new Date(draft.created * 1000).toLocaleString('it', { dateStyle: 'medium', timeStyle: 'short' });
  const shown = draft.tags.filter((t) => !isReservedTag(t));
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
  changed,
  onToggle,
  onOpen,
}: {
  draft: DraftNote;
  selected: boolean;
  active: boolean;
  /** Cambiata sul server dopo che l'utente l'aveva vista: non è stata approvata né scartata. */
  changed: boolean;
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
          {changed ? (
            <Badge variant="warning" size="sm">
              Cambiata
            </Badge>
          ) : null}
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
