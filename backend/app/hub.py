"""Livello di servizio dell'hub delle flashcard (docs/PIANO-HUB.md): creazione di note da
agenti, bozze, mazzi, anteprime e operazioni in blocco.

Niente FastAPI qui: le funzioni prendono la collezione già bloccata (`manager.use()`) e
lanciano `HubError`, così le riusano sia le rotte REST sia il futuro server MCP.
Lo scheduling resta quello di Anki: qui si creano note, si sospendono carte, si spostano.

Concetti (stessi del piano):

- **Provenienza**: le note create da un token hanno il tag `agent::<slug>`.
- **Idempotenza**: `external_id` diventa il tag `ext::<id>`; rimandare la stessa nota la
  aggiorna (o la lascia com'è) invece di duplicarla. Il tag viaggia con la sync.
- **Bozze**: carte sospese + tag `hub::bozza`. Si approvano o si scartano dalla PWA.
- **Una batch = una operazione annullabile**: tutte le scritture stanno sotto un'unica
  voce di undo (`add_custom_undo_entry` + `merge_undo_entries`).
"""

from __future__ import annotations

import base64
import binascii
import logging
import re
import unicodedata
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Literal

from anki.cards import Card
from anki.collection import Collection, SearchNode
from anki.errors import NotFoundError
from anki.notes import Note, NoteFieldsCheckResult
from anki.utils import field_checksum, strip_html_media

from .rendering import render_card
from .schemas import (
    CardPreview,
    DraftList,
    DraftNote,
    HubBatchIn,
    HubBatchOut,
    HubDeckOut,
    HubNoteIn,
    HubNoteResult,
    HubSummary,
    MediaOut,
)

log = logging.getLogger(__name__)

DRAFT_TAG = "hub::bozza"
AGENT_PREFIX = "agent::"
EXT_PREFIX = "ext::"
# I tag riservati li mette solo l'hub: un agente non deve poter scrivere la provenienza
# di un altro, togliere lo stato di bozza o prendersi l'`external_id` di un'altra nota
RESERVED_PREFIXES = (AGENT_PREFIX, EXT_PREFIX, "hub::")

# Etichette delle voci di undo. Lo studio non deve proporle come "Annulla" (vedi
# routers/study.py): chi sta ripassando non vuole cancellare per sbaglio le note di un agente.
UNDO_BATCH = "Aggiungi note da agente"
UNDO_APPROVE = "Approva bozze"
UNDO_TAGS = "Modifica i tag"
UNDO_LABELS = {UNDO_BATCH, UNDO_APPROVE, UNDO_TAGS}

_SUSPENDED = -1


class HubError(Exception):
    """Errore da riportare a chi chiama; `kind` lo traduce in 404 / 422 / 413 nelle rotte."""

    kind: Literal["not_found", "invalid", "too_large"] = "invalid"


class NotFound(HubError):
    kind = "not_found"


class TooLarge(HubError):
    kind = "too_large"


# ---- tag -----------------------------------------------------------------------------


def clean_tags(tags: list[str]) -> list[str]:
    """Tag validi per Anki: niente spazi dentro (li spezzerebbero in due tag), niente
    vuoti né doppioni (i tag di Anki non distinguono maiuscole e minuscole)."""
    out: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        tag = "_".join(tag.split())
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            out.append(tag)
    return out


def is_reserved(tag: str) -> bool:
    return tag.casefold().startswith(RESERVED_PREFIXES)


def user_tags(tags: list[str]) -> list[str]:
    """I tag scelti da chi scrive, senza quelli riservati."""
    return [t for t in clean_tags(tags) if not is_reserved(t)]


def has_tag(tags: list[str], wanted: str) -> bool:
    return wanted.casefold() in {t.casefold() for t in tags}


def agent_tag(agent: str) -> str:
    return AGENT_PREFIX + agent


def is_own_note(tags: list[str], agent: str) -> bool:
    return has_tag(tags, agent_tag(agent))


