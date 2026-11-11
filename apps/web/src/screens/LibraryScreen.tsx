/*
 * Libreria: cerca, rivedi e sistema le note della collezione.
 *
 * La ricerca è quella di Anki (`deck:… tag:… is:suspended`): il campo accetta la sintassi
 * intera e i filtri rapidi (mazzo, tag, agente, sospese) non fanno che comporne i
 * pezzi, così chi sa la sintassi la usa e chi no ha i menu. Il backend risponde a pagine,
 * dalla nota modificata più di recente.
 *
 * Da `lg` l'elenco e il dettaglio stanno affiancati; più stretti il dettaglio è un foglio a
 * tutto schermo. Le azioni distruttive (cancella) chiedono sempre conferma e valgono per
 * ciò che si vede selezionato: cambiare ricerca azzera la selezione, così non si cancella
 * mai una nota che non è più sullo schermo.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Bot, ChevronLeft, FolderInput, History, Library, Plus, Search, Tag, Trash2, X } from 'lucide-react';
import { Badge, Banner, Button, Checkbox, EmptyHint, HeaderBar, IconButton, Input, Select, Spinner, cn } from '@anki-studio/ui-kit';
import { api, ApiError } from '../api/client';
import { flattenDecks } from '../api/decks';
import type { DeckNode, NoteSearchItem } from '../api/types';
import { ActivityList } from '../agents/ActivityList';
import { formatRelative, plural } from '../app/format';
import { navigate } from '../app/route';
import { isReservedTag } from '../notes/tags';
import { plainTitle, searchTerm } from '../app/text';
import { useToast } from '../app/toasts';
import { runEach } from '../hub/bulk';
import { ErrorBanner, describeError } from '../hub/errors';
import { useDebounced, useMediaQuery } from '../hub/hooks';
import { DeleteNotesDialog, MoveDialog, TagsDialog } from '../hub/LibraryDialogs';
import { NoteInspector } from '../hub/NoteInspector';
import { Sheet } from '../hub/Sheet';
import { useActiveNote } from '../hub/useActiveNote';

const PAGE = 50;
/** Tetto del backend per una pagina (`_MAX_LIMIT` in routers/browse.py). */
const MAX_PAGE = 200;
const AGENT_PREFIX = 'agent::';

interface Filters {
  deck: string;
  tag: string;
  agent: string;
  suspended: boolean;
}

const NO_FILTERS: Filters = { deck: '', tag: '', agent: '', suspended: false };

/** I pezzi dei filtri vanno in coda al testo digitato: Anki li mette in AND. */
function buildQuery(text: string, f: Filters): string {
  const parts = [text.trim()];
  if (f.deck) parts.push(searchTerm('deck', f.deck));
  if (f.tag) parts.push(searchTerm('tag', f.tag));
  if (f.agent) parts.push(searchTerm('tag', `${AGENT_PREFIX}${f.agent}`));
  if (f.suspended) parts.push('is:suspended');
  return parts.filter(Boolean).join(' ');
}

const agentOf = (item: NoteSearchItem) => item.tags.find((t) => t.toLowerCase().startsWith(AGENT_PREFIX))?.slice(AGENT_PREFIX.length) ?? null;

/** Tag di sistema dell'hub: non servono come filtro per tag (gli agenti hanno il loro menu). */
const isSystemTag = isReservedTag;

