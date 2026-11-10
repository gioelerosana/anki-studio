/*
 * Tag riservati dell'hub: li scrive solo il backend (`is_reserved` in hub.py).
 * `hub::bozza` lega la nota alle carte sospese dell'Inbox, `agent::…` e `ext::…` dicono chi
 * l'ha creata e da quale fonte: se l'utente li togliesse o ne inventasse uno da un campo di
 * testo, una bozza resterebbe sospesa fuori dall'Inbox o una nota si farebbe passare per
 * di un agente. Il backend li rifiuta (422); la UI li mostra bloccati prima che si provi.
 */
const RESERVED = /^(?:agent|ext|hub)::/i;

export const isReservedTag = (tag: string) => RESERVED.test(tag);