def merge_agent_tags(existing: list[str], incoming: list[str]) -> list[str]:
    """I tag di una nota dopo una modifica fatta da un token: i suoi tag normali sostituiscono
    quelli vecchi, ma i riservati restano com'erano (non può togliere `hub::bozza`, cambiare
    la provenienza o l'`external_id`) e quelli che prova ad aggiungere si ignorano."""
    return [t for t in existing if is_reserved(t)] + user_tags(incoming)


def effective_draft(requested: bool | None, *, review: bool) -> bool:
    """Un token con `review` ha sempre bozze; gli altri scelgono (default: note normali)."""
    return True if review else bool(requested)


# ---- mazzi ---------------------------------------------------------------------------


def normalize_deck_name(name: str) -> str:
    parts = [p.strip() for p in name.strip().split("::")]
    if not all(parts):
        raise HubError("Nome del mazzo non valido (parti vuote)")
    return "::".join(parts)


def create_deck(col: Collection, name: str) -> HubDeckOut:
    """Idempotente: se il mazzo esiste lo restituisce, `created=False`."""
    name = normalize_deck_name(name)
    existing = col.decks.id_for_name(name)
    if existing:
        return HubDeckOut(id=existing, name=col.decks.name(existing), created=False)
    try:
        did = col.decks.add_normal_deck_with_name(name).id
    except Exception as e:  # noqa: BLE001 - il backend spiega perché (es. genitore filtrato)
        raise HubError(f"Impossibile creare il mazzo: {e}") from None
    return HubDeckOut(id=did, name=col.decks.name(did), created=True)


# ---- creazione in batch --------------------------------------------------------------

_CHECK_ERRORS = {
    NoteFieldsCheckResult.EMPTY: "Il primo campo è vuoto",
    NoteFieldsCheckResult.MISSING_CLOZE: "Manca una cloze ({{c1::...}})",
    NoteFieldsCheckResult.NOTETYPE_NOT_CLOZE: "Questo tipo di nota non supporta le cloze",
    NoteFieldsCheckResult.FIELD_NOT_CLOZE: "Cloze in un campo che non la supporta",
}


@dataclass
class _Item:
    """Cosa fare per una nota della batch, deciso prima di scrivere qualsiasi cosa:
    così `dry_run` e la scrittura vera seguono la stessa strada."""

    index: int
    status: Literal["created", "updated", "unchanged", "duplicate", "error"]
    error: str | None = None
    note: Note | None = None  # da creare (nuova) o da aggiornare (già nella collezione)
    deck: int | str | None = None  # id del mazzo, o nome di un mazzo da creare
    note_id: int | None = None
    card_ids: list[int] = field(default_factory=list)
    dup_of: int | None = None  # indice di una nota della stessa batch


def _error(index: int, message: str) -> _Item:
    return _Item(index, "error", error=message)


def _resolve_notetype(col: Collection, spec: str | int):
    if isinstance(spec, str):
        model = col.models.by_name(spec.strip())
        if model is not None:
            return model
        if not spec.strip().isdigit():
            return None
        spec = int(spec)
    return col.models.get(spec)


def _resolve_deck(
    col: Collection, spec: str | int, create_missing: bool
) -> int | str:
    """L'id di un mazzo esistente, o il nome (normalizzato) di uno da creare."""
    if isinstance(spec, str):
        name = normalize_deck_name(spec)
        did = col.decks.id_for_name(name)
        if did is None and name.isdigit():
            spec = int(name)  # un id passato come testo
        elif did is None:
            if create_missing:
                return name
            raise HubError(f"Il mazzo «{name}» non esiste (usa create_missing_decks)")
        else:
            spec = did
    deck = col.decks.get(spec, default=False)
    if deck is None:
        raise HubError(f"Mazzo con id {spec} non trovato")
    if deck.get("dyn"):
        raise HubError("Non si possono aggiungere note a un mazzo filtrato")
    return int(deck["id"])


