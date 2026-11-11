"""Sessione di studio: prossima carta, risposta, undo, azioni rapide.

L'API è stateless: ogni chiamata indica il mazzo, il backend lo seleziona e
chiede allo scheduler di Anki la carta in cima alla coda. Quando rispondi,
il backend verifica che la carta sia ancora quella in cima (se nel frattempo
hai studiato da un altro dispositivo e sincronizzato, ricevi 409 e la PWA
ricarica la carta successiva).
"""

import weakref
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from anki.cards import Card
from anki.collection import Collection
from anki.errors import UndoEmpty
from anki.scheduler.v3 import CardAnswer, QueuedCards
from anki.utils import int_time

from ..collection import CollectionManager
from ..deps import get_manager
from ..rendering import render_card, render_typed_answer, strip_bidi
from ..schemas import (
    AnswerIn,
    Counts,
    FlagIn,
    StudyCard,
    StudyState,
    TypedAnswerIn,
    TypedAnswerOut,
)

router = APIRouter(tags=["study"])

_QUEUE = {
    QueuedCards.NEW: "new",
    QueuedCards.LEARNING: "learning",
    QueuedCards.REVIEW: "review",
}
_RATING = {
    1: CardAnswer.AGAIN,
    2: CardAnswer.HARD,
    3: CardAnswer.GOOD,
    4: CardAnswer.EASY,
}


class _StudyUndo:
    """Quali passi della pila di undo di Anki sono davvero dello studio.

    L'«Annulla» dello studio deve annullare solo una risposta o un'azione fatta qui, mai la
    modifica di un agente (o il suo annullamento dal diario, app/journal.py) o la selezione di un
    mazzo: sotto c'è una pila sola, condivisa con tutto il resto. Anki non dice chi ha fatto cosa, ma `last_step`
    cambia a ogni operazione (anche a ogni undo). Per ogni operazione dello studio ci segniamo
    `last_step` prima e dopo; l'ultima è annullabile da qui solo se da allora `last_step` non è
    cambiato (nessun'altra operazione), e quella sotto solo se tra le due non c'è stato altro.
    Tutto in memoria: dopo un riavvio non si offre niente finché non si risponde di nuovo."""

    def __init__(self) -> None:
        self.ops: list[tuple[int, int]] = []  # (last_step prima, last_step dopo)
        self.current = -1  # last_step a cui `ops` è aggiornato

    def remember(self, before: int, after: int) -> None:
        if after == before:
            return  # niente è stato registrato
        # una nuova operazione si appoggia alle precedenti solo se non c'è stato altro in mezzo
        if self.ops and self.current == before:
            self.ops.append((before, after))
        else:
            self.ops = [(before, after)]
        self.current = after

    def can_undo(self, last_step: int) -> bool:
        return bool(self.ops) and self.current == last_step

    def undone(self, new_step: int) -> None:
        """Dopo un undo dello studio: sotto c'è un'altra operazione dello studio solo se era
        attaccata a quella annullata; altrimenti non offriamo più niente."""
        before, _ = self.ops.pop()
        if not (self.ops and self.ops[-1][1] == before):
            self.ops.clear()
        self.current = new_step


# per collezione: la collezione si riapre dopo una sync completa e lo stato riparte da zero
_study_undo: "weakref.WeakKeyDictionary[Collection, _StudyUndo]" = weakref.WeakKeyDictionary()


def _undo_state(col: Collection) -> _StudyUndo:
    return _study_undo.setdefault(col, _StudyUndo())


@contextmanager
def _study_op(col: Collection) -> Iterator[None]:
    """Racchiude una scrittura dello studio (risposta, seppellisci, sospendi, flag)."""
    before = col.undo_status().last_step
    yield
    _undo_state(col).remember(before, col.undo_status().last_step)


def _select_deck(col: Collection, deck_id: int) -> None:
    if col.decks.get(deck_id, default=False) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mazzo non trovato")
    if col.decks.get_current_id() != deck_id:
        # la selezione del mazzo è un'operazione annullabile, ma non dello studio: non è
        # registrata, quindi dopo un cambio di mazzo non si annulla niente (l'ultima risposta
        # era in un altro mazzo e tornarci a sorpresa confonde)
        col.decks.select(deck_id)


def _undo_label(col: Collection) -> str | None:
    """Cosa annullerebbe «Annulla», o None se l'ultima operazione non è dello studio."""
    status_ = col.undo_status()
    if status_.undo and _undo_state(col).can_undo(status_.last_step):
        return status_.undo
    return None


