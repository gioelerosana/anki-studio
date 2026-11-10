/*
 * Dettaglio di una nota: anteprima della carta e modifica di campi e tag.
 *
 * Lo usano la libreria (colonna a destra o foglio) e l'inbox. Due schede, «Anteprima» e
 * «Modifica», invece di impilarle: su iPad in verticale la carta e il form insieme non
 * stanno nello schermo, e chi controlla una bozza vuole prima vedere la carta com'è.
 * Il salvataggio ricarica l'anteprima e avvisa il chiamante, che aggiorna l'elenco.
 */
import { useEffect, useState, type MutableRefObject, type ReactNode } from 'react';
import { Button, SegmentedControl } from '@anki-studio/ui-kit';
import type { Note } from '../api/types';
import { NoteFields, TagsInput } from '../notes/NoteFields';
import { useNoteEditor } from '../notes/useNoteEditor';
import { CardPreviewPane } from './CardPreviewPane';
import { ErrorBanner } from './errors';

type Tab = 'preview' | 'edit';

const TABS: { id: Tab; label: string }[] = [
  { id: 'preview', label: 'Anteprima' },
  { id: 'edit', label: 'Modifica' },
];

export function NoteInspector({
  noteId,
  cardIds,
  header,
  actions,
  saveIsPrimary = true,
  onSaved,
  onDirtyChange,
  saveHandle,
}: {
  noteId: number;
  cardIds: number[];
  /** Titolo e metadati sopra le schede. */
  header?: ReactNode;
  /** Azioni sulla nota (sposta, cancella, approva…) sotto le schede. */
  actions?: ReactNode;
  /** `false` quando la vista ha già il suo pulsante primario (inbox: «Approva»). */
  saveIsPrimary?: boolean;
  onSaved: (note: Note) => void;
  onDirtyChange?: (dirty: boolean) => void;
  /**
   * Il chiamante può far salvare l'editor da fuori (inbox: «Salva e approva»). Vale `null` se la
   * nota non è ancora caricata o non c'è nulla da salvare; risponde con la nota salvata o `null`
   * se il salvataggio è fallito (l'errore resta visibile nell'editor).
   */
  saveHandle?: MutableRefObject<(() => Promise<Note | null>) | null>;
}) {
  const editor = useNoteEditor(noteId);
  const [tab, setTab] = useState<Tab>('preview');
  const [cardIndex, setCardIndex] = useState(0);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    onDirtyChange?.(editor.dirty);
  }, [editor.dirty, onDirtyChange]);
  // chi chiude il pannello non deve restare con «modifiche non salvate» di una nota che non c'è più
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);

  const cardId = cardIds[Math.min(cardIndex, cardIds.length - 1)];

  async function save(): Promise<Note | null> {
    const saved = await editor.save();
    if (!saved) {
      // chi salva da fuori non vede il form: porta l'utente dove c'è l'errore
      setTab('edit');
      return null;
    }
    setReloadKey((k) => k + 1);
    setTab('preview');
    onSaved(saved);
    return saved;
  }

  useEffect(() => {
    if (!saveHandle) return;
    saveHandle.current = editor.note && editor.canSave ? save : null;
    return () => {
      saveHandle.current = null;
    };
  });

  return (
    <div className="flex flex-col gap-4">
      {header}
      <SegmentedControl items={TABS} activeId={tab} onChange={setTab} aria-label="Dettaglio della nota" className="self-start" />

      {tab === 'preview' ? (
        <div className="flex flex-col gap-3">
          {cardIds.length > 1 ? (
            <SegmentedControl
              size="sm"
              items={cardIds.map((id, i) => ({ id: String(i), label: `Carta ${i + 1}` }))}
              activeId={String(cardIndex)}
              onChange={(i) => setCardIndex(Number(i))}
              aria-label="Carta della nota"
              className="self-start"
            />
          ) : null}
          {cardId !== undefined ? <CardPreviewPane cardId={cardId} reloadKey={reloadKey} /> : <p className="text-sm text-muted-foreground">Nessuna carta per questa nota.</p>}
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          {editor.error ? <ErrorBanner error={editor.error} onRetry={editor.note ? undefined : editor.reload} /> : null}
          {editor.note ? (
            <>
              <NoteFields fields={editor.fields} values={editor.values} isCloze={editor.notetype?.is_cloze ?? false} onChange={editor.setValue} />
              <TagsInput value={editor.tags} onChange={editor.setTags} reserved={editor.reservedTags} typedReserved={editor.typedReserved} />
              <div className="flex justify-end">
                <Button variant={saveIsPrimary ? 'default' : 'outline'} loading={editor.saving} disabled={!editor.canSave} onClick={() => void save()} className="coarse:h-10">
                  Salva modifiche
                </Button>
              </div>
            </>
          ) : editor.error ? null : (
            <p className="text-sm text-muted-foreground">Caricamento…</p>
          )}
        </div>
      )}

      {actions}
    </div>
  );
}
