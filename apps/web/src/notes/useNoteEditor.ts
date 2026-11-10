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

export interface NoteEditor {
  note: Note | null;
  notetype: Notetype | null;
  fields: NotetypeField[];
  values: Record<string, string>;
  tags: string;
  setValue: (name: string, value: string) => void;
  setTags: (tags: string) => void;
  dirty: boolean;
  loading: boolean;
  saving: boolean;
  error: unknown;
  save: () => Promise<Note | null>;
  reload: () => void;
}

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
        setTags(n.tags.join(' '));
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

  const save = useCallback(async (): Promise<Note | null> => {
    if (!note) return null;
    setSaving(true);
    setError(null);
    try {
      const saved = await api.updateNote(note.id, { fields: values, tags: parseTags(tags) });
      setNote(saved);
      setValues(saved.fields);
      setTags(saved.tags.join(' '));
      return saved;
    } catch (err) {
      setError(err);
      return null;
    } finally {
      setSaving(false);
    }
  }, [note, values, tags]);

  const dirty =
    note !== null &&
    (Object.entries(values).some(([k, v]) => note.fields[k] !== v) || parseTags(tags).join(' ') !== note.tags.join(' '));

  return {
    note,
    notetype,
    fields,
    values,
    tags,
    setValue: (name, value) => setValues((prev) => ({ ...prev, [name]: value })),
    setTags,
    dirty,
    loading: noteId !== null && note === null && error === null,
    saving,
    error,
    save,
    reload: () => setAttempt((n) => n + 1),
  };
}
