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

/* ---- telecomando (backend/app/remote.py, WebSocket /api/remote) ---- */

/**
 * Cosa mostra lo schermo (la PWA sul computer): il telefono lo usa per disegnare i pulsanti.
 * `view`: `decks` = elenco dei mazzi (il telefono ne apre uno), `study` = studio (tutti gli
 * altri campi), `other` = un'altra schermata, che il telefono non cambia.
 */
export interface RemoteScreenState {
  view: 'decks' | 'study' | 'other';
  deck_id: number | null;
  deck_name: string;
  done: boolean;
  card_id: number | null;
  revealed: boolean;
  queue: StudyCard['queue'] | null;
  counts: Counts | null;
  /** Come StudyCard.button_labels: [Di nuovo, Difficile, Bene, Facile]. */
  button_labels: string[];
  has_audio: boolean;
  /** La pagina non ha ancora ricevuto un clic: il browser blocca audio e voce. */
  audio_blocked: boolean;
  /** Flag della carta mostrata, 0 = nessuno. */
  flag: number;
  can_undo: boolean;
  /** Una risposta è in viaggio verso il backend. */
  busy: boolean;
}

/** Un tasto premuto sul telefono. `card_id`: lo schermo lo esegue solo se la carta è ancora quella. */
export interface RemoteCommand {
  action: 'reveal' | 'answer' | 'undo' | 'replay' | 'bury' | 'suspend' | 'flag' | 'open_deck' | 'close';
  rating?: Rating | null;
  /** Solo per `flag`: 1–7, 0 = togli (lo stesso flag di nuovo lo toglie). */
  flag?: number | null;
  card_id?: number | null;
  /** Solo per `open_deck`: il mazzo da aprire sullo schermo (`close` torna ai mazzi). */
  deck_id?: number | null;
}

/** Dal server: `state` al telefono, `command` e `remotes` alla schermata di studio. */
export type RemoteServerMessage =
  | { type: 'state'; screen: RemoteScreenState | null }
  | { type: 'command'; command: RemoteCommand }
  | { type: 'remotes'; count: number }
  | { type: 'pong' };

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
  /** Solo nella risposta di `PATCH /notes/{id}` quando la modifica di un agente ha cambiato qualcosa: id dell'operazione annullabile. */
  operation_id?: string | null;
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

export interface NoteSearchItem {
  id: number;
  notetype_id: number;
  notetype_name: string;
  /** Campo di ordinamento senza HTML (di solito il primo campo). */
  sort_field: string;
  tags: string[];
  card_ids: number[];
  /** Mazzo della prima carta della nota. */
  deck_name: string | null;
  /** Ultima modifica, secondi epoch. */
  modified: number;
}

export interface NoteSearchResult {
  total: number;
  offset: number;
  notes: NoteSearchItem[];
}

export interface CardCounts {
  new: number;
  learning: number;
  /** In ripasso con intervallo < 21 giorni. */
  young: number;
  /** In ripasso con intervallo ≥ 21 giorni. */
  mature: number;
  suspended: number;
  buried: number;
  total: number;
}

export interface Stats {
  cards: CardCounts;
  /** Un elemento per giorno, dal più vecchio a oggi (`day` 0 = oggi, -1 = ieri…). */
  reviews: { day: number; reviews: number; again: number; seconds: number }[];
  /** Quota di ripassi con risposta diversa da "Di nuovo" nel periodo; null se non ce ne sono. */
  retention: number | null;
  /** Carte da ripassare nei prossimi 7 giorni (`day` 0 = oggi, scadute comprese). */
  forecast: { day: number; due: number }[];
  generated_at: number;
}

export interface DeckOptions {
  deck_id: number;
  deck_name: string;
  filtered: boolean;
  preset_id: number | null;
  preset_name: string | null;
  new_per_day: number | null;
  reviews_per_day: number | null;
  learn_steps_min: number[];
  relearn_steps_min: number[];
  max_answer_seconds: number | null;
  bury_new_siblings: boolean;
  bury_review_siblings: boolean;
  fsrs: boolean;
  desired_retention: number | null;
}

