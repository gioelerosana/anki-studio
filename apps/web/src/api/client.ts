/*
 * Client dell'API. Stessa origine della PWA (/api): in sviluppo ci pensa il
 * proxy di Vite, in produzione nginx (apps/web/nginx.conf).
 */
import { getSettings } from '../settings';
import type {
  DeckNode,
  Note,
  Notetype,
  Rating,
  StudyState,
  SyncResult,
  SyncStatus,
  TodayStats,
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
  flag: (cardId: number, flag: number) => request<void>('POST', `/cards/${cardId}/flag`, { flag }),

  notetypes: () => request<Notetype[]>('GET', '/notetypes'),
  createNote: (input: { deck_id: number; notetype_id: number; fields: Record<string, string>; tags?: string[] }) =>
    request<Note>('POST', '/notes', input),
  note: (id: number) => request<Note>('GET', `/notes/${id}`),
  updateNote: (id: number, patch: { fields?: Record<string, string>; tags?: string[] }) =>
    request<Note>('PATCH', `/notes/${id}`, patch),

  syncStatus: () => request<SyncStatus>('GET', '/sync'),
  syncLogin: (username: string, password: string) => request<void>('POST', '/sync/login', { username, password }),
  syncLogout: () => request<void>('POST', '/sync/logout'),
  sync: () => request<SyncResult>('POST', '/sync'),
  fullSync: (direction: 'upload' | 'download') => request<SyncResult>('POST', '/sync/full', { direction }),
};
