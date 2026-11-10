import { Button, Modal, Spinner } from '@anki-studio/ui-kit';
import { ErrorBanner } from '../hub/errors';
import { NoteFields, TagsInput } from './NoteFields';
import { useNoteEditor } from './useNoteEditor';

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
  const editor = useNoteEditor(noteId);

  async function save() {
    if (await editor.save()) onSaved();
  }

  return (
    <Modal
      isOpen={noteId !== null}
      onClose={onClose}
      title="Modifica nota"
      description={editor.notetype?.name}
      size="lg"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} className="coarse:h-10">
            Annulla
          </Button>
          <Button onClick={save} loading={editor.saving} disabled={!editor.canSave} className="coarse:h-10">
            Salva
          </Button>
        </>
      }
    >
      {editor.error ? <ErrorBanner error={editor.error} onRetry={editor.note ? undefined : editor.reload} className="mb-4" /> : null}
      {editor.note ? (
        <div className="flex flex-col gap-4">
          <NoteFields
            fields={editor.fields}
            values={editor.values}
            isCloze={editor.notetype?.is_cloze ?? false}
            onChange={editor.setValue}
          />
          <TagsInput value={editor.tags} onChange={editor.setTags} reserved={editor.reservedTags} typedReserved={editor.typedReserved} />
        </div>
      ) : editor.error ? null : (
        <div className="flex justify-center p-6 text-muted-foreground">
          <Spinner />
        </div>
      )}
    </Modal>
  );
}
