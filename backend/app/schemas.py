from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


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


class DeckInfo(BaseModel):
    """Cosa contiene un mazzo, per la conferma prima di eliminarlo. I conteggi comprendono i
    sottomazzi; per un mazzo filtrato sono le carte che, eliminandolo, tornano nel mazzo d'origine."""

    id: int
    full_name: str
    filtered: bool
    subdecks: int
    cards: int
    notes: int


class DeckDeleteOut(BaseModel):
    # carte cancellate davvero (0 per un mazzo filtrato: le carte tornano al loro mazzo)
    deleted_cards: int
    # il mazzo e i suoi sottomazzi
    deleted_decks: int


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


# ---- telecomando (app/remote.py) ---------------------------------------------

# Limiti dell'albero dei mazzi nello stato dello schermo: arriva a ogni cambio di vista e il
# relay lo tiene in memoria e lo rimanda a ogni telefono. Una collezione vera ne ha qualche
# decina; il tetto impedisce a un client sbagliato (o al ponte di un'altra installazione) di
# far crescere la memoria del server.
REMOTE_MAX_DECKS = 2000
REMOTE_MAX_DECK_DEPTH = 32


class RemoteDeck(BaseModel):
    """Un mazzo nell'elenco che lo schermo manda al telefono: solo ciò che serve a disegnarlo.
    `name` è l'ultimo pezzo del nome (`Verbi`, non `Spagnolo::Verbi`), come `DeckNode.name`."""

    id: int
    name: str = Field(max_length=1000)
    counts: Counts
    children: list["RemoteDeck"] = Field(default_factory=list, max_length=REMOTE_MAX_DECKS)


def _deck_tree_size(nodes: list[RemoteDeck], depth: int = 1) -> int:
    if depth > REMOTE_MAX_DECK_DEPTH:
        raise ValueError(f"albero dei mazzi più profondo di {REMOTE_MAX_DECK_DEPTH} livelli")
    return sum(1 + _deck_tree_size(n.children, depth + 1) for n in nodes)


class RemoteScreenState(BaseModel):
    """Cosa mostra lo schermo (la PWA aperta sul computer): il telefono lo usa per
    disegnare i pulsanti. Niente contenuto della carta: il telefono è solo un telecomando.

    `view`: `decks` = elenco dei mazzi (il telefono può sceglierne uno), `study` = studio
    (tutti gli altri campi), `other` = un'altra schermata (aggiungi, impostazioni: il
    telefono non la cambia, si perderebbe quello che si sta scrivendo)."""

    view: Literal["decks", "study", "other"] = "study"
    deck_id: int | None = None
    deck_name: str = Field(default="", max_length=1000)
    done: bool = False
    card_id: int | None = None
    revealed: bool = False
    queue: Literal["new", "learning", "review"] | None = None
    counts: Counts | None = None
    # come StudyCard.button_labels: [Di nuovo, Difficile, Bene, Facile]
    button_labels: list[str] = Field(default_factory=list, max_length=4)
    has_audio: bool = False
    # la pagina non ha ancora ricevuto un clic: il browser blocca audio e voce, e il
    # telefono chiede di fare un clic sul computer
    audio_blocked: bool = False
    # flag della carta mostrata (0 = nessuno), per il menu del telefono
    flag: int = Field(default=0, ge=0, le=7)
    can_undo: bool = False
    # una risposta è in viaggio verso il backend: i pulsanti vanno disattivati
    busy: bool = False
    # da dove studia lo schermo, per il sottotitolo del telefono: la PWA in un browser o
    # l'app desktop (che arriva al server attraverso il ponte, app/remote_bridge.py)
    source: Literal["browser", "desktop"] = "browser"
    # solo con `view == "decks"`: i mazzi come li vede lo schermo. Il telefono li preferisce a
    # /api/decks del server, che per l'app desktop (copia locale) può essere indietro: dopo
    # una sync gli id coincidono, i conteggi no. Senza (schermi di versioni vecchie), /api/decks.
    decks: list[RemoteDeck] | None = Field(default=None, max_length=REMOTE_MAX_DECKS)

    @field_validator("decks")
    @classmethod
    def _decks_limit(cls, v: list[RemoteDeck] | None) -> list[RemoteDeck] | None:
        if v is not None and _deck_tree_size(v) > REMOTE_MAX_DECKS:
            raise ValueError(f"più di {REMOTE_MAX_DECKS} mazzi")
        return v


class RemoteCommand(BaseModel):
    """Un tasto premuto sul telefono. `card_id` evita che un doppio tocco valuti la
    carta successiva: lo schermo esegue il comando solo se la carta è ancora quella."""

    action: Literal[
        "reveal", "answer", "undo", "replay", "bury", "suspend", "flag", "open_deck", "close"
    ]
    rating: Literal[1, 2, 3, 4] | None = None
    # solo per "flag": 1–7, 0 = togli (lo stesso flag di nuovo lo toglie, come sul computer)
    flag: int | None = Field(default=None, ge=0, le=7)
    card_id: int | None = None
    # solo per "open_deck": il mazzo da aprire sullo schermo ("close" torna ai mazzi)
    deck_id: int | None = None


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
    # solo nella risposta di `PATCH /notes/{id}` (e di `update_note` via MCP) quando la modifica ha
    # cambiato davvero qualcosa: l'id dell'operazione nel diario, da dare a `undo`. Altrove è null.
    operation_id: str | None = None


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


