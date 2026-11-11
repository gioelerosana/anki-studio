/*
 * Tag riservati dell'hub: li scrive solo il backend (`is_reserved` in hub.py).
 * `agent::…` dice chi ha creato la nota, `ext::…` da quale fonte (idempotenza dell'invio):
 * se l'utente li togliesse o ne inventasse uno da un campo di testo, una nota si farebbe
 * passare per di un agente o romperebbe l'idempotenza. Il backend li rifiuta (422); la UI
 * li mostra bloccati prima che si provi.
 */
const RESERVED = /^(?:agent|ext)::/i;

export const isReservedTag = (tag: string) => RESERVED.test(tag);
