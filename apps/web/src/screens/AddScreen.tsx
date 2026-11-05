/*
 * Aggiungi carta: tipo di nota, mazzo, campi, tag.
 *
 * Come in Anki desktop la schermata resta aperta dopo l'aggiunta (si inseriscono
 * più note di fila): si svuotano i campi, restano tipo di nota, mazzo e tag.
 * La validazione (primo campo vuoto, duplicato, cloze mancante) è del backend.
 */
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { ChevronLeft, Plus } from 'lucide-react';
import { Banner, Button, Field, HeaderBar, Select, Spinner } from '@anki-studio/ui-kit';
import { api } from '../api/client';
import { flattenDecks } from '../api/decks';
import type { DeckNode, Notetype } from '../api/types';
import { plural } from '../app/format';
import { navigate } from '../app/route';
import { useToast } from '../app/toasts';
import { NoteFields, TagsInput, parseTags } from '../notes/NoteFields';
import { getSettings, updateSettings } from '../settings';

export function AddScreen({ deckId }: { deckId: number | null }) {
  const toast = useToast();
  const [notetypes, setNotetypes] = useState<Notetype[] | null>(null);
  const [decks, setDecks] = useState<DeckNode[]>([]);
  const [notetypeId, setNotetypeId] = useState(0);
  const [targetDeck, setTargetDeck] = useState(0);
  const [values, setValues] = useState<Record<string, string>>({});
  const [tags, setTags] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [formKey, setFormKey] = useState(0);

  useEffect(() => {
    Promise.all([api.notetypes(), api.decks()])
      .then(([types, tree]) => {
        const flat = flattenDecks(tree);
        const { lastNotetypeId, lastDeckId } = getSettings();
        setNotetypes(types);
        setDecks(flat);
        setNotetypeId((types.find((t) => t.id === lastNotetypeId) ?? types[0])?.id ?? 0);
        const wanted = deckId ?? lastDeckId;
        setTargetDeck((flat.find((d) => d.id === wanted) ?? flat[0])?.id ?? 0);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Server non raggiungibile'));
  }, [deckId]);

  const notetype = notetypes?.find((t) => t.id === notetypeId) ?? null;
  const fields = useMemo(() => (notetype ? [...notetype.fields].sort((a, b) => a.ord - b.ord) : []), [notetype]);
  const filled = Object.values(values).some((v) => v.trim());

  function changeNotetype(id: number) {
    setNotetypeId(id);
    // I campi con lo stesso nome passano al nuovo tipo (Fronte → Fronte), gli altri si perdono.
    const next = notetypes?.find((t) => t.id === id);
    if (next) setValues((prev) => Object.fromEntries(next.fields.filter((f) => prev[f.name]).map((f) => [f.name, prev[f.name]])));
  }

  async function submit(e?: FormEvent) {
    e?.preventDefault();
    if (!notetype || !targetDeck || !filled || saving) return;
    setSaving(true);
    setError(null);
    try {
      const note = await api.createNote({
        deck_id: targetDeck,
        notetype_id: notetype.id,
        fields: Object.fromEntries(fields.map((f) => [f.name, values[f.name] ?? ''])),
        tags: parseTags(tags),
      });
      updateSettings({ lastNotetypeId: notetype.id, lastDeckId: targetDeck });
      toast('success', `Nota aggiunta · ${plural(note.card_ids.length, 'carta', 'carte')}`);
      setValues({});
      setFormKey((k) => k + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nota non aggiunta');
    } finally {
      setSaving(false);
    }
  }

  // Cmd/Ctrl+Invio da qualunque campo, come in Anki desktop.
  const submitRef = useRef(submit);
  submitRef.current = submit;
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        void submitRef.current();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const back = () => (deckId ? navigate({ name: 'study', deckId }) : navigate({ name: 'decks' }));

  return (
    <div className="flex h-full flex-col">
      <HeaderBar
        title="Aggiungi carta"
        leftContent={
          <Button variant="ghost" size="sm" icon={<ChevronLeft />} onClick={back} className="-ml-1.5 pl-1">
            {deckId ? 'Studio' : 'Mazzi'}
          </Button>
        }
      />
      <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col">
        <main className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 p-4 pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))]">
            {error ? <Banner variant="error">{error}</Banner> : null}
            {notetypes === null ? (
              error ? null : (
                <div className="flex justify-center p-8 text-muted-foreground">
                  <Spinner />
                </div>
              )
            ) : (
              <>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Tipo di nota">
                    <Select
                      size="lg"
                      value={String(notetypeId)}
                      onChange={(e) => changeNotetype(Number(e.target.value))}
                      options={notetypes.map((t) => ({ value: String(t.id), label: t.name }))}
                    />
                  </Field>
                  <Field label="Mazzo">
                    <Select
                      size="lg"
                      value={String(targetDeck)}
                      onChange={(e) => setTargetDeck(Number(e.target.value))}
                      options={decks.map((d) => ({ value: String(d.id), label: d.full_name.replaceAll('::', ' › ') }))}
                    />
                  </Field>
                </div>
                <NoteFields
                  key={`${notetypeId}-${formKey}`}
                  fields={fields}
                  values={values}
                  isCloze={notetype?.is_cloze ?? false}
                  autoFocus
                  onChange={(name, value) => setValues((prev) => ({ ...prev, [name]: value }))}
                />
                <TagsInput value={tags} onChange={setTags} />
              </>
            )}
          </div>
        </main>
        <div className="shrink-0 border-t bg-background pb-[max(0.75rem,env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] pt-3">
          <div className="mx-auto flex max-w-2xl justify-end">
            <Button type="submit" size="lg" icon={<Plus />} loading={saving} disabled={!notetype || !filled} className="coarse:h-12 coarse:px-6">
              Aggiungi
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}
