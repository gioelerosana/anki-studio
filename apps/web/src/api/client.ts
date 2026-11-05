/*
 * Client dell'API. Stessa origine della PWA (/api): in sviluppo ci pensa il
 * proxy di Vite, in produzione lo stesso processo dell'API serve anche la PWA
 * (backend/app/web.py).
 */
import { getSettings } from '../settings';
import type {
  DeckNode,
  DeckOptions,
  NoteSearchResult,
  Stats,
  Note,
  Notetype,
  Rating,
  StudyState,
  SyncResult,
  SyncStatus,
  TodayStats,
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

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: 'same-origin',
    headers: {
      Authorization: `Bearer ${getSettings().apiToken}`,
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
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
  /** Imposta il cookie che permette a <img>/<audio> delle carte di caricare i media. */
  createSession: () => request<void>('POST', '/auth/session'),
  deleteSession: () => request<void>('DELETE', '/auth/session'),

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
};
