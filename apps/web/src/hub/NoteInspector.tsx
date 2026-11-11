/*
 * Dettaglio di una nota: anteprima della carta e modifica di campi e tag.
 *
 * Lo usa la libreria (colonna a destra o foglio). Due schede, «Anteprima» e «Modifica»,
 * invece di impilarle: su iPad in verticale la carta e il form insieme non stanno nello
 * schermo, e chi controlla una nota vuole prima vedere la carta com'è.
 * Il salvataggio ricarica l'anteprima e avvisa il chiamante, che aggiorna l'elenco.
 */
import { useEffect, useState, type ReactNode } from 'react';
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
  onSaved,
  onDirtyChange,
}: {
  noteId: number;
  cardIds: number[];
  /** Titolo e metadati sopra le schede. */
  header?: ReactNode;
  /** Azioni sulla nota (sposta, cancella…) sotto le schede. */
  actions?: ReactNode;
  onSaved: (note: Note) => void;
  onDirtyChange?: (dirty: boolean) => void;
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

  async function save() {
    const saved = await editor.save();
    if (!saved) return;
    setReloadKey((k) => k + 1);
    setTab('preview');
    onSaved(saved);
  }

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
                <Button loading={editor.saving} disabled={!editor.canSave} onClick={() => void save()} className="coarse:h-10">
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
