/*
 * Conferma prima di eliminare un mazzo. Perché chiedere i conteggi al backend: l'albero
 * dei mazzi ha solo le carte in scadenza oggi, e «0 da studiare» non vuol dire mazzo vuoto.
 * Si elimina come in Anki desktop (sottomazzi e carte compresi); da qui non si annulla.
 */
import { useEffect, useState } from 'react';
import { Spinner } from '@anki-studio/ui-kit';
import { api } from '../api/client';
import type { DeckDeleteOut, DeckInfo, DeckNode } from '../api/types';
import { plural } from '../app/format';
import { ConfirmDialog } from '../hub/ConfirmDialog';

export function DeleteDeckDialog({
  deck,
  onDeleted,
  onClose,
}: {
  /** Il mazzo da eliminare; `null` = dialog chiuso. */
  deck: DeckNode | null;
  onDeleted: (deck: DeckNode, result: DeckDeleteOut) => void;
  onClose: () => void;
}) {
  const [info, setInfo] = useState<DeckInfo | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setInfo(null);
    setError(null);
    setBusy(false);
    if (!deck) return;
    let alive = true;
    api
      .deckInfo(deck.id)
      .then((i) => alive && setInfo(i))
      .catch((err: unknown) => alive && setError(err));
    return () => {
      alive = false;
    };
  }, [deck]);

  async function confirm() {
    if (!deck) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.deleteDeck(deck.id);
      onDeleted(deck, result);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  }

  const name = (info?.full_name ?? deck?.full_name ?? '').replaceAll('::', ' › ');
  const contents = info
    ? [
        info.subdecks > 0 ? plural(info.subdecks, 'sottomazzo', 'sottomazzi') : null,
        plural(info.cards, 'carta', 'carte'),
        `${plural(info.notes, 'nota', 'note')}`,
      ]
        .filter(Boolean)
        .join(' · ')
    : null;

  const description = !info
    ? undefined
    : info.filtered
      ? 'È un mazzo filtrato: eliminandolo le sue carte tornano ai mazzi d’origine, non si cancella nessuna carta.'
      : info.cards > 0 || info.subdecks > 0
        ? 'Cancelli definitivamente il mazzo, i suoi sottomazzi e tutte le loro carte con la cronologia dei ripassi. Non si può annullare da Anki Studio e, alla prossima sync, sparisce anche da AnkiWeb.'
        : 'Il mazzo è vuoto. Alla prossima sync sparisce anche da AnkiWeb.';

  return (
    <ConfirmDialog
      isOpen={deck !== null}
      title="Eliminare il mazzo?"
      description={description}
      confirmLabel={info && !info.filtered && info.cards > 0 ? `Elimina ${plural(info.cards, 'carta', 'carte')}` : 'Elimina il mazzo'}
      busy={busy}
      error={error}
      // Finché non si sa cosa c'è dentro non si conferma: è il punto del dialog.
      onConfirm={() => info && void confirm()}
      onClose={onClose}
    >
      <div className="rounded-md border bg-card px-3 py-2 text-sm">
        <div className="truncate font-medium">{name}</div>
        <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
          {contents ?? (error ? null : <Spinner className="size-3.5" />)}
        </div>
      </div>
    </ConfirmDialog>
  );
}
