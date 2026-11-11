"""Diario delle operazioni degli agenti, con annullamento (docs/PIANO-HUB.md, «Rete di sicurezza»).

Gli agenti scrivono direttamente nella collezione (note normali, subito attive): non c'è una
quarantena da approvare. La rete di sicurezza è questa: ogni operazione che MODIFICA davvero la
collezione (`add_notes`, `update_note`, `create_deck`, e le rotte REST equivalenti) lascia una
voce con lo stato di prima, e si può annullare, da `GET /api/hub/operations` + `POST
…/undo` o dai tool MCP `list_operations` e `undo_operation`.

Cosa si può annullare, e cosa no (mai niente che l'utente abbia toccato nel frattempo):

- **nota creata** → cancellata, solo se esiste ancora, non è cambiata dalla creazione (`mod` e
  contenuto uguali) e nessuna sua carta è stata studiata (`reps`, `type`, `revlog`);
- **nota aggiornata** → campi e tag di prima ripristinati, solo se non è cambiata dopo
  l'operazione;
- **mazzo creato** → eliminato, solo se è vuoto e senza sottomazzi.

Il resto si salta, con il motivo, e l'operazione resta `partial` (si può ritentare: gli elementi
già annullati non si rifanno). Non si annullano i media caricati né la sync.

Persistenza: `<ANKI_DATA_DIR>/agent-ops.json` (0600, scrittura atomica, come `tokens.json`); un
file illeggibile si rinomina in `.bak-<data>` e si riparte vuoto. Al massimo le ultime
`MAX_OPERATIONS` operazioni e `MAX_AGE_DAYS` giorni, e un tetto alla dimensione totale: il diario
conserva il testo che i campi avevano PRIMA (non i media, solo i loro nomi dentro i campi).

Blocchi: l'ordine è sempre lock della collezione (`manager.use()`) → lock del diario, mai al
contrario. Le funzioni che scrivono nel diario (`record`) e `undo` si chiamano dentro
`manager.use()`; `list_operations` non tocca la collezione.

L'undo NON passa dallo stack di undo di Anki visibile alla PWA: `_StudyUndo` (routers/study.py)
offre «Annulla» solo per ciò che ha fatto lo studio, e cancellare note o ripristinarle sposta
`last_step`, quindi lo studio non propone mai di annullare un'operazione di un agente.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Literal

from anki.collection import Collection
from anki.notes import Note

from .schemas import OperationKind, OperationOut, UndoOut, UndoSkip

log = logging.getLogger(__name__)

MAX_OPERATIONS = 200
MAX_AGE_DAYS = 30
# oltre questa dimensione (testo dei campi di prima) si dimenticano le operazioni più vecchie: un
# agente che riscrive cento note da 200 KB non deve far crescere il file senza limite
MAX_BYTES = 16 * 1024 * 1024

SESSION_ACTOR = "sessione"
ADMIN_ACTOR = "admin"

ItemKind = Literal["note_created", "note_updated", "deck_created"]
Status = Literal["applied", "partial", "undone"]


class JournalError(Exception):
    """Base degli errori del diario."""


class OperationNotFound(JournalError):
    """L'id non esiste, o è di un altro agente (non si rivela che esiste)."""


class AlreadyUndone(JournalError):
    """L'operazione è già stata annullata del tutto."""


@dataclass(frozen=True)
class Actor:
    """Chi ha fatto l'operazione. `scoped` = un token con scope (o l'OAuth di /mcp): vede e
    annulla solo le proprie operazioni. Un token chiamato «admin» non può quindi confondersi con
    l'amministratore: conta il flag, non il nome."""

    name: str
    scoped: bool = False


@dataclass
class Item:
    """Un elemento di un'operazione, con quanto serve per annullarlo."""

    kind: ItemKind
    # id della nota, o del mazzo
    id: int
    # mazzo: il nome (serve a eliminare prima i figli e a dire cosa si salta)
    name: str | None = None
    # nota: `mod` e impronta del contenuto SUBITO DOPO l'operazione. Se non coincidono più, la nota
    # è stata toccata da qualcun altro. `mod` è al secondo: l'impronta copre lo stesso secondo.
    mod: int | None = None
    digest: str | None = None
    # nota aggiornata: il tipo di nota e lo stato di PRIMA (solo i campi cambiati, i tag interi)
    mid: int | None = None
    fields: dict[str, str] | None = None
    tags: list[str] | None = None
    # annullato (anche in un tentativo precedente di un'operazione `partial`)
    undone: bool = False


