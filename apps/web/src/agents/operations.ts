/*
 * Logica pura del diario delle operazioni degli agenti: testi e regole che non dipendono da
 * React né dalla rete, così si provano con `pnpm --filter @anki-studio/web test` (vitest).
 */
import type { OperationOut, UndoOut } from '../api/types';

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** Si può (ri)provare ad annullare finché l'operazione non è `undone`. */
export const canUndo = (op: Pick<OperationOut, 'status'>) => op.status !== 'undone';

/** «Riprova» per un annullamento riuscito solo in parte, «Annulla» altrimenti. */
export const undoLabel = (op: Pick<OperationOut, 'status'>) => (op.status === 'partial' ? 'Riprova' : 'Annulla');

/** Etichetta della tinta di stato; `null` per un'operazione ancora applicata (nessun badge). */
export function statusLabel(status: OperationOut['status']): string | null {
  if (status === 'undone') return 'Annullata';
  if (status === 'partial') return 'Parziale';
  return null;
}

/**
 * Cosa succede annullando, per il dialog di conferma. Le note create si cancellano (non si
 * recuperano), quelle modificate tornano com'erano; quelle toccate o studiate dopo restano.
 */
export function undoExplanation(kind: OperationOut['kind']): string[] {
  const guard = 'Le note che nel frattempo hai modificato o studiato non vengono toccate: restano dove sono e te le segnalo.';
  switch (kind) {
    case 'add_notes':
      return ['Le note create da questa operazione vengono cancellate, con le loro carte.', guard];
    case 'update_note':
      return ['La nota modificata torna com’era prima della modifica.', guard];
    case 'create_deck':
      return ['Il mazzo creato viene rimosso se è ancora vuoto.', guard];
  }
}

export interface UndoReport {
  tone: 'success' | 'warning';
  title: string;
  /** Una riga per cosa è successo: ripristinate, cancellate, saltate (raggruppate per motivo). */
  lines: string[];
  /** Una riga sola per il toast. */
  short: string;
}

/** Raggruppa i saltati per motivo, nell'ordine in cui compaiono, così «20 note» non fa 20 righe. */
function groupSkipped(skipped: UndoOut['skipped']): { reason: string; n: number }[] {
  const groups = new Map<string, number>();
  for (const s of skipped) groups.set(s.reason, (groups.get(s.reason) ?? 0) + 1);
  return [...groups].map(([reason, n]) => ({ reason, n }));
}

/** L'esito di un annullamento, pronto da mostrare. */
export function summarizeUndo(out: UndoOut): UndoReport {
  const lines: string[] = [];
  if (out.restored > 0) lines.push(`${count(out.restored, 'nota ripristinata', 'note ripristinate')}.`);
  if (out.deleted > 0) lines.push(`${count(out.deleted, 'nota cancellata', 'note cancellate')}.`);
  if (out.restored === 0 && out.deleted === 0) lines.push('Nessuna nota è cambiata.');
  for (const { reason, n } of groupSkipped(out.skipped)) {
    lines.push(`${n === 1 ? 'Saltata' : `Saltate ${n}`}: ${reason}`);
  }

  const partial = out.status === 'partial';
  const bits = [
    out.restored > 0 ? count(out.restored, 'ripristinata', 'ripristinate') : '',
    out.deleted > 0 ? count(out.deleted, 'cancellata', 'cancellate') : '',
    out.skipped.length > 0 ? count(out.skipped.length, 'saltata', 'saltate') : '',
  ].filter(Boolean);
  const detail = bits.length > 0 ? bits.join(', ') : 'nessuna nota cambiata';
  return {
    tone: partial ? 'warning' : 'success',
    title: partial ? 'Annullata in parte' : 'Operazione annullata',
    lines,
    short: `${partial ? 'Annullata in parte' : 'Annullata'}: ${detail}`,
  };
}