export function LibraryScreen() {
  const toast = useToast();
  const wide = useMediaQuery('(min-width: 1024px)');
  const searchRef = useRef<HTMLInputElement>(null);

  const [text, setText] = useState('');
  const [committed, setCommitted] = useState('');
  const debounced = useDebounced(text, 350);
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);

  const [items, setItems] = useState<NoteSearchItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);

  const [decks, setDecks] = useState<DeckNode[]>([]);
  const [allTags, setAllTags] = useState<string[]>([]);

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const { active, select, reset, onDirtyChange, dirty, guard } = useActiveNote();

  type Action = 'move' | 'tags' | 'delete';
  const [action, setAction] = useState<{ kind: Action; ids: number[] } | null>(null);
  const [acting, setActing] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const [progress, setProgress] = useState<string | null>(null);
  // Foglio «Attività degli agenti»: dove ci si accorge di una carta sbagliata si può annullare l'operazione.
  const [activityOpen, setActivityOpen] = useState(false);

  // Il debounce alimenta la ricerca; Invio la anticipa.
  useEffect(() => setCommitted(debounced), [debounced]);

  const query = useMemo(() => buildQuery(committed, filters), [committed, filters]);
  // Ogni richiesta ha un numero: una risposta che arriva dopo una ricerca più recente si scarta.
  const seq = useRef(0);

  // Mazzi e tag per i filtri: se falliscono i menu restano vuoti, la ricerca funziona lo stesso.
  useEffect(() => {
    api.decks().then((tree) => setDecks(flattenDecks(tree))).catch(() => {});
    api.tags().then(setAllTags).catch(() => {});
  }, []);

  // Nuova ricerca: si riparte dalla prima pagina e si azzera la selezione.
  useEffect(() => {
    const id = ++seq.current;
    setLoading(true);
    setError(null);
    setSelected(new Set());
    api
      .searchNotes(query, PAGE, 0)
      .then((r) => {
        if (id !== seq.current) return;
        setItems(r.notes);
        setTotal(r.total);
      })
      .catch((err: unknown) => {
        if (id !== seq.current) return;
        setItems([]);
        setTotal(0);
        setError(err);
      })
      .finally(() => id === seq.current && setLoading(false));
  }, [query, attempt]);

  /** Dopo una modifica: rilegge quanto è già caricato, senza tornare in cima né perdere la selezione. */
  const refresh = useCallback(
    async (loaded: number) => {
      const id = ++seq.current;
      try {
        const r = await api.searchNotes(query, Math.min(Math.max(loaded, PAGE), MAX_PAGE), 0);
        if (id !== seq.current) return;
        setItems(r.notes);
        setTotal(r.total);
        setSelected((prev) => new Set(r.notes.filter((n) => prev.has(n.id)).map((n) => n.id)));
      } catch {
        // l'elenco resta com'era: il prossimo gesto lo riallinea
      }
    },
    [query],
  );

  async function loadMore() {
    if (loadingMore || loading) return;
    const id = seq.current;
    setLoadingMore(true);
    try {
      const r = await api.searchNotes(query, PAGE, items.length);
      if (id !== seq.current) return;
      // Le modifiche fanno scorrere l'ordine: una nota può comparire due volte tra una pagina e l'altra.
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
   * La nota aperta. Se esce dai risultati (nuova ricerca, filtro, spostata) ma l'editor ha
   * modifiche non salvate, resta aperta com'era e un avviso lo dice: chiuderla le butterebbe in
   * silenzio. Senza modifiche si chiude da sola, come prima. `lastActive` è l'ultima copia vista.
   */
  const lastActive = useRef<NoteSearchItem | null>(null);
  const found = useMemo(() => items.find((n) => n.id === active) ?? null, [items, active]);
  if (found) lastActive.current = found;
  const activeItem = found ?? (dirty && active !== null && lastActive.current?.id === active ? lastActive.current : null);
  const detached = active !== null && found === null && activeItem !== null;
  useEffect(() => {
    if (active !== null && !loading && !activeItem) reset();
  }, [active, activeItem, loading, reset]);

  const tagOptions = useMemo(() => allTags.filter((t) => !isSystemTag(t)).sort((a, b) => a.localeCompare(b)), [allTags]);
  const agentOptions = useMemo(
    () => [...new Set(allTags.filter((t) => t.toLowerCase().startsWith(AGENT_PREFIX)).map((t) => t.slice(AGENT_PREFIX.length).split('::')[0]))].sort(),
    [allTags],
  );
  const filtersActive = JSON.stringify(filters) !== JSON.stringify(NO_FILTERS);

  /* ---- selezione ---- */
  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }
  const allSelected = items.length > 0 && selected.size === items.length;
  const toggleAll = () => setSelected(allSelected ? new Set() : new Set(items.map((n) => n.id)));

  /* ---- azioni ---- */
  function openAction(kind: Action, ids: number[]) {
    setActionError(null);
    setProgress(null);
    setAction({ kind, ids });
  }
  const closeAction = () => !acting && setAction(null);

  async function applyAction(run: (ids: number[]) => Promise<{ done: number; failed: number; error: unknown }>, success: (n: number) => string) {
    if (!action) return;
    setActing(true);
    setActionError(null);
    const result = await run(action.ids);
    setActing(false);
    setProgress(null);
    // anche con errori parziali l'elenco va riallineato: qualcosa può essere già cambiato
    if (result.done > 0) toast('success', success(result.done));
    // cancellata la nota aperta (scelta esplicita, con conferma): il dettaglio si chiude anche se era modificato
    if (action.kind === 'delete' && active !== null && action.ids.includes(active) && result.failed === 0) reset();
    await refresh(items.length);
    if (result.failed > 0) {
      setActionError(result.error ?? new Error('Operazione non riuscita'));
      // le note riuscite escono dalla selezione, restano quelle da riprovare
      return;
    }
    setAction(null);
    setSelected(new Set());
  }

  const doMove = (deckId: number) =>
    applyAction(
      (ids) => runEach(ids, (id) => api.moveNote(id, deckId), (d, t) => setProgress(`${d} di ${t}`)),
      (n) => `${plural(n, 'nota spostata', 'note spostate')}`,
    );

  const doTags = (change: { add: string[]; remove: string[] }) =>
    applyAction(
      async (ids) => {
        try {
          const r = await api.editNoteTags(ids, change);
          return { done: r.updated, failed: 0, error: null };
        } catch (err) {
          return { done: 0, failed: ids.length, error: err };
        }
      },
      (n) => `Tag aggiornati su ${plural(n, 'nota', 'note')}`,
    );

  const doDelete = () =>
    applyAction(
      (ids) =>
        runEach(
          ids,
          // già cancellata altrove (404): lo scopo è raggiunto
          (id) => api.deleteNote(id).catch((err: unknown) => (err instanceof ApiError && err.status === 404 ? undefined : Promise.reject(err))),
          (d, t) => setProgress(`Cancellate ${d} di ${t}`),
        ),
      (n) => `${plural(n, 'nota cancellata', 'note cancellate')}`,
    );

  // dopo aver cancellato o spostato la nota aperta, il dettaglio si allinea da solo (activeItem)
  const deleteTitles = useMemo(() => {
    if (action?.kind !== 'delete') return [];
    const byId = new Map(items.map((n) => [n.id, n.sort_field]));
    return action.ids.slice(0, 3).map((id) => plainTitle(byId.get(id) ?? ''));
  }, [action, items]);

  /* ---- tastiera: «/» cerca, Esc chiude il dettaglio o la selezione (da lg: sotto lo fa il foglio) ---- */
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const typing = !!el && (el.isContentEditable || /^(input|textarea|select)$/i.test(el.localName));
      if (e.key === '/' && !typing && !e.metaKey && !e.ctrlKey && !document.querySelector('[role="dialog"]')) {
        e.preventDefault();
        searchRef.current?.focus();
      } else if (e.key === 'Escape' && wide && !e.defaultPrevented && !document.querySelector('[role="dialog"]')) {
        if (selected.size > 0 && !typing) setSelected(new Set());
        else if (active !== null) select(null);
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [wide, selected.size, active, select]);

  const detail = activeItem ? (
    <NoteInspector
      key={activeItem.id}
      noteId={activeItem.id}
      cardIds={activeItem.card_ids}
      onDirtyChange={onDirtyChange}
      onSaved={() => {
        toast('success', 'Nota salvata');
        void refresh(items.length);
      }}
      header={
        <>
          {detached ? (
            <Banner variant="warning">
              Questa nota non è più tra i risultati della ricerca. Le tue modifiche non sono salvate: salvale, oppure chiudi per scartarle.
            </Banner>
          ) : null}
          <ItemHeader item={activeItem} />
        </>
      }
      actions={
        <div className="flex flex-wrap items-center gap-2 border-t pt-4">
          <Button variant="outline" icon={<FolderInput />} onClick={() => openAction('move', [activeItem.id])} className="coarse:h-10">
            Sposta
          </Button>
          <Button variant="destructive-outline" icon={<Trash2 />} onClick={() => openAction('delete', [activeItem.id])} className="coarse:h-10">
            Cancella
          </Button>
        </div>
      }
    />
  ) : null;

  const hasResults = items.length > 0;

  return (
    <div className="flex h-full flex-col">
      <HeaderBar
        title="Libreria"
        subtitle={!loading && !error ? plural(total, 'nota', 'note') : undefined}
        leftContent={
          <Button variant="ghost" size="sm" icon={<ChevronLeft />} onClick={() => navigate({ name: 'decks' })} className="-ml-1.5 pl-1">
            Mazzi
          </Button>
        }
        rightContent={
          <>
            <IconButton label="Attività degli agenti" onClick={() => setActivityOpen(true)}>
              <History />
            </IconButton>
            <IconButton label="Aggiungi carta" onClick={() => navigate({ name: 'add', deckId: null })}>
              <Plus />
            </IconButton>
          </>
        }
      />

      <div className="flex min-h-0 flex-1">
        <section aria-label="Elenco delle note" className={cn('flex min-h-0 min-w-0 flex-1 flex-col', wide && 'max-w-[28rem] shrink-0 border-r')}>
          {/* ricerca e filtri */}
          <div className="flex shrink-0 flex-col gap-2 border-b p-3 pl-[max(0.75rem,env(safe-area-inset-left))] pr-3">
            <form
              role="search"
              onSubmit={(e) => {
                e.preventDefault();
                setCommitted(text);
              }}
            >
              <Input
                ref={searchRef}
                type="search"
                size="lg"
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Cerca come in Anki: deck:Lingue tag:verbi"
                aria-label="Cerca nelle note, con la sintassi di Anki"
                leading={<Search />}
                trailing={
                  text ? (
                    <button
                      type="button"
                      aria-label="Cancella la ricerca"
                      onClick={() => {
                        setText('');
                        setCommitted('');
                        searchRef.current?.focus();
                      }}
                      className="rounded-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <X className="size-4" />
                    </button>
                  ) : undefined
                }
                autoCapitalize="none"
                autoCorrect="off"
                spellCheck={false}
                enterKeyHint="search"
                inputClassName="coarse:text-base [&::-webkit-search-cancel-button]:hidden"
              />
            </form>
            <div className="grid grid-cols-2 gap-2">
              <Select
                aria-label="Filtra per mazzo"
                value={filters.deck}
                onChange={(e) => setFilters((f) => ({ ...f, deck: e.target.value }))}
                selectClassName="coarse:text-base"
              >
                <option value="">Tutti i mazzi</option>
                {decks.map((d) => (
                  <option key={d.id} value={d.full_name}>
                    {d.full_name.replaceAll('::', ' › ')}
                  </option>
                ))}
              </Select>
              <Select aria-label="Filtra per tag" value={filters.tag} onChange={(e) => setFilters((f) => ({ ...f, tag: e.target.value }))} selectClassName="coarse:text-base">
                <option value="">Tutti i tag</option>
                {tagOptions.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </Select>
              {agentOptions.length > 0 ? (
                <Select
                  aria-label="Filtra per agente"
                  value={filters.agent}
                  onChange={(e) => setFilters((f) => ({ ...f, agent: e.target.value }))}
                  className="col-span-2"
                  selectClassName="coarse:text-base"
                >
                  <option value="">Tutti gli agenti</option>
                  {agentOptions.map((a) => (
                    <option key={a} value={a}>
                      Creata da {a}
                    </option>
                  ))}
                </Select>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" variant="outline" active={filters.suspended} aria-pressed={filters.suspended} onClick={() => setFilters((f) => ({ ...f, suspended: !f.suspended }))} className="coarse:h-9">
                Solo sospese
              </Button>
              {filtersActive ? (
                <Button size="sm" variant="ghost-muted" onClick={() => setFilters(NO_FILTERS)} className="coarse:h-9">
                  Azzera filtri
                </Button>
              ) : null}
            </div>
          </div>

          {/* elenco */}
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain" aria-busy={loading}>
            {error ? <ErrorBanner error={error} onRetry={() => setAttempt((n) => n + 1)} className="m-3" /> : null}
            {loading && !hasResults ? (
              <div className="flex justify-center p-8 text-muted-foreground">
                <Spinner />
              </div>
            ) : !error && !hasResults ? (
              <EmptyHint
                icon={<Library />}
                title="Nessuna nota trovata"
                description={query ? 'Prova una ricerca diversa o togli qualche filtro.' : 'La collezione non ha ancora note. Aggiungine una o sincronizza con AnkiWeb.'}
                action={
                  filtersActive || text ? (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setFilters(NO_FILTERS);
                        setText('');
                        setCommitted('');
                      }}
                    >
                      Azzera ricerca
                    </Button>
                  ) : undefined
                }
              />
            ) : (
              <>
                <div className="flex items-center gap-3 border-b px-3 py-1.5 text-2xs text-muted-foreground">
                  <Checkbox checked={allSelected} indeterminate={selected.size > 0 && !allSelected} onCheckedChange={toggleAll} aria-label="Seleziona tutte le note caricate" />
                  <span>
                    {selected.size > 0 ? `${plural(selected.size, 'selezionata', 'selezionate')} · ` : ''}
                    {items.length < total ? `${items.length} di ${total}` : plural(total, 'nota', 'note')}
                  </span>
                  {loading ? <Spinner className="ml-auto size-3.5" /> : null}
                </div>
                <ul className={cn('divide-y', loading && 'opacity-60')}>
                  {items.map((item) => (
                    <NoteRow key={item.id} item={item} selected={selected.has(item.id)} active={item.id === active} onToggle={() => toggle(item.id)} onOpen={() => select(item.id)} />
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

          {/* azioni sulla selezione */}
          {selected.size > 0 ? (
            <div className="shrink-0 border-t bg-background pb-[max(0.5rem,env(safe-area-inset-bottom))] pl-[max(0.75rem,env(safe-area-inset-left))] pr-3 pt-2">
              <div className="flex flex-wrap items-center gap-2" role="toolbar" aria-label="Azioni sulle note selezionate">
                <span className="mr-auto text-xs text-muted-foreground">{plural(selected.size, 'nota', 'note')}</span>
                <Button size="sm" variant="outline" icon={<FolderInput />} onClick={() => openAction('move', [...selected])} className="coarse:h-10">
                  Sposta
                </Button>
                <Button size="sm" variant="outline" icon={<Tag />} onClick={() => openAction('tags', [...selected])} className="coarse:h-10">
                  Tag
                </Button>
                <Button size="sm" variant="destructive-outline" icon={<Trash2 />} onClick={() => openAction('delete', [...selected])} className="coarse:h-10">
                  Cancella
                </Button>
                <IconButton label="Deseleziona tutto" size="sm" onClick={() => setSelected(new Set())} className="coarse:size-10">
                  <X />
                </IconButton>
              </div>
            </div>
          ) : null}
        </section>

        {wide ? (
          <aside aria-label="Dettaglio della nota" className="min-h-0 min-w-0 flex-1 overflow-y-auto overscroll-contain">
            {detail ? (
              <div className="mx-auto w-full max-w-2xl p-4 pr-[max(1rem,env(safe-area-inset-right))]">{detail}</div>
            ) : (
              <EmptyHint icon={<Library />} title="Scegli una nota" description="Qui vedi la carta com’è e puoi modificarla, spostarla o cancellarla." className="mt-16" />
            )}
          </aside>
        ) : null}
      </div>

      {!wide && detail ? (
        <Sheet title="Nota" backLabel="Libreria" onClose={() => select(null)}>
          {detail}
        </Sheet>
      ) : null}

      {activityOpen ? (
        <Sheet title="Attività degli agenti" backLabel="Libreria" onClose={() => setActivityOpen(false)}>
          <div className="overflow-hidden rounded-lg border bg-card">
            {/* annullare cancella o ripristina note: la ricerca riparte da capo, e i tag per i filtri si rileggono */}
            <ActivityList
              onUndone={() => {
                setAttempt((n) => n + 1);
                api.tags().then(setAllTags).catch(() => {});
              }}
            />
          </div>
        </Sheet>
      ) : null}

      <MoveDialog isOpen={action?.kind === 'move'} count={action?.ids.length ?? 0} decks={decks} busy={acting} error={actionError} onConfirm={(id) => void doMove(id)} onClose={closeAction} />
      <TagsDialog isOpen={action?.kind === 'tags'} count={action?.ids.length ?? 0} suggestions={tagOptions} busy={acting} error={actionError} onConfirm={(c) => void doTags(c)} onClose={closeAction} />
      <DeleteNotesDialog
        isOpen={action?.kind === 'delete'}
        count={action?.ids.length ?? 0}
        titles={deleteTitles}
        busy={acting}
        progress={progress}
        error={actionError}
        onConfirm={() => void doDelete()}
        onClose={closeAction}
      />
      {guard}
    </div>
  );
}

function ItemHeader({ item }: { item: NoteSearchItem }) {
  const agent = agentOf(item);
  const shown = item.tags.filter((t) => !isSystemTag(t));
  return (
    <div className="flex flex-col gap-1.5">
      <h2 className="break-words text-base font-semibold">{plainTitle(item.sort_field) || '(senza testo)'}</h2>
      <p className="text-2xs text-muted-foreground">
        {item.notetype_name}
        {item.deck_name ? ` · ${item.deck_name.replaceAll('::', ' › ')}` : ''} · modificata {formatRelative(item.modified)}
      </p>
      <div className="flex flex-wrap items-center gap-1.5">
        {agent ? (
          <Badge variant="outline" icon={<Bot />}>
            Creata da {agent}
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

function NoteRow({
  item,
  selected,
  active,
  onToggle,
  onOpen,
}: {
  item: NoteSearchItem;
  selected: boolean;
  active: boolean;
  onToggle: () => void;
  onOpen: () => void;
}) {
  const agent = agentOf(item);
  return (
    <li className={cn('flex items-stretch', active && 'bg-sidebar-row-active')}>
      {/* area del tocco più larga della casella (16px): su iPad un dito non la centra */}
      <div className="flex w-11 shrink-0 cursor-pointer items-center justify-center pl-[env(safe-area-inset-left)] coarse:w-12" onClick={onToggle}>
        <Checkbox
          checked={selected}
          onCheckedChange={onToggle}
          // il clic sulla casella non deve arrivare anche all'area attorno, o si commuta due volte
          onClick={(e) => e.stopPropagation()}
          aria-label={`Seleziona «${plainTitle(item.sort_field) || 'nota senza testo'}»`}
        />
      </div>
      <button
        type="button"
        onClick={onOpen}
        aria-current={active || undefined}
        className="flex min-h-14 min-w-0 flex-1 flex-col justify-center gap-0.5 py-2 pr-3 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
      >
        <span className="flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-sm">{plainTitle(item.sort_field) || '(senza testo)'}</span>
          {agent ? (
            <Badge variant="outline" size="sm" icon={<Bot />} title={`Creata da ${agent}`} className="max-w-28 truncate">
              {agent}
            </Badge>
          ) : null}
        </span>
        <span className="truncate text-2xs text-muted-foreground">
          {item.notetype_name}
          {item.deck_name ? ` · ${item.deck_name.replaceAll('::', ' › ')}` : ''} · {formatRelative(item.modified)}
        </span>
      </button>
    </li>
  );
}