def _find_by_ext(col: Collection, ext_tag: str, agent: str | None) -> Note | None:
    """La nota con quel tag `ext::`. Un token vede solo le proprie: due agenti possono
    usare lo stesso `external_id` senza pestarsi i piedi."""
    ids = col.find_notes(col.build_search_string(SearchNode(tag=ext_tag)))
    for nid in sorted(ids):
        note = col.get_note(nid)
        # `tag:ext::x` trova anche i figli (`ext::x::y`): si controlla il tag intero
        if not has_tag(note.tags, ext_tag):
            continue
        if agent is None or is_own_note(note.tags, agent):
            return note
    return None


def _first_field_key(text: str) -> str:
    return strip_html_media(text)


def _find_duplicate_id(col: Collection, mid: int, first_field: str) -> int | None:
    """L'id della nota con lo stesso primo campo e tipo (il controllo dei duplicati di Anki)."""
    key = _first_field_key(first_field)
    for nid, flds in col.db.execute(
        "select id, flds from notes where mid = ? and csum = ?", mid, field_checksum(first_field)
    ):
        if _first_field_key(flds.split("\x1f")[0]) == key:
            return nid
    return None


def _check_message(note: Note, *, allow_duplicate: bool) -> str | None:
    result = note.fields_check()
    if result == NoteFieldsCheckResult.NORMAL:
        return None
    if result == NoteFieldsCheckResult.DUPLICATE and allow_duplicate:
        return None
    return _CHECK_ERRORS.get(result, "Nota non valida")


def _plan_note(
    col: Collection,
    index: int,
    spec: HubNoteIn,
    *,
    batch: HubBatchIn,
    agent: str | None,
    draft: bool,
    seen_ext: set[str],
    seen_first: dict[tuple[int, str], int],
) -> _Item:
    model = _resolve_notetype(col, spec.notetype)
    if model is None:
        return _error(index, f"Tipo di nota «{spec.notetype}» non trovato")
    mid = int(model["id"])
    field_names = {f["name"] for f in model["flds"]}
    unknown = sorted(set(spec.fields) - field_names)
    if unknown:
        return _error(index, f"Campi inesistenti per «{model['name']}»: {unknown}")

    wanted_tags = user_tags(spec.tags)
    ext_tag = EXT_PREFIX + spec.external_id if spec.external_id else None

    if ext_tag is not None:
        if ext_tag.casefold() in seen_ext:
            return _error(index, "external_id ripetuto nella stessa batch")
        seen_ext.add(ext_tag.casefold())
        existing = _find_by_ext(col, ext_tag, agent)
        if existing is not None:
            return _plan_update(index, existing, mid, spec, wanted_tags)

    try:
        deck = _resolve_deck(col, spec.deck, batch.create_missing_decks)
    except HubError as e:
        return _error(index, str(e))

    note = col.new_note(model)
    for name, value in spec.fields.items():
        note[name] = value
    tags = list(wanted_tags)
    if agent:
        tags.append(agent_tag(agent))
    if ext_tag:
        tags.append(ext_tag)
    if draft:
        tags.append(DRAFT_TAG)
    note.tags = tags

    message = _check_message(note, allow_duplicate=True)
    if message:
        return _error(index, message)

    if ext_tag is None:
        # senza external_id il primo campo è l'unica identità che abbiamo
        first = note.fields[0]
        key = (mid, _first_field_key(first))
        if key in seen_first:
            return _Item(index, "duplicate", dup_of=seen_first[key])
        if note.fields_check() == NoteFieldsCheckResult.DUPLICATE:
            return _Item(
                index, "duplicate", note_id=_find_duplicate_id(col, mid, first)
            )
        seen_first[key] = index
    return _Item(index, "created", note=note, deck=deck)


