/*
 * Stato di modifica di una nota (campi + tag), condiviso da «Modifica nota» nello studio,
 * dalla libreria e dall'inbox. Carica nota e tipo di nota, tiene i valori in modifica e
 * salva con `PATCH /notes/{id}`; il contenuto resta HTML grezzo come in Anki.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { Note, Notetype, NotetypeField } from '../api/types';
import { getNotetypes } from './notetypes';
import { parseTags } from './NoteFields';
import { isReservedTag } from './tags';

export interface NoteEditor {
  note: Note | null;
  notetype: Notetype | null;
  fields: NotetypeField[];
  values: Record<string, string>;
  /** Solo i tag modificabili, separati da spazi (i riservati non ci sono). */
  tags: string;
  /** Tag riservati della nota (`hub::bozza`, `agent::…`, `ext::…`): si mostrano, non si toccano. */
  reservedTags: string[];
  /** Tag riservati digitati nel campo: il salvataggio resta bloccato finché non li si toglie. */
  typedReserved: string[];
  setValue: (name: string, value: string) => void;
  setTags: (tags: string) => void;
  dirty: boolean;
  /** Modificato e senza tag riservati digitati: l'unico caso in cui «Salva» è attivo. */
  canSave: boolean;
  loading: boolean;
  saving: boolean;
  error: unknown;
  save: () => Promise<Note | null>;
  reload: () => void;
}

const editableTags = (tags: string[]) => tags.filter((t) => !isReservedTag(t)).join(' ');

export function useNoteEditor(noteId: number | null): NoteEditor {
  const [note, setNote] = useState<Note | null>(null);
  const [notetype, setNotetype] = useState<Notetype | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [tags, setTags] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (noteId === null) return;
    let cancelled = false;
    setNote(null);
    setError(null);
    Promise.all([api.note(noteId), getNotetypes()])
      .then(([n, types]) => {
        if (cancelled) return;
        setNote(n);
        setNotetype(types.find((t) => t.id === n.notetype_id) ?? null);
        setValues(n.fields);
        setTags(editableTags(n.tags));
      })
      .catch((err: unknown) => !cancelled && setError(err));
    return () => {
      cancelled = true;
    };
  }, [noteId, attempt]);

  // Ordine dei campi del tipo di nota; se manca (tipo cambiato altrove) quello della risposta.
  const fields = useMemo(
    () => (notetype ? [...notetype.fields].sort((a, b) => a.ord - b.ord) : Object.keys(values).map((name, ord) => ({ name, ord }))),
    [notetype, values],
  );

  const typedReserved = useMemo(() => parseTags(tags).filter(isReservedTag), [tags]);
  const tagsChanged = note !== null && parseTags(tags).join(' ') !== editableTags(note.tags);

  const save = useCallback(async (): Promise<Note | null> => {
    if (!note || typedReserved.length > 0) return null;
    setSaving(true);
    setError(null);
    try {
      // I tag si rimandano solo se l'utente li ha cambiati; allora la lista porta anche quelli
      // riservati com'erano (il PATCH sostituisce l'elenco: senza, si toglierebbero).
      const patch: { fields: Record<string, string>; tags?: string[] } = { fields: values };
      if (tagsChanged) patch.tags = [...note.tags.filter(isReservedTag), ...parseTags(tags)];
      const saved = await api.updateNote(note.id, patch);
      setNote(saved);
      setValues(saved.fields);
      setTags(editableTags(saved.tags));
      return saved;
    } catch (err) {
      setError(err);
      return null;
    } finally {
      setSaving(false);
    }
  }, [note, values, tags, tagsChanged, typedReserved]);

  const dirty = note !== null && (Object.entries(values).some(([k, v]) => note.fields[k] !== v) || tagsChanged);

  return {
    note,
    notetype,
    fields,
    values,
    tags,
    reservedTags: note ? note.tags.filter(isReservedTag) : [],
    typedReserved,
    setValue: (name, value) => setValues((prev) => ({ ...prev, [name]: value })),
    setTags,
    dirty,
    canSave: dirty && typedReserved.length === 0,
    loading: noteId !== null && note === null && error === null,
    saving,
    error,
    save,
    reload: () => setAttempt((n) => n + 1),
  };
}