class DeckPreset(BaseModel):
    """Un preset di opzioni con i campi che la PWA sa modificare: servono tutti per
    passare il mazzo a un altro preset senza un'altra richiesta."""

    id: int
    name: str
    # quanti mazzi lo usano: con più di uno, cambiarlo cambia anche gli altri
    use_count: int
    new_per_day: int
    reviews_per_day: int
    learn_steps_min: list[float]
    relearn_steps_min: list[float]
    max_answer_seconds: int
    bury_new_siblings: bool
    bury_review_siblings: bool
    desired_retention: float


class DeckLimits(BaseModel):
    """Limiti propri del mazzo, sopra quelli del preset (le schede «Questo mazzo» e «Solo
    oggi» di Anki desktop). `None` = si usa il limite del preset."""

    new: int | None = None
    review: int | None = None
    new_today: int | None = None
    review_today: int | None = None


class DeckOptions(BaseModel):
    deck_id: int
    deck_name: str
    filtered: bool
    preset_id: int | None = None
    preset_name: str | None = None
    presets: list[DeckPreset] = []
    new_per_day: int | None = None
    reviews_per_day: int | None = None
    deck_limits: DeckLimits = DeckLimits()
    learn_steps_min: list[float] = []
    relearn_steps_min: list[float] = []
    max_answer_seconds: int | None = None
    bury_new_siblings: bool = False
    bury_review_siblings: bool = False
    # opzioni della collezione, non del preset: valgono per tutti i mazzi
    new_cards_ignore_review_limit: bool = False
    apply_all_parent_limits: bool = False
    fsrs: bool = False
    desired_retention: float | None = None


# Passi in minuti, come in Anki: da un secondo a un anno, al massimo 20.
_Step = Annotated[float, Field(gt=0, le=525_600)]
_PerDay = Annotated[int, Field(ge=0, le=9999)]


class DeckOptionsIn(BaseModel):
    """Salvataggio delle opzioni (PUT /api/decks/{id}/options). Il mazzo passa al preset
    `preset_id` e i campi del preset si scrivono lì: se lo usano altri mazzi, cambiano anche
    per loro. I limiti di `deck_limits` restano solo di questo mazzo."""

    preset_id: int
    new_per_day: _PerDay
    reviews_per_day: _PerDay
    deck_limits: DeckLimits = DeckLimits()
    learn_steps_min: list[_Step] = Field(default_factory=list, max_length=20)
    relearn_steps_min: list[_Step] = Field(default_factory=list, max_length=20)
    max_answer_seconds: int = Field(60, ge=1, le=7200)
    bury_new_siblings: bool = False
    bury_review_siblings: bool = False
    new_cards_ignore_review_limit: bool = False
    apply_all_parent_limits: bool = False
    # considerata solo con FSRS attivo
    desired_retention: float | None = Field(None, ge=0.7, le=0.99)

    @field_validator("deck_limits")
    @classmethod
    def _limits_in_range(cls, v: DeckLimits) -> DeckLimits:
        for n in (v.new, v.review, v.new_today, v.review_today):
            if n is not None and not 0 <= n <= 9999:
                raise ValueError("I limiti vanno da 0 a 9999")
        return v


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


# ---- hub: creazione da agenti, libreria, diario e annullamento, token (docs/PIANO-HUB.md) --------
#
# Contratto condiviso tra REST (app/routers/hub.py), server MCP (app/mcp_server.py) e PWA.
# Se cambi qualcosa qui, aggiorna apps/web/src/api/types.ts.


class HubNoteIn(BaseModel):
    # nome completo ("Lingue::Spagnolo") o id numerico
    deck: str | int
    # nome del tipo di nota ("Basic", "Cloze") o id numerico
    notetype: str | int
    fields: dict[str, str]
    tags: list[str] = []
    # id scelto dall'agente per rendere l'invio ripetibile: diventa il tag `ext::<id>`.
    # Se esiste già una nota con quel tag viene aggiornata (o lasciata com'è) invece di duplicarla.
    # Solo lettere, cifre e `. _ : -`: finisce in un tag di Anki e in una ricerca, e un carattere
    # speciale (spazio, `*`, `\`, `"`) cambierebbe cosa trova.
    external_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._:-]{1,200}$")


class HubBatchIn(BaseModel):
    notes: list[HubNoteIn] = Field(min_length=1, max_length=100)
    # niente viene scritto: restituisce solo cosa succederebbe
    dry_run: bool = False
    # crea i mazzi che non esistono (altrimenti la nota è un errore)
    create_missing_decks: bool = False


