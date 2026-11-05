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
  /** Nome completo del mazzo, es. "Lingue::Spagnolo::Verbi". */
  deck_name?: string | null;
  /** Cosa annullerebbe «Annulla», già tradotto (es. "Rispondi alla carta"); null = niente da annullare. */
  undo_label?: string | null;
}

export interface TypedAnswer {
  /** Retro della carta con il confronto colorato al posto di [[type:…]] (classi typeGood/typeBad/typeMissed). */
  answer_html: string;
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
  /** network = offline (riprova da sola), auth = serve un nuovo login, server = AnkiWeb ha rifiutato, refused = bloccata per non perdere dati. */
  error_kind?: 'network' | 'auth' | 'server' | 'refused' | 'other' | null;
}

export interface SyncProgress {
  kind: 'full_sync' | 'normal_sync';
  /** full_sync: byte trasferiti / totali (total = 0 finché non è noto). */
  transferred?: number | null;
  total?: number | null;
  /** normal_sync: testi già tradotti da Anki. */
  stage?: string | null;
  added?: string | null;
  removed?: string | null;
}

/*
 * I campi opzionali da `running` in giù arrivano con il consolidamento del backend
 * (sync in background): la PWA funziona anche con un backend che non li manda.
 */
export interface SyncStatus {
  logged_in: boolean;
  username: string | null;
  last_result: SyncResult | null;
  media: { active: boolean; checked?: string; added?: string; removed?: string; error: string | null };
  running?: 'normal' | 'full_upload' | 'full_download' | null;
  running_since?: number | null;
  progress?: SyncProgress | null;
  /** L'ultima sync ha trovato un conflitto: serve /sync/full (la sync automatica non lo risolve). */
  full_sync_required?: boolean;
  /** Server di sync configurato (null = AnkiWeb). */
  endpoint?: string | null;
  /** La chiave salvata è di un altro server: serve un nuovo login. */
  endpoint_mismatch?: boolean;
  next_auto_sync_at?: number | null;
  auto_sync_failures?: number;
}

export interface TodayStats {
  reviews: number;
  seconds: number;
  again: number;
  summary: string;
}