def _plan_update(
    index: int, existing: Note, mid: int, spec: HubNoteIn, wanted_tags: list[str]
) -> _Item:
    """`external_id` già presente: si aggiornano i campi passati e si aggiungono i tag
    nuovi (non si tolgono: li può aver messi l'utente). Mazzo e bozza non si toccano:
    la nota potrebbe essere stata spostata o approvata nel frattempo."""
    if existing.mid != mid:
        return _error(index, "external_id già usato da una nota di un altro tipo")
    changed = {k: v for k, v in spec.fields.items() if existing[k] != v}
    new_tags = [t for t in wanted_tags if not has_tag(existing.tags, t)]
    card_ids = [int(c) for c in existing.card_ids()]
    if not changed and not new_tags:
        return _Item(index, "unchanged", note_id=existing.id, card_ids=card_ids)
    for k, v in changed.items():
        existing[k] = v
    existing.tags = [*existing.tags, *new_tags]
    message = _check_message(existing, allow_duplicate=True)
    if message:
        return _error(index, message)
    return _Item(index, "updated", note=existing, note_id=existing.id, card_ids=card_ids)


def create_batch(
    col: Collection, body: HubBatchIn, *, agent: str | None = None, review: bool = False
) -> HubBatchOut:
    """Crea (o aggiorna) fino a 100 note. Ogni nota ha il suo esito: un errore non ferma
    le altre. `agent` è lo slug del token (provenienza), `review` il suo flag: se vero le
    note sono sempre bozze. Con `dry_run` non si scrive niente."""
    draft = effective_draft(body.draft, review=review)

    seen_ext: set[str] = set()
    seen_first: dict[tuple[int, str], int] = {}
    items = [
        _plan_note(
            col, i, spec, batch=body, agent=agent, draft=draft, seen_ext=seen_ext, seen_first=seen_first
        )
        for i, spec in enumerate(body.notes)
    ]

    if not body.dry_run and any(it.status in ("created", "updated") for it in items):
        _apply(col, items, draft=draft)

    # il duplicato di una nota della stessa batch punta all'id che ha avuto davvero
    for it in items:
        if it.status == "duplicate" and it.dup_of is not None:
            it.note_id = items[it.dup_of].note_id

    results = [
        HubNoteResult(
            index=it.index,
            status=it.status,
            note_id=it.note_id,
            card_ids=it.card_ids,
            error=it.error,
        )
        for it in items
    ]
    count = lambda s: sum(1 for r in results if r.status == s)  # noqa: E731
    return HubBatchOut(
        dry_run=body.dry_run,
        draft=draft,
        created=count("created"),
        updated=count("updated"),
        unchanged=count("unchanged"),
        duplicates=count("duplicate"),
        errors=count("error"),
        results=results,
    )


def _apply(col: Collection, items: list[_Item], *, draft: bool) -> None:
    """Scrive tutto sotto un'unica voce di undo. Una nota alla volta (`add_note`, non
    `add_notes`): le note successive vedono quelle appena create e un errore del backend
    su una nota (es. mazzo non creabile) diventa il suo esito, senza perdere le altre.

    Anki tiene solo 30 passi di undo: dopo ogni scrittura si fonde il passo nella voce
    iniziale, altrimenti con più di ~28 note la voce cadrebbe dalla pila e la fusione
    finale fallirebbe ("target undo op not found")."""
    target = col.add_custom_undo_entry(UNDO_BATCH)
    new_decks: dict[str, int] = {}
    for it in items:
        if it.note is None:
            continue
        try:
            if it.status == "created":
                did = it.deck
                if isinstance(did, str):
                    if did not in new_decks:
                        new_decks[did] = col.decks.add_normal_deck_with_name(did).id
                        col.merge_undo_entries(target)
                    did = new_decks[did]
                col.add_note(it.note, did)  # type: ignore[arg-type]
                col.merge_undo_entries(target)
                cards = [int(c) for c in it.note.card_ids()]
                if draft:
                    col.sched.suspend_cards(cards)
                    col.merge_undo_entries(target)
                it.note_id, it.card_ids = it.note.id, cards
            else:
                col.update_note(it.note)
                col.merge_undo_entries(target)
        except Exception as e:  # noqa: BLE001 - l'esito è per nota, la batch continua
            log.warning("Nota della batch non scritta: %s", e)
            it.status, it.error, it.note_id, it.card_ids = "error", str(e), None, []
            with suppress(Exception):
                col.merge_undo_entries(target)