@dataclass
class Operation:
    id: str
    created_at: int
    agent: str
    scoped: bool
    kind: OperationKind
    summary: str
    items: list[Item] = field(default_factory=list)
    status: Status = "applied"
    undone_at: int | None = None

    @property
    def note_count(self) -> int:
        return sum(1 for i in self.items if i.kind != "deck_created")

    def out(self) -> OperationOut:
        return OperationOut(
            id=self.id,
            created_at=self.created_at,
            agent=self.agent,
            kind=self.kind,
            summary=self.summary,
            note_count=self.note_count,
            status=self.status,
            undone_at=self.undone_at,
        )


# ---- impronte e voci -----------------------------------------------------------------------


def note_digest(note: Note) -> str:
    """Impronta di campi e tag: cattura ciò che `mod` (al secondo) non distingue."""
    raw = "\x1f".join(note.fields) + "\x1e" + " ".join(sorted(t.casefold() for t in note.tags))
    return hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()


def item_created(note: Note) -> Item:
    """Una nota appena creata: `note` va riletta dalla collezione (con `mod` vero)."""
    return Item("note_created", note.id, mod=note.mod, digest=note_digest(note))


def item_updated(note: Note, prev_fields: dict[str, str], prev_tags: list[str]) -> Item:
    """Una nota appena aggiornata (riletta dalla collezione); `prev_*` è lo stato di prima."""
    return Item(
        "note_updated",
        note.id,
        mod=note.mod,
        digest=note_digest(note),
        mid=note.mid,
        fields=dict(prev_fields),
        tags=list(prev_tags),
    )


def item_deck(deck_id: int, name: str) -> Item:
    return Item("deck_created", deck_id, name=name)


def deck_snapshot(col: Collection) -> dict[int, str]:
    """Id e nomi di tutti i mazzi: confrontato prima e dopo, dice quali ha creato una scrittura
    (anche i genitori che mancavano: «A::B::C» può creare tre mazzi)."""
    return {int(d.id): d.name for d in col.decks.all_names_and_ids(include_filtered=True)}


def new_decks(before: dict[int, str], col: Collection) -> list[Item]:
    after = deck_snapshot(col)
    return [item_deck(i, n) for i, n in after.items() if i not in before]


# ---- il diario -----------------------------------------------------------------------------