/** Utente della sessione (GET /api/auth/me, specchio di `AuthUser`). */
export interface AuthUser {
  name: string;
  username: string | null;
}

export interface AuthLogout {
  /** End-session di Authentik: ci si naviga per chiudere anche quella sessione. */
  logout_url: string | null;
}

/* ---- hub: creazione da agenti, libreria, token, diario delle operazioni (specchio di schemas.py, docs/PIANO-HUB.md) ---- */

export interface HubNoteResult {
  index: number;
  /** `unchanged`: external_id già presente con gli stessi campi; `duplicate`: stesso primo campo senza external_id. */
  status: 'created' | 'updated' | 'unchanged' | 'duplicate' | 'error';
  note_id: number | null;
  card_ids: number[];
  error: string | null;
}

/** Esito di `POST /hub/notes/batch` (la PWA non lo chiama: lo usano gli agenti, qui per specchio). */
export interface HubBatchOut {
  dry_run: boolean;
  created: number;
  updated: number;
  unchanged: number;
  duplicates: number;
  errors: number;
  results: HubNoteResult[];
  /** Id dell'operazione annullabile nel diario; `null` se non è stato scritto niente (dry run, tutte in errore). */
  operation_id: string | null;
}

export type OperationKind = 'add_notes' | 'update_note' | 'create_deck';
/** `applied` = da annullare; `partial` = annullata in parte (si può riprovare); `undone` = annullata del tutto. */
export type OperationStatus = 'applied' | 'partial' | 'undone';

/** Una riga del diario delle operazioni degli agenti (`GET /hub/operations`). */
export interface OperationOut {
  id: string;
  /** Secondi epoch. */
  created_at: number;
  /** Nome dell'agente (slug del token). */
  agent: string;
  kind: OperationKind;
  /** Riepilogo già scritto dal backend, es. «3 note aggiunte in Lingue::Spagnolo». */
  summary: string;
  note_count: number;
  status: OperationStatus;
  /** Secondi epoch dell'ultimo annullamento, `null` se mai annullata. */
  undone_at: number | null;
}

export interface OperationList {
  operations: OperationOut[];
}

export interface UndoSkipped {
  note_id: number | null;
  /** Motivo in italiano (nota modificata o studiata dopo l'operazione, già cancellata…). */
  reason: string;
}

/** Esito di `POST /hub/operations/{id}/undo`. */
export interface UndoOut {
  operation_id: string;
  status: 'undone' | 'partial';
  /** Note tornate com'erano prima di una modifica. */
  restored: number;
  /** Note create dall'operazione e ora cancellate. */
  deleted: number;
  skipped: UndoSkipped[];
}

export interface NoteTagsResult {
  updated: number;
}

/** Una carta fuori dallo studio (libreria): vale anche per le carte sospese. */
export interface CardPreview {
  card_id: number;
  note_id: number;
  deck_id: number;
  deck_name: string;
  question_html: string;
  answer_html: string;
  css: string;
  card_class: string;
  question_av: AvItem[];
  answer_av: AvItem[];
  flag: number;
  suspended: boolean;
}

export type TokenScope = 'read' | 'write';

export interface ApiToken {
  id: string;
  name: string;
  scope: TokenScope;
  /** Secondi epoch. */
  created_at: number;
  last_used_at: number | null;
}

/** Risposta alla creazione: `token` si vede UNA volta sola. */
export interface ApiTokenCreated extends ApiToken {
  token: string;
}

/** Un file da caricare nella cartella media (max 10 MB decodificati; immagini, audio, mp4/webm). */
export interface MediaUpload {
  /** Nome desiderato: il backend lo sanifica e Anki può cambiarlo se esiste già un file diverso. */
  filename: string;
  /** Solo il base64, senza il prefisso `data:…;base64,`. */
  data_base64: string;
}

export interface MediaUploadResult {
  /** Nome da usare nei campi: `<img src="…">` o `[sound:…]`. */
  filename: string;
}