def _state(col: Collection) -> StudyState:
    queued = col.sched.get_queued_cards(fetch_limit=1)
    counts = Counts(
        new=queued.new_count,
        learning=queued.learning_count,
        review=queued.review_count,
    )
    deck_name = col.decks.name(col.decks.get_current_id())
    if not queued.cards:
        return StudyState(
            done=True, counts=counts, deck_name=deck_name, undo_label=_undo_label(col)
        )

    qc = queued.cards[0]
    card = Card(col)
    card._load_from_backend_card(qc.card)
    note = card.note()
    return StudyState(
        done=False,
        counts=counts,
        deck_name=deck_name,
        undo_label=_undo_label(col),
        card=StudyCard(
            card_id=card.id,
            note_id=card.nid,
            deck_id=card.did,
            queue=_QUEUE[qc.queue],
            button_labels=[strip_bidi(x) for x in col.sched.describe_next_states(qc.states)],
            flag=card.user_flag(),
            tags=list(note.tags),
            **render_card(card),
        ),
    )


@router.get("/decks/{deck_id}/study", response_model=StudyState)
def next_card(deck_id: int, manager: CollectionManager = Depends(get_manager)):
    with manager.use() as col:
        _select_deck(col, deck_id)
        return _state(col)


@router.post("/decks/{deck_id}/study/answer", response_model=StudyState)
def answer(
    deck_id: int, body: AnswerIn, manager: CollectionManager = Depends(get_manager)
):
    """Registra la risposta e restituisce direttamente la carta successiva."""
    with manager.use() as col:
        _select_deck(col, deck_id)
        queued = col.sched.get_queued_cards(fetch_limit=1)
        if not queued.cards or queued.cards[0].card.id != body.card_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "La carta non è più in cima alla coda: ricarica la sessione",
            )
        qc = queued.cards[0]
        card = Card(col)
        card._load_from_backend_card(qc.card)

        states = qc.states
        new_state = {
            1: states.again,
            2: states.hard,
            3: states.good,
            4: states.easy,
        }[body.rating]
        # come Anki desktop, il tempo registrato è limitato dal preset del mazzo
        limit = card.time_limit()
        taken = min(body.time_taken_ms, limit) if limit else body.time_taken_ms
        with _study_op(col):
            col.sched.answer_card(
                CardAnswer(
                    card_id=card.id,
                    current_state=states.current,
                    new_state=new_state,
                    rating=_RATING[body.rating],
                    answered_at_millis=int_time(1000),
                    milliseconds_taken=taken,
                )
            )
        return _state(col)


@router.post("/decks/{deck_id}/study/undo", response_model=StudyState)
def undo(deck_id: int, manager: CollectionManager = Depends(get_manager)):
    with manager.use() as col:
        if _undo_label(col) is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Niente da annullare")
        try:
            col.undo()
        except UndoEmpty:
            raise HTTPException(status.HTTP_409_CONFLICT, "Niente da annullare")
        _undo_state(col).undone(col.undo_status().last_step)
        _select_deck(col, deck_id)
        return _state(col)


def _card_or_404(col: Collection, card_id: int) -> Card:
    try:
        return col.get_card(card_id)
    except Exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Carta non trovata")


_DECK_QUERY = Query(
    None, description="Se presente, risponde con lo StudyState di questo mazzo (200) invece di 204"
)


def _after_action(col: Collection, deck_id: int | None):
    if deck_id is None:
        return Response(status_code=204)
    _select_deck(col, deck_id)
    return _state(col)


@router.post(
    "/cards/{card_id}/bury",
    response_model=StudyState,
    responses={204: {"description": "Senza deck_id: nessun contenuto"}},
)
def bury(
    card_id: int,
    deck_id: int | None = _DECK_QUERY,
    manager: CollectionManager = Depends(get_manager),
):
    with manager.use() as col:
        _card_or_404(col, card_id)
        with _study_op(col):
            col.sched.bury_cards([card_id])
        return _after_action(col, deck_id)


@router.post(
    "/cards/{card_id}/suspend",
    response_model=StudyState,
    responses={204: {"description": "Senza deck_id: nessun contenuto"}},
)
def suspend(
    card_id: int,
    deck_id: int | None = _DECK_QUERY,
    manager: CollectionManager = Depends(get_manager),
):
    with manager.use() as col:
        _card_or_404(col, card_id)
        with _study_op(col):
            col.sched.suspend_cards([card_id])
        return _after_action(col, deck_id)


@router.post("/cards/{card_id}/type-answer", response_model=TypedAnswerOut)
def type_answer(
    card_id: int, body: TypedAnswerIn, manager: CollectionManager = Depends(get_manager)
):
    """Retro della carta con la risposta digitata confrontata come in Anki
    (`<code id=typeans>` con le classi typeGood/typeBad/typeMissed)."""
    with manager.use() as col:
        card = _card_or_404(col, card_id)
        return TypedAnswerOut(answer_html=render_typed_answer(card, body.typed))


@router.post("/cards/{card_id}/flag", status_code=204)
def flag(card_id: int, body: FlagIn, manager: CollectionManager = Depends(get_manager)):
    with manager.use() as col:
        _card_or_404(col, card_id)
        with _study_op(col):
            col.set_user_flag_for_cards(body.flag, [card_id])