class HubNoteResult(BaseModel):
    index: int
    # unchanged: external_id già presente con gli stessi campi; duplicate: stesso primo campo
    # senza external_id (note_id punta a quella esistente)
    status: Literal["created", "updated", "unchanged", "duplicate", "error"]
    note_id: int | None = None
    card_ids: list[int] = []
    error: str | None = None


class HubBatchOut(BaseModel):
    dry_run: bool
    created: int
    updated: int
    unchanged: int
    duplicates: int
    errors: int
    results: list[HubNoteResult]
    # l'operazione nel diario (`GET /hub/operations`), da dare a `undo`; null se non è stato
    # scritto niente (dry_run, tutto unchanged/duplicate/error)
    operation_id: str | None = None


class HubDeckIn(BaseModel):
    # nome completo, es. "Lingue::Spagnolo::Verbi"
    name: str = Field(min_length=1, max_length=500)


class HubDeckOut(BaseModel):
    id: int
    name: str
    # False se esisteva già (la rotta è idempotente)
    created: bool
    # se il mazzo è stato creato: l'operazione nel diario, da dare a `undo`
    operation_id: str | None = None


OperationKind = Literal["add_notes", "update_note", "create_deck"]


class OperationOut(BaseModel):
    """Una voce del diario delle operazioni degli agenti (`app/journal.py`)."""

    id: str
    # secondi epoch
    created_at: int
    # slug del token che l'ha fatta ("claude"), oppure "sessione" / "admin"
    agent: str
    kind: OperationKind
    summary: str
    # note create o aggiornate dall'operazione
    note_count: int
    # applied: niente annullato; partial: annullata in parte (si può ritentare); undone: tutta
    status: Literal["applied", "partial", "undone"]
    undone_at: int | None = None


class OperationList(BaseModel):
    # dalla più recente
    operations: list[OperationOut]


class UndoSkip(BaseModel):
    # null per un elemento che non è una nota (un mazzo)
    note_id: int | None = None
    reason: str


class UndoOut(BaseModel):
    operation_id: str
    status: Literal["undone", "partial"]
    # note riportate a come erano prima
    restored: int
    # note create e cancellate, più i mazzi eliminati
    deleted: int
    skipped: list[UndoSkip] = []


class NoteMoveIn(BaseModel):
    deck_id: int


class NoteTagsIn(BaseModel):
    note_ids: list[int] = Field(min_length=1, max_length=500)
    add: list[str] = []
    remove: list[str] = []


class NoteTagsOut(BaseModel):
    updated: int


class CardPreview(BaseModel):
    """Una carta mostrata fuori dallo studio (libreria): come StudyCard, senza
    pulsanti e senza coda, quindi vale anche per le carte sospese."""

    card_id: int
    note_id: int
    deck_id: int
    deck_name: str
    question_html: str
    answer_html: str
    css: str
    card_class: str
    question_av: list[AvItem]
    answer_av: list[AvItem]
    flag: int
    suspended: bool


class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    # read: solo letture; write: legge e crea/modifica note (mai cancella, mai sync completa);
    # remote: solo il telecomando, come schermo (l'app desktop attraverso il ponte): nessuna
    # rotta REST, niente /mcp
    scope: Literal["read", "write", "remote"] = "write"


class TokenUpdate(BaseModel):
    scope: Literal["read", "write", "remote"] | None = None


class TokenOut(BaseModel):
    id: str
    name: str
    scope: Literal["read", "write", "remote"]
    # secondi epoch
    created_at: int
    last_used_at: int | None = None


class TokenCreated(TokenOut):
    # il token in chiaro, mostrato UNA volta sola: sul server resta solo l'hash
    token: str


class MediaIn(BaseModel):
    # nome desiderato (Anki può cambiarlo se esiste già un file diverso con lo stesso nome)
    filename: str = Field(min_length=1, max_length=200)
    data_base64: str


class MediaOut(BaseModel):
    # nome da usare nei campi: `<img src="…">` o `[sound:…]`
    filename: str


# ---- ponte del telecomando (solo app desktop, app/remote_bridge.py) ------------------


class RemoteBridgeIn(BaseModel):
    """La configurazione del ponte dall'app desktop. `token` None = tieni quello salvato
    (la PWA non lo rilegge mai: sa solo se c'è)."""

    server_url: str = Field(min_length=1, max_length=500)
    token: str | None = Field(default=None, min_length=8, max_length=200)
    enabled: bool = True


class RemoteBridgeStatus(BaseModel):
    server_url: str | None = None
    token_set: bool = False
    enabled: bool = False
    # off = scollegato o non configurato; connecting = primo tentativo; connected;
    # retrying = caduto o rifiutato, riprova da solo (vedi `last_error` e `retry_at`)
    status: Literal["off", "connecting", "connected", "retrying"] = "off"
    last_error: str | None = None
    # secondi epoch
    connected_at: int | None = None
    retry_at: int | None = None
    # telefoni collegati al server come telecomando, quando il ponte è su
    remotes: int = 0
