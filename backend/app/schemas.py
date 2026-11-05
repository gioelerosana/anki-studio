from typing import Literal

from pydantic import BaseModel, Field


class Counts(BaseModel):
    new: int
    learning: int
    review: int


class DeckNode(BaseModel):
    id: int
    name: str
    full_name: str
    level: int
    collapsed: bool
    counts: Counts
    children: list["DeckNode"] = []


class AvItem(BaseModel):
    type: Literal["sound", "tts"]
    url: str | None = None
    text: str | None = None
    lang: str | None = None
    speed: float | None = None


class StudyCard(BaseModel):
    card_id: int
    note_id: int
    deck_id: int
    queue: Literal["new", "learning", "review"]
    question_html: str
    answer_html: str
    css: str
    card_class: str
    question_av: list[AvItem]
    answer_av: list[AvItem]
    autoplay: bool
    # etichette dei 4 pulsanti: [Di nuovo, Difficile, Bene, Facile] es. ["<1m", "6m", "10m", "4g"]
    button_labels: list[str]
    flag: int
    tags: list[str]


class StudyState(BaseModel):
    done: bool
    counts: Counts
    card: StudyCard | None = None
    # nome completo del mazzo che si sta studiando, es. "Lingue::Spagnolo::Verbi"
    deck_name: str | None = None
    # cosa annullerebbe «Annulla» (già tradotto, es. "Rispondi alla carta"); null = niente
    undo_label: str | None = None


class TypedAnswerIn(BaseModel):
    typed: str = Field(max_length=10_000)


class TypedAnswerOut(BaseModel):
    answer_html: str


class AnswerIn(BaseModel):
    card_id: int
    rating: Literal[1, 2, 3, 4] = Field(description="1=Di nuovo 2=Difficile 3=Bene 4=Facile")
    time_taken_ms: int = Field(ge=0, le=60 * 60 * 1000)


class FlagIn(BaseModel):
    flag: int = Field(ge=0, le=7)


class NotetypeField(BaseModel):
    name: str
    ord: int


class Notetype(BaseModel):
    id: int
    name: str
    is_cloze: bool
    fields: list[NotetypeField]


class NoteIn(BaseModel):
    deck_id: int
    notetype_id: int
    fields: dict[str, str]
    tags: list[str] = []


class NoteUpdate(BaseModel):
    fields: dict[str, str] | None = None
    tags: list[str] | None = None


class NoteOut(BaseModel):
    id: int
    notetype_id: int
    fields: dict[str, str]
    tags: list[str]
    card_ids: list[int]


class LoginIn(BaseModel):
    username: str
    password: str


class FullSyncIn(BaseModel):
    direction: Literal["upload", "download"]


class SyncResultOut(BaseModel):
    outcome: Literal[
        "no_changes",
        "synced",
        "full_download",
        "full_upload",
        "full_sync_required",
        "not_logged_in",
        "error",
    ]
    finished_at: float
    server_message: str = ""
    error: str | None = None
    # network = offline/timeout (si riprova da sola), auth = serve un nuovo login,
    # server = AnkiWeb ha rifiutato, refused = bloccata per non perdere dati
    error_kind: Literal["network", "auth", "server", "refused", "other"] | None = None


class SyncProgress(BaseModel):
    kind: Literal["full_sync", "normal_sync"]
    # full_sync: byte trasferiti / totali (total può essere 0 finché non è noto)
    transferred: int | None = None
    total: int | None = None
    # normal_sync: testi già tradotti da Anki
    stage: str | None = None
    added: str | None = None
    removed: str | None = None


class SyncStatusOut(BaseModel):
    logged_in: bool
    username: str | None
    last_result: SyncResultOut | None
    media: dict
    # sync in corso: "normal", "full_upload", "full_download" oppure null
    running: Literal["normal", "full_upload", "full_download"] | None = None
    running_since: float | None = None
    progress: SyncProgress | None = None
    # l'ultima sync ha trovato un conflitto: serve /sync/full (la sync automatica non lo risolve)
    full_sync_required: bool = False
    # server di sync configurato (null = AnkiWeb)
    endpoint: str | None = None
    # la chiave salvata è di un altro server: serve un nuovo login
    endpoint_mismatch: bool = False
    next_auto_sync_at: float | None = None
    auto_sync_failures: int = 0


class TodayStats(BaseModel):
    reviews: int
    seconds: int
    again: int
    summary: str


class NoteSearchItem(BaseModel):
    id: int
    notetype_id: int
    notetype_name: str
    # campo di ordinamento senza HTML (di solito il primo campo)
    sort_field: str
    tags: list[str]
    card_ids: list[int]
    # mazzo della prima carta della nota
    deck_name: str | None
    # ultima modifica, secondi epoch
    modified: int


class NoteSearchOut(BaseModel):
    total: int
    offset: int
    notes: list[NoteSearchItem]


class CardCounts(BaseModel):
    new: int
    learning: int
    # in ripasso con intervallo < 21 giorni / >= 21 giorni (come le statistiche di Anki)
    young: int
    mature: int
    suspended: int
    buried: int
    total: int


class DayReviews(BaseModel):
    # 0 = oggi, -1 = ieri, … (giorni di Anki: rispettano l'ora del cambio giorno)
    day: int
    reviews: int
    again: int
    seconds: int


class DayForecast(BaseModel):
    # 0 = oggi (comprese le scadute), 1 = domani, …
    day: int
    due: int


class StatsOut(BaseModel):
    cards: CardCounts
    reviews: list[DayReviews]
    # quota di ripassi (non nuove né apprendimento) con risposta diversa da "Di nuovo"
    retention: float | None
    forecast: list[DayForecast]
    generated_at: float


class DeckOptions(BaseModel):
    deck_id: int
    deck_name: str
    filtered: bool
    preset_id: int | None = None
    preset_name: str | None = None
    new_per_day: int | None = None
    reviews_per_day: int | None = None
    learn_steps_min: list[float] = []
    relearn_steps_min: list[float] = []
    max_answer_seconds: int | None = None
    bury_new_siblings: bool = False
    bury_review_siblings: bool = False
    fsrs: bool = False
    desired_retention: float | None = None


class ExtendLimitsIn(BaseModel):
    # carte in più per oggi (anche negative per toglierne)
    new: int = Field(0, ge=-9999, le=9999)
    review: int = Field(0, ge=-9999, le=9999)


class AuthUser(BaseModel):
    """Utente della sessione (GET /api/auth/me)."""

    name: str
    username: str | None = None


class AuthLogout(BaseModel):
    # end-session di Authentik: la PWA ci naviga per chiudere anche quella sessione
    logout_url: str | None = None
