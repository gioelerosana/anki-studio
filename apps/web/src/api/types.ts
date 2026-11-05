/*
 * Tipi dell'API del backend. Specchio di backend/app/schemas.py:
 * se cambi uno, aggiorna l'altro (contratto documentato in backend/README.md).
 */

export interface Counts {
  new: number;
  learning: number;
  review: number;
}

export interface DeckNode {
  id: number;
  name: string;
  full_name: string;
  level: number;
  collapsed: boolean;
  counts: Counts;
  children: DeckNode[];
}

export interface AvItem {
  type: 'sound' | 'tts';
  url?: string | null;
  text?: string | null;
  lang?: string | null;
  speed?: number | null;
}

export interface StudyCard {
  card_id: number;
  note_id: number;
  deck_id: number;
  queue: 'new' | 'learning' | 'review';
  question_html: string;
  answer_html: string;
  css: string;
  card_class: string;
  question_av: AvItem[];
  answer_av: AvItem[];
  autoplay: boolean;
  /** Intervalli dei 4 pulsanti: [Di nuovo, Difficile, Bene, Facile]. */
  button_labels: string[];
  flag: number;
  tags: string[];
}

export interface StudyState {
  done: boolean;
  counts: Counts;
  card: StudyCard | null;
}

export type Rating = 1 | 2 | 3 | 4;

export interface NotetypeField {
  name: string;
  ord: number;
}

export interface Notetype {
  id: number;
  name: string;
  is_cloze: boolean;
  fields: NotetypeField[];
}

export interface Note {
  id: number;
  notetype_id: number;
  fields: Record<string, string>;
  tags: string[];
  card_ids: number[];
}

export interface SyncResult {
  outcome:
    | 'no_changes'
    | 'synced'
    | 'full_download'
    | 'full_upload'
    | 'full_sync_required'
    | 'not_logged_in'
    | 'error';
  finished_at: number;
  server_message: string;
  error: string | null;
}

export interface SyncStatus {
  logged_in: boolean;
  username: string | null;
  last_result: SyncResult | null;
  media: { active: boolean; checked?: string; added?: string; removed?: string; error: string | null };
}

export interface TodayStats {
  reviews: number;
  seconds: number;
  again: number;
  summary: string;
}