# ---- bozze ---------------------------------------------------------------------------


def _ids_sql(ids) -> str:
    return "(" + ",".join(str(int(i)) for i in ids) + ")"


def draft_ids(col: Collection) -> list[int]:
    """Le note in bozza, dalla più recente. Il tag è confrontato per intero (con gli spazi
    attorno, come li salva Anki): `hub::bozza::x` non è una bozza."""
    return list(
        col.db.list("select id from notes where tags like '% hub::bozza %' order by mod desc, id desc")
    )


def summary(col: Collection) -> HubSummary:
    return HubSummary(
        drafts=col.db.scalar("select count() from notes where tags like '% hub::bozza %'")
    )


def first_deck_name(col: Collection, nid: int) -> str | None:
    row = col.db.first("select did, odid from cards where nid = ? order by ord limit 1", nid)
    if not row:
        return None
    did, odid = row
    return col.decks.name(odid or did)


def _agent_of(tags: list[str]) -> str | None:
    for t in tags:
        if t.casefold().startswith(AGENT_PREFIX):
            return t[len(AGENT_PREFIX):]
    return None


def list_drafts(col: Collection, limit: int, offset: int) -> DraftList:
    ids = draft_ids(col)
    notes: list[DraftNote] = []
    for nid in ids[offset : offset + limit]:
        note = col.get_note(nid)
        notes.append(
            DraftNote(
                id=note.id,
                notetype_id=note.mid,
                notetype_name=note.note_type()["name"],
                fields=dict(note.items()),
                tags=list(note.tags),
                deck_name=first_deck_name(col, nid),
                card_ids=[int(c) for c in note.card_ids()],
                agent=_agent_of(note.tags),
                created=nid // 1000,
            )
        )
    return DraftList(total=len(ids), notes=notes)


def approve_drafts(col: Collection, note_ids: list[int]) -> int:
    """Bozza → nota normale: carte riattivate e tag tolto. Gli id che non sono bozze si
    ignorano. Un'unica voce di undo."""
    drafts = set(draft_ids(col))
    ids = [i for i in dict.fromkeys(note_ids) if i in drafts]
    if not ids:
        return 0
    target = col.add_custom_undo_entry(UNDO_APPROVE)
    try:
        cards = col.db.list(
            f"select id from cards where nid in {_ids_sql(ids)} and queue = {_SUSPENDED}"
        )
        if cards:
            col.sched.unsuspend_cards(cards)
        col.tags.bulk_remove(ids, DRAFT_TAG)
    finally:
        col.merge_undo_entries(target)
    return len(ids)


def discard_drafts(col: Collection, note_ids: list[int]) -> int:
    """Cancella SOLO note con `hub::bozza`: niente altro si può scartare da qui
    (regola 1: nessun dato perso senza una scelta esplicita)."""
    drafts = set(draft_ids(col))
    ids = [i for i in dict.fromkeys(note_ids) if i in drafts]
    if ids:
        col.remove_notes(ids)
    return len(ids)


# ---- anteprima, spostamento, cancellazione, tag --------------------------------------


def get_note(col: Collection, note_id: int) -> Note:
    try:
        return col.get_note(note_id)  # type: ignore[arg-type]
    except NotFoundError:
        raise NotFound("Nota non trovata") from None


def card_preview(col: Collection, card_id: int) -> CardPreview:
    """La carta com'è, fuori dalla coda di studio: funziona anche per le sospese."""
    try:
        card: Card = col.get_card(card_id)  # type: ignore[arg-type]
    except NotFoundError:
        raise NotFound("Carta non trovata") from None
    rendered = render_card(card)
    rendered.pop("autoplay")
    # in un mazzo filtrato la carta "sta" nel suo mazzo di origine
    did = card.odid or card.did
    return CardPreview(
        card_id=card.id,
        note_id=card.nid,
        deck_id=did,
        deck_name=col.decks.name(did),
        flag=card.user_flag(),
        suspended=card.queue == _SUSPENDED,
        **rendered,
    )


