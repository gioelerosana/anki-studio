import { useEffect, useState } from 'react';
import { Banner, Button, Modal, Spinner } from '@anki-studio/ui-kit';
import { api } from '../api/client';
import type { Note, Notetype } from '../api/types';
import { NoteFields, TagsInput, parseTags } from './NoteFields';

export function EditNoteModal({
  noteId,
  onClose,
  onSaved,
}: {
  /** `null` = chiuso. */
  noteId: number | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [note, setNote] = useState<Note | null>(null);
  const [notetype, setNotetype] = useState<Notetype | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [tags, setTags] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (noteId === null) return;
    let cancelled = false;
    setNote(null);
    setError(null);
    Promise.all([api.note(noteId), api.notetypes()])
      .then(([n, types]) => {
        if (cancelled) return;
        setNote(n);
        setNotetype(types.find((t) => t.id === n.notetype_id) ?? null);
        setValues(n.fields);
        setTags(n.tags.join(' '));
      })
      .catch((err: unknown) => !cancelled && setError(err instanceof Error ? err.message : 'Nota non caricata'));
    return () => {
      cancelled = true;
    };
  }, [noteId]);

  // Ordine dei campi del tipo di nota; se manca (tipo cambiato altrove) quello della risposta.
  const fields = notetype
    ? [...notetype.fields].sort((a, b) => a.ord - b.ord)
    : Object.keys(values).map((name, ord) => ({ name, ord }));

  async function save() {
    if (!note) return;
    setSaving(true);
    setError(null);
    try {
      await api.updateNote(note.id, { fields: values, tags: parseTags(tags) });
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Nota non salvata');
    } finally {
      setSaving(false);
    }
  }

  const dirty =
    note !== null &&
    (Object.entries(values).some(([k, v]) => note.fields[k] !== v) || parseTags(tags).join(' ') !== note.tags.join(' '));

  return (
    <Modal
      isOpen={noteId !== null}
      onClose={onClose}
      title="Modifica nota"
      description={notetype?.name}
      size="lg"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} className="coarse:h-10">
            Annulla
          </Button>
          <Button onClick={save} loading={saving} disabled={!dirty} className="coarse:h-10">
            Salva
          </Button>
        </>
      }
    >
      {error ? (
        <Banner variant="error" className="mb-4">
          {error}
        </Banner>
      ) : null}
      {note ? (
        <div className="flex flex-col gap-4">
          <NoteFields
            fields={fields}
            values={values}
            isCloze={notetype?.is_cloze ?? false}
            onChange={(name, value) => setValues((prev) => ({ ...prev, [name]: value }))}
          />
          <TagsInput value={tags} onChange={setTags} />
        </div>
      ) : error ? null : (
        <div className="flex justify-center p-6 text-muted-foreground">
          <Spinner />
        </div>
      )}
    </Modal>
  );
}
