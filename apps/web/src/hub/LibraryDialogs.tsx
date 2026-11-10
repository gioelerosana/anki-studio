/*
 * Dialog delle azioni della libreria: sposta, tag in blocco, cancella.
 * Valgono per una nota o per una selezione: cambia solo il conteggio nei testi.
 */
import { useEffect, useState } from 'react';
import { Banner, Button, Field, Input, Modal, Select } from '@anki-studio/ui-kit';
import type { DeckNode } from '../api/types';
import { plural } from '../app/format';
import { parseTags } from '../notes/NoteFields';
import { describeError } from './errors';
import { ConfirmDialog } from './ConfirmDialog';

const noteCount = (n: number) => plural(n, 'nota', 'note');

export function MoveDialog({
  isOpen,
  count,
  decks,
  busy,
  error,
  onConfirm,
  onClose,
}: {
  isOpen: boolean;
  count: number;
  decks: DeckNode[];
  busy: boolean;
  error: unknown;
  onConfirm: (deckId: number) => void;
  onClose: () => void;
}) {
  const [deckId, setDeckId] = useState(0);
  useEffect(() => {
    if (isOpen) setDeckId((prev) => (decks.some((d) => d.id === prev) ? prev : (decks[0]?.id ?? 0)));
  }, [isOpen, decks]);

  return (
    <Modal
      isOpen={isOpen}
      onClose={busy ? () => {} : onClose}
      title="Sposta in un altro mazzo"
      description={`${noteCount(count)}: tutte le loro carte vanno nel mazzo scelto.`}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy} className="coarse:h-10">
            Annulla
          </Button>
          <Button loading={busy} disabled={!deckId} onClick={() => onConfirm(deckId)} className="coarse:h-10">
            Sposta
          </Button>
        </>
      }
    >
      {error ? (
        <Banner variant="error" className="mb-3">
          {describeError(error).message}
        </Banner>
      ) : null}
      <Field label="Mazzo di destinazione">
        <Select
          size="lg"
          value={String(deckId)}
          onChange={(e) => setDeckId(Number(e.target.value))}
          options={decks.map((d) => ({ value: String(d.id), label: d.full_name.replaceAll('::', ' › ') }))}
          selectClassName="coarse:text-base"
        />
      </Field>
    </Modal>
  );
}

export function TagsDialog({
  isOpen,
  count,
  suggestions,
  busy,
  error,
  onConfirm,
  onClose,
}: {
  isOpen: boolean;
  count: number;
  suggestions: string[];
  busy: boolean;
  error: unknown;
  onConfirm: (change: { add: string[]; remove: string[] }) => void;
  onClose: () => void;
}) {
  const [add, setAdd] = useState('');
  const [remove, setRemove] = useState('');
  useEffect(() => {
    if (isOpen) {
      setAdd('');
      setRemove('');
    }
  }, [isOpen]);

  const toAdd = parseTags(add);
  const toRemove = parseTags(remove);
  // hub::bozza lega il tag alle carte sospese: toglierlo da qui lascerebbe carte sospese senza
  // più comparire nell'Inbox. Si approva o si scarta da lì.
  const touchesDraft = [...toAdd, ...toRemove].some((t) => t.toLowerCase() === 'hub::bozza');

  return (
    <Modal
      isOpen={isOpen}
      onClose={busy ? () => {} : onClose}
      title="Tag in blocco"
      description={`Si applicano a ${noteCount(count)}. Più tag separati da spazi.`}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy} className="coarse:h-10">
            Annulla
          </Button>
          <Button
            loading={busy}
            disabled={(toAdd.length === 0 && toRemove.length === 0) || touchesDraft}
            onClick={() => onConfirm({ add: toAdd, remove: toRemove })}
            className="coarse:h-10"
          >
            Applica
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {error ? <Banner variant="error">{describeError(error).message}</Banner> : null}
        {touchesDraft ? <Banner variant="warning">Il tag hub::bozza si gestisce dall’Inbox: lì si approva o si scarta.</Banner> : null}
        <datalist id="library-tag-suggestions">
          {suggestions.map((t) => (
            <option key={t} value={t} />
          ))}
        </datalist>
        <Field label="Aggiungi">
          <Input value={add} onChange={(e) => setAdd(e.target.value)} list="library-tag-suggestions" size="lg" autoCapitalize="none" autoCorrect="off" spellCheck={false} inputClassName="coarse:text-base" />
        </Field>
        <Field label="Togli">
          <Input value={remove} onChange={(e) => setRemove(e.target.value)} list="library-tag-suggestions" size="lg" autoCapitalize="none" autoCorrect="off" spellCheck={false} inputClassName="coarse:text-base" />
        </Field>
      </div>
    </Modal>
  );
}

export function DeleteNotesDialog({
  isOpen,
  titles,
  count,
  busy,
  progress,
  error,
  onConfirm,
  onClose,
}: {
  isOpen: boolean;
  /** Primi titoli, per far riconoscere cosa si sta cancellando. */
  titles: string[];
  count: number;
  busy: boolean;
  progress: string | null;
  error: unknown;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const more = count - titles.length;
  return (
    <ConfirmDialog
      isOpen={isOpen}
      title={count === 1 ? 'Cancellare la nota?' : `Cancellare ${count} note?`}
      description={`Cancelli definitivamente ${noteCount(count)} con tutte le loro carte e la cronologia dei ripassi. Non si può annullare da Anki Studio e, alla prossima sync, sparisce anche da AnkiWeb.`}
      confirmLabel={count === 1 ? 'Cancella la nota' : `Cancella ${noteCount(count)}`}
      busy={busy}
      error={error}
      onConfirm={onConfirm}
      onClose={onClose}
    >
      <ul className="flex flex-col gap-1 text-sm">
        {titles.map((t, i) => (
          <li key={i} className="truncate rounded-md border bg-card px-2 py-1">
            {t || '(senza testo)'}
          </li>
        ))}
        {more > 0 ? <li className="px-1 text-xs text-muted-foreground">e altre {more}</li> : null}
      </ul>
      {progress ? <p className="mt-3 text-xs text-muted-foreground">{progress}</p> : null}
    </ConfirmDialog>
  );
}