def move_note(col: Collection, note_id: int, deck_id: int) -> Note:
    note = get_note(col, note_id)
    deck = col.decks.get(deck_id, default=False)
    if deck is None:
        raise NotFound("Mazzo non trovato")
    if deck.get("dyn"):
        raise HubError("Non si possono spostare note in un mazzo filtrato")
    col.set_deck(note.card_ids(), deck_id)
    return note


def delete_note(col: Collection, note_id: int) -> None:
    get_note(col, note_id)
    col.remove_notes([note_id])  # type: ignore[list-item]


def change_tags(col: Collection, note_ids: list[int], add: list[str], remove: list[str]) -> int:
    """Aggiunge e toglie tag a più note (una sola voce di undo). Restituisce quante note
    sono cambiate davvero; gli id che non esistono si ignorano."""
    add, remove = clean_tags(add), clean_tags(remove)
    ids = list(dict.fromkeys(col.db.list(f"select id from notes where id in {_ids_sql(note_ids)}")))
    if not ids or not (add or remove):
        return 0
    before = dict(col.db.execute(f"select id, tags from notes where id in {_ids_sql(ids)}"))
    target = col.add_custom_undo_entry(UNDO_TAGS)
    try:
        if remove:
            col.tags.bulk_remove(ids, " ".join(remove))
        if add:
            col.tags.bulk_add(ids, " ".join(add))
    finally:
        col.merge_undo_entries(target)
    after = dict(col.db.execute(f"select id, tags from notes where id in {_ids_sql(ids)}"))
    return sum(1 for i in ids if before[i] != after[i])


# ---- media ---------------------------------------------------------------------------
#
# Un agente può caricare immagini e audio da usare nei campi (`<img src="…">`, `[sound:…]`).
# Il tetto e la lista dei formati sono qui, in un posto solo, per la REST e per il server MCP.
# I file finiscono nella cartella media della collezione e viaggiano con la sync dei media.

MAX_MEDIA_BYTES = 10 * 1024 * 1024
# 4 caratteri di base64 ogni 3 byte: oltre questa lunghezza non vale nemmeno la pena decodificare
_MAX_MEDIA_B64 = (MAX_MEDIA_BYTES + 2) // 3 * 4 + 4
_MAX_NAME_LEN = 100


def _starts(*prefixes: bytes):
    return lambda d: d.startswith(prefixes)


def _riff(kind: bytes):
    return lambda d: d[:4] == b"RIFF" and d[8:12] == kind


def _is_mp3(d: bytes) -> bool:
    # ID3 oppure un frame MPEG (11 bit di sync a 1)
    return d.startswith(b"ID3") or (len(d) > 1 and d[0] == 0xFF and d[1] & 0xE0 == 0xE0)


def _is_adts(d: bytes) -> bool:
    return len(d) > 1 and d[0] == 0xFF and d[1] & 0xF6 == 0xF0


def _is_svg(d: bytes) -> bool:
    head = d[:2048].decode("utf-8", "ignore").lstrip("﻿ \t\r\n").lower()
    return head.startswith(("<svg", "<?xml", "<!doctype svg", "<!--")) and "<svg" in head


# estensione → (tipo, controllo sul contenuto). L'estensione deve corrispondere al contenuto:
# un `.png` che è un eseguibile, o un `.mp3` che è HTML, si rifiuta.
_MEDIA_TYPES: dict[str, tuple[str, object]] = {
    "png": ("immagine", _starts(b"\x89PNG\r\n\x1a\n")),
    "jpg": ("immagine", _starts(b"\xff\xd8\xff")),
    "jpeg": ("immagine", _starts(b"\xff\xd8\xff")),
    "gif": ("immagine", _starts(b"GIF87a", b"GIF89a")),
    "webp": ("immagine", _riff(b"WEBP")),
    "svg": ("immagine", _is_svg),
    "mp3": ("audio", _is_mp3),
    "ogg": ("audio", _starts(b"OggS")),
    "wav": ("audio", _riff(b"WAVE")),
    "m4a": ("audio", lambda d: d[4:8] == b"ftyp"),
    "aac": ("audio", _is_adts),
    "flac": ("audio", _starts(b"fLaC")),
    "mp4": ("video", lambda d: d[4:8] == b"ftyp"),
    "webm": ("video", _starts(b"\x1a\x45\xdf\xa3")),
}
MEDIA_EXTENSIONS = tuple(_MEDIA_TYPES)

