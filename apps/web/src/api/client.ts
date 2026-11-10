/*
 * Client dell'API. Stessa origine della PWA (/api): in sviluppo ci pensa il
 * proxy di Vite, in produzione lo stesso processo dell'API serve anche la PWA
 * (backend/app/web.py).
 *
 * Niente token: l'accesso è il cookie di sessione HttpOnly che il backend imposta
 * dopo il login su Authentik (app/auth.tsx). Un 401 vuol dire sessione scaduta.
 */
import type {
  ApiToken,
  ApiTokenCreated,
  AuthLogout,
  AuthUser,
  CardPreview,
  DeckNode,
  DeckOptions,
  DraftApproveResult,
  DraftDiscardResult,
  DraftList,
  HubSummary,
  MediaUpload,
  MediaUploadResult,
  NoteSearchResult,
  NoteTagsResult,
  Stats,
  Note,
  Notetype,
  Rating,
  StudyState,
  SyncResult,
  SyncStatus,
  TodayStats,
  TokenScope,
  TypedAnswer,
} from './types';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const unauthorizedListeners = new Set<() => void>();

/** Chiamato a ogni 401 dell'API: la sessione è scaduta o è stata chiusa. */
export function onUnauthorized(listener: () => void): () => void {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: 'same-origin',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) unauthorizedListeners.forEach((l) => l());
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = (await res.json()) as { detail?: unknown };
      if (typeof data.detail === 'string') detail = data.detail;
    } catch {
      // risposta non JSON
    }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  me: () => request<AuthUser>('GET', '/auth/me'),
  logout: () => request<AuthLogout>('POST', '/auth/logout'),

  decks: () => request<DeckNode[]>('GET', '/decks'),
  todayStats: () => request<TodayStats>('GET', '/stats/today'),

  study: (deckId: number) => request<StudyState>('GET', `/decks/${deckId}/study`),
  answer: (deckId: number, cardId: number, rating: Rating, timeTakenMs: number) =>
    request<StudyState>('POST', `/decks/${deckId}/study/answer`, {
      card_id: cardId,
      rating,
      time_taken_ms: timeTakenMs,
    }),
  undo: (deckId: number) => request<StudyState>('POST', `/decks/${deckId}/study/undo`),
  bury: (cardId: number) => request<void>('POST', `/cards/${cardId}/bury`),
  suspend: (cardId: number) => request<void>('POST', `/cards/${cardId}/suspend`),
  /** Come bury/suspend, ma risponde direttamente con la carta successiva del mazzo. */
  buryAndNext: (cardId: number, deckId: number) =>
    request<StudyState>('POST', `/cards/${cardId}/bury?deck_id=${deckId}`),
  suspendAndNext: (cardId: number, deckId: number) =>
    request<StudyState>('POST', `/cards/${cardId}/suspend?deck_id=${deckId}`),
  /** Confronta la risposta digitata ({{type:Campo}}) come Anki e restituisce il retro. */
  typeAnswer: (cardId: number, typed: string) =>
    request<TypedAnswer>('POST', `/cards/${cardId}/type-answer`, { typed }),
  flag: (cardId: number, flag: number) => request<void>('POST', `/cards/${cardId}/flag`, { flag }),

  notetypes: () => request<Notetype[]>('GET', '/notetypes'),
  createNote: (input: { deck_id: number; notetype_id: number; fields: Record<string, string>; tags?: string[] }) =>
    request<Note>('POST', '/notes', input),
  note: (id: number) => request<Note>('GET', `/notes/${id}`),
  updateNote: (id: number, patch: { fields?: Record<string, string>; tags?: string[] }) =>
    request<Note>('PATCH', `/notes/${id}`, patch),

  /** Ricerca con la sintassi di Anki (`deck:… tag:… is:due`), dalla nota modificata più di recente. */
  searchNotes: (q: string, limit = 50, offset = 0) =>
    request<NoteSearchResult>(
      'GET',
      `/search/notes?${new URLSearchParams({ q, limit: String(limit), offset: String(offset) })}`,
    ),
  tags: () => request<string[]>('GET', '/tags'),
  stats: (deckId?: number, days = 30) =>
    request<Stats>(
      'GET',
      `/stats?${new URLSearchParams({ days: String(days), ...(deckId !== undefined ? { deck_id: String(deckId) } : {}) })}`,
    ),
  deckOptions: (deckId: number) => request<DeckOptions>('GET', `/decks/${deckId}/options`),
  /** "Studia altre N carte oggi" sul mazzo; risponde con la carta successiva. */
  extendLimits: (deckId: number, extra: { new?: number; review?: number }) =>
    request<StudyState>('POST', `/decks/${deckId}/extend-limits`, extra),

  syncStatus: () => request<SyncStatus>('GET', '/sync'),
  syncLogin: (username: string, password: string) => request<void>('POST', '/sync/login', { username, password }),
  syncLogout: () => request<void>('POST', '/sync/logout'),
  sync: () => request<SyncResult>('POST', '/sync'),
  fullSync: (direction: 'upload' | 'download') => request<SyncResult>('POST', '/sync/full', { direction }),

  /* ---- hub: bozze degli agenti, libreria, token (docs/PIANO-HUB.md) ---- */
  hubSummary: () => request<HubSummary>('GET', '/hub/summary'),
  drafts: (limit = 50, offset = 0) =>
    request<DraftList>('GET', `/hub/drafts?${new URLSearchParams({ limit: String(limit), offset: String(offset) })}`),
  /** `expectedMod`: id nota → `modified` visto; le note cambiate nel frattempo vengono saltate (`skipped_ids`). */
  approveDrafts: (noteIds: number[], expectedMod?: Record<number, number>) =>
    request<DraftApproveResult>('POST', '/hub/drafts/approve', { note_ids: noteIds, expected_mod: expectedMod }),
  /** Cancella le bozze scelte (solo quelle: mai note normali). Chiedi sempre conferma prima. */
  discardDrafts: (noteIds: number[], expectedMod?: Record<number, number>) =>
    request<DraftDiscardResult>('POST', '/hub/drafts/discard', { note_ids: noteIds, expected_mod: expectedMod }),
  cardPreview: (cardId: number) => request<CardPreview>('GET', `/cards/${cardId}/preview`),
  moveNote: (id: number, deckId: number) => request<Note>('POST', `/notes/${id}/move`, { deck_id: deckId }),
  /** Cancella la nota con le sue carte. Solo dalla sessione della PWA; chiedi sempre conferma. */
  deleteNote: (id: number) => request<void>('DELETE', `/notes/${id}`),
  editNoteTags: (noteIds: number[], change: { add?: string[]; remove?: string[] }) =>
    request<NoteTagsResult>('POST', '/notes/tags', { note_ids: noteIds, add: change.add ?? [], remove: change.remove ?? [] }),

  /** Carica un'immagine, un audio o un video breve nei media della collezione (base64, max 10 MB). */
  uploadMedia: (file: MediaUpload) => request<MediaUploadResult>('POST', '/media', file),

  /** Token per gli agenti (solo dalla sessione). Il token in chiaro si vede alla creazione e basta. */
  tokens: () => request<ApiToken[]>('GET', '/tokens'),
  createToken: (input: { name: string; scope?: TokenScope; review?: boolean }) =>
    request<ApiTokenCreated>('POST', '/tokens', input),
  updateToken: (id: string, patch: { scope?: TokenScope; review?: boolean }) =>
    request<ApiToken>('PATCH', `/tokens/${id}`, patch),
  deleteToken: (id: string) => request<void>('DELETE', `/tokens/${id}`),
};