class Journal:
    def __init__(
        self,
        path: Path,
        *,
        max_operations: int = MAX_OPERATIONS,
        max_age_days: float = MAX_AGE_DAYS,
        max_bytes: int = MAX_BYTES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = path
        self.max_operations = max_operations
        self.max_age_s = max_age_days * 86400
        self.max_bytes = max_bytes
        self.clock = clock
        self._lock = threading.RLock()
        # se un file illeggibile non si riesce a spostare, non lo si sovrascrive mai
        self._save_blocked = False
        self._ops: list[Operation] = self._load()
        with self._lock:
            if self._prune():
                self._save()

    # ---- disco -------------------------------------------------------------

    def _load(self) -> list[Operation]:
        try:
            raw = json.loads(self.path.read_text())
            op_known = {f.name for f in fields(Operation)}
            item_known = {f.name for f in fields(Item)}
            ops: list[Operation] = []
            for o in raw["operations"]:
                data = {k: v for k, v in o.items() if k in op_known}
                data["items"] = [
                    Item(**{k: v for k, v in i.items() if k in item_known}) for i in data.get("items", [])
                ]
                ops.append(Operation(**data))
            return ops
        except FileNotFoundError:
            return []
        except (ValueError, TypeError, KeyError, AttributeError, OSError):
            self._set_aside()
            return []

    def _set_aside(self) -> None:
        """Il file non si legge: lo si mette da parte invece di lasciarlo sovrascrivere dal
        primo `record`. Niente contenuti nel log (sono testi delle carte)."""
        backup = self.path.with_name(f"{self.path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        try:
            os.replace(self.path, backup)
            os.chmod(backup, 0o600)
        except OSError:
            log.error("%s non leggibile e non spostabile: non lo scrivo", self.path.name)
            self._save_blocked = True
        else:
            log.warning("%s non leggibile: salvato come %s, riparto da un diario vuoto", self.path.name, backup.name)

    def _save(self) -> None:
        """Mai un'eccezione verso chi scrive nella collezione: se il disco non va, il diario resta
        in memoria (e si perde al riavvio), ma l'operazione dell'agente non fallisce."""
        if self._save_blocked:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({"version": 1, "operations": [asdict(o) for o in self._ops]}, f)
            tmp.replace(self.path)
        except OSError:
            log.warning("Impossibile salvare il diario delle operazioni", exc_info=True)

    def _prune(self) -> bool:
        """Toglie le voci troppo vecchie o in eccesso. Vero se qualcosa è cambiato."""
        before = len(self._ops)
        horizon = self.clock() - self.max_age_s
        ops = [o for o in self._ops if o.created_at >= horizon]
        ops = ops[-self.max_operations :]
        # tetto alla dimensione: si dimenticano le più vecchie, ma l'ultima resta sempre
        sizes = [len(json.dumps(asdict(o))) for o in ops]
        total = sum(sizes)
        while len(ops) > 1 and total > self.max_bytes:
            total -= sizes.pop(0)
            ops.pop(0)
        self._ops = ops
        return len(ops) != before

    # ---- scrittura ---------------------------------------------------------

    def record(self, actor: Actor, kind: OperationKind, summary: str, items: list[Item]) -> str | None:
        """Registra un'operazione già avvenuta; restituisce il suo id. Senza elementi (nessun
        effetto reale) non registra niente e restituisce None."""
        if not items:
            return None
        with self._lock:
            existing = {o.id for o in self._ops}
            op_id = secrets.token_hex(4)
            while op_id in existing:
                op_id = secrets.token_hex(4)
            self._ops.append(
                Operation(
                    id=op_id,
                    created_at=int(self.clock()),
                    agent=actor.name,
                    scoped=actor.scoped,
                    kind=kind,
                    summary=summary,
                    items=items,
                )
            )
            self._prune()
            self._save()
        log.info("Operazione registrata", extra={"operation_id": op_id, "agent": actor.name, "kind": kind})
        return op_id

    # ---- lettura -----------------------------------------------------------

    @staticmethod
    def _visible(op: Operation, agent: str | None) -> bool:
        """`agent` = lo slug di un token con scope: vede solo le proprie. None = vede tutto."""
        return agent is None or (op.scoped and op.agent == agent)

    def list(self, *, agent: str | None = None, limit: int = 50) -> list[OperationOut]:
        with self._lock:
            if self._prune():
                self._save()
            ops = [o for o in reversed(self._ops) if self._visible(o, agent)]
            return [o.out() for o in ops[:limit]]

    def get(self, op_id: str, *, agent: str | None = None) -> OperationOut:
        with self._lock:
            return self._find(op_id, agent).out()

    def _find(self, op_id: str, agent: str | None) -> Operation:
        for op in self._ops:
            if op.id == op_id and self._visible(op, agent):
                return op
        raise OperationNotFound("Operazione non trovata")

    # ---- annullamento ------------------------------------------------------

    def undo(self, col: Collection, op_id: str, *, agent: str | None = None) -> UndoOut:
        """Annulla un'operazione (da chiamare dentro `manager.use()`). Ogni elemento è tentato
        anche se un altro fallisce; quelli che non si possono annullare tornano in `skipped`.
        `OperationNotFound` se l'id non c'è (o è di un altro agente), `AlreadyUndone` se è già
        stata annullata del tutto."""
        with self._lock:
            op = self._find(op_id, agent)
            if op.status == "undone":
                raise AlreadyUndone("Operazione già annullata")
            restored = deleted = 0
            skipped: list[UndoSkip] = []
            # prima le note, poi i mazzi (un mazzo si elimina solo se è vuoto), i più profondi per primi
            todo = [i for i in op.items if not i.undone and i.kind != "deck_created"]
            todo += sorted(
                (i for i in op.items if not i.undone and i.kind == "deck_created"),
                key=lambda i: -(i.name or "").count("::"),
            )
            for item in todo:
                try:
                    reason = self._undo_item(col, item)
                except Exception as e:  # noqa: BLE001 - un elemento che fallisce non ferma gli altri
                    # niente traceback: potrebbe citare il testo di una carta
                    log.warning(
                        "Annullamento di un elemento non riuscito",
                        extra={"operation_id": op.id, "error": type(e).__name__},
                    )
                    reason = f"errore imprevisto: {e}"
                if reason is None:
                    item.undone = True
                    if item.kind == "note_updated":
                        restored += 1
                    else:
                        deleted += 1
                else:
                    skipped.append(
                        UndoSkip(note_id=None if item.kind == "deck_created" else item.id, reason=reason)
                    )
            if all(i.undone for i in op.items):
                op.status, op.undone_at = "undone", int(self.clock())
            else:
                op.status = "partial"
            self._save()
            out = UndoOut(
                operation_id=op.id,
                status="undone" if op.status == "undone" else "partial",
                restored=restored,
                deleted=deleted,
                skipped=skipped,
            )
        log.info(
            "Operazione annullata",
            extra={"operation_id": op_id, "status": out.status, "restored": restored, "deleted": deleted},
        )
        return out

    def _undo_item(self, col: Collection, item: Item) -> str | None:
        """None se annullato, altrimenti il motivo per cui si salta."""
        if item.kind == "deck_created":
            return self._undo_deck(col, item)
        note = _load_note(col, item.id)
        if note is None:
            return "la nota non esiste più"
        if note.mod != item.mod or note_digest(note) != item.digest:
            return "modificata dopo l'operazione"
        if item.kind == "note_created":
            if _was_studied(col, note):
                return "ha carte già studiate"
            col.remove_notes([note.id])  # type: ignore[list-item]
            return None
        # nota aggiornata: si ripristinano campi e tag esatti di prima, senza il filtro dei tag
        # riservati (altrimenti `agent::` ed `ext::` andrebbero persi)
        if note.mid != item.mid:
            return "il tipo di nota è cambiato"
        prev = item.fields or {}
        missing = [k for k in prev if k not in note.keys()]
        if missing:
            return f"i campi {missing} non esistono più nel tipo di nota"
        for name, value in prev.items():
            note[name] = value
        note.tags = list(item.tags or [])
        col.update_note(note)
        self._rebase(col, item.id)
        return None

    def _rebase(self, col: Collection, note_id: int) -> None:
        """Dopo un ripristino la nota ha un `mod` nuovo. Le altre operazioni ancora annullabili su
        quella nota, che si aspettavano esattamente questo contenuto, devono aspettarsi il `mod`
        nuovo: così annullare B e poi A (A ha creato la nota, B l'ha aggiornata) funziona."""
        note = _load_note(col, note_id)
        if note is None:
            return
        digest = note_digest(note)
        for other in self._ops:
            for it in other.items:
                if it.kind != "deck_created" and it.id == note_id and not it.undone and it.digest == digest:
                    it.mod = note.mod

    @staticmethod
    def _undo_deck(col: Collection, item: Item) -> str | None:
        name = f"«{item.name}»" if item.name else "il mazzo"
        deck = col.decks.get(item.id, default=False)  # type: ignore[arg-type]
        if deck is None:
            return f"{name} non esiste più"
        if deck.get("dyn"):
            return f"{name} è diventato un mazzo filtrato"
        if col.decks.children(item.id):  # type: ignore[arg-type]
            return f"{name} ha dei sottomazzi"
        if col.decks.card_count(item.id, include_subdecks=False):  # type: ignore[arg-type]
            return f"{name} non è vuoto"
        if item.id == 1:
            return "il mazzo Default non si elimina"
        col.decks.remove([item.id])  # type: ignore[list-item]
        return None


def _load_note(col: Collection, note_id: int) -> Note | None:
    try:
        return col.get_note(note_id)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - NotFoundError: la nota non c'è più
        return None


def _was_studied(col: Collection, note: Note) -> bool:
    """Una carta con ripassi (`reps`), non più nuova (`type`) o con una riga in `revlog` (anche un
    riprogrammato a mano) ha una storia che cancellare farebbe perdere."""
    if col.db.scalar("select count() from cards where nid = ? and (reps != 0 or type != 0)", note.id):
        return True
    return bool(
        col.db.scalar("select count() from revlog where cid in (select id from cards where nid = ?)", note.id)
    )


# ---- riassunti -----------------------------------------------------------------------------


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def summary_for_notes(created: int, updated: int, deck_names: list[str], new_deck_count: int = 0) -> str:
    """«3 note create in Prova::Hub», «1 nota aggiornata», «2 note create e 1 aggiornata»…"""
    parts = []
    if created:
        parts.append(_plural(created, "nota creata", "note create"))
    if updated:
        # «e 1 aggiornata» suona meglio di «e 1 nota aggiornata» dopo una frase già con «note»
        parts.append(_plural(updated, "nota aggiornata", "note aggiornate"))
    text = " e ".join(parts) if parts else "Nessuna nota"
    if created and len(deck_names) == 1:
        text += f" in {deck_names[0]}"
    elif created and len(deck_names) > 1:
        text += f" in {len(deck_names)} mazzi"
    if new_deck_count:
        text += f" ({_plural(new_deck_count, 'mazzo creato', 'mazzi creati')})"
    return text


def summary_for_decks(names: list[str]) -> str:
    if len(names) == 1:
        return f"Mazzo creato: {names[0]}"
    return f"{len(names)} mazzi creati: {', '.join(names)}"


def summary_for_update(note_id: int, changed_fields: list[str], tags_changed: bool) -> str:
    what = [*changed_fields, *(["tag"] if tags_changed else [])]
    return f"Nota {note_id} aggiornata" + (f" ({', '.join(what)})" if what else "")
