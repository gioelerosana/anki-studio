/*
 * Azioni su più note, una alla volta.
 *
 * Perché in sequenza e non in parallelo: la collezione è una sola, protetta da un lock, e un
 * gesto dell'utente su 30 note non deve diventare 30 richieste insieme (né un'ondata di 503
 * durante una sync). Se il backend dice "occupato", "non permesso" o "sessione scaduta" si
 * smette subito: le altre note andrebbero incontro allo stesso errore.
 */
import { ApiError } from '../api/client';

export interface BulkResult {
  done: number;
  failed: number;
  /** Primo errore incontrato (per il messaggio). */
  error: unknown;
}

export async function runEach(
  ids: number[],
  action: (id: number) => Promise<unknown>,
  onProgress?: (done: number, total: number) => void,
): Promise<BulkResult> {
  let done = 0;
  let failed = 0;
  let error: unknown = null;
  for (const id of ids) {
    try {
      await action(id);
      done += 1;
    } catch (err) {
      failed += 1;
      error ??= err;
      if (err instanceof ApiError && [401, 403, 503].includes(err.status)) {
        failed += ids.length - done - failed;
        break;
      }
    }
    onProgress?.(done + failed, ids.length);
  }
  return { done, failed, error };
}