# script nell'SVG: i media sono serviti con una CSP `sandbox` (security._MEDIA_CSP) e un <img>
# non esegue mai script, ma un agente non ha motivo di scriverne: meglio non portarli in
# giro nella collezione (finiscono anche su AnkiWeb e sugli altri dispositivi)
_SVG_ACTIVE = re.compile(r"<\s*script|<\s*foreignobject|\son[a-z]+\s*=|javascript\s*:", re.I)
# lista bianca: lettere (anche accentate), cifre, `_`, `.` e `-`; il resto diventa `_`
_UNSAFE_NAME_CHARS = re.compile(r"[^\w.\-]+")


def clean_media_name(raw: str) -> str:
    """Un nome file sicuro: niente percorsi, niente `..`, niente caratteri di controllo, spazi
    o simboli che romperebbero `<img src>` e `[sound:…]`, niente nome "nascosto" (che inizia
    con un punto), lunghezza limitata (l'estensione si conserva). Il nome definitivo lo decide
    comunque Anki (`write_data`), che può cambiarlo se esiste già un file diverso."""
    name = unicodedata.normalize("NFC", raw)
    name = re.split(r"[\\/]", name)[-1]  # solo l'ultimo componente di un eventuale percorso
    name = _UNSAFE_NAME_CHARS.sub("_", name)
    name = re.sub(r"\.{2,}", ".", name).strip("._ ")
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = stem.strip("._ ")
    if len(stem) > _MAX_NAME_LEN - len(ext) - 1:
        stem = stem[: _MAX_NAME_LEN - len(ext) - 1].rstrip("._ ")
    if not stem:
        raise HubError("Nome file non valido: serve un nome (es. «gatto.png»)")
    return f"{stem}.{ext}" if ext else stem


def add_media(col: Collection, filename: str, data_base64: str) -> MediaOut:
    """Valida e scrive un file nella cartella media. Il nome restituito è quello da usare
    nei campi (`<img src="…">` o `[sound:…]`)."""
    name = clean_media_name(filename)
    ext = name.rpartition(".")[2].lower() if "." in name else ""
    if ext not in _MEDIA_TYPES:
        raise HubError(
            f"Estensione «{ext or '(nessuna)'}» non ammessa: usa una di {', '.join(MEDIA_EXTENSIONS)}"
        )

    payload = "".join(data_base64.split())  # il base64 a capo ogni 76 caratteri è valido
    if payload.startswith("data:"):
        raise HubError("Passa solo il base64 del file, senza il prefisso «data:…;base64,»")
    if len(payload) > _MAX_MEDIA_B64:
        raise TooLarge(f"File troppo grande: al massimo {MAX_MEDIA_BYTES // (1024 * 1024)} MB")
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise HubError("data_base64 non è base64 valido (alfabeto standard, con il padding)") from None
    if not data:
        raise HubError("Il file è vuoto")
    if len(data) > MAX_MEDIA_BYTES:
        raise TooLarge(f"File troppo grande: al massimo {MAX_MEDIA_BYTES // (1024 * 1024)} MB")

    kind, matches = _MEDIA_TYPES[ext]
    if not matches(data):  # type: ignore[operator]
        raise HubError(f"Il contenuto non è un {kind} «.{ext}» valido: estensione e contenuto non coincidono")
    if ext == "svg" and _SVG_ACTIVE.search(data.decode("utf-8", "ignore")):
        raise HubError("L'SVG contiene script o elementi attivi: non ammessi")

    final = col.media.write_data(name, data)
    log.info("Media aggiunto", extra={"media_file": final, "size": len(data)})
    return MediaOut(filename=final)
