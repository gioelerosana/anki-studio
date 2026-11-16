from fastapi import APIRouter, Depends, HTTPException, status

from anki.collection import Collection

from ..collection import CollectionManager
from ..deps import get_manager, get_sync
from ..rendering import strip_bidi
from ..schemas import Counts, DeckDeleteOut, DeckInfo, DeckNode, TodayStats
from ..sync import SyncService

router = APIRouter(tags=["decks"])


def _convert(node, parent_name: str = "") -> DeckNode:
    full = f"{parent_name}::{node.name}" if parent_name else node.name
    return DeckNode(
        id=node.deck_id,
        name=node.name,
        full_name=full,
        level=node.level,
        collapsed=node.collapsed,
        counts=Counts(
            new=node.new_count, learning=node.learn_count, review=node.review_count
        ),
        children=[_convert(c, full) for c in node.children],
    )


@router.get("/decks", response_model=list[DeckNode])
def list_decks(manager: CollectionManager = Depends(get_manager)):
    """Albero dei mazzi con i conteggi di oggi (come la schermata principale di Anki)."""
    with manager.use() as col:
        root = col.sched.deck_due_tree()
        return [_convert(c) for c in root.children]


def _deck_or_404(col: Collection, deck_id: int) -> dict:
    deck = col.decks.get(deck_id, default=False)
    if not deck:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mazzo non trovato")
    return deck


def _info(col: Collection, deck: dict) -> DeckInfo:
    ids = col.decks.deck_and_child_ids(deck["id"])
    in_ids = "(" + ",".join(str(int(i)) for i in ids) + ")"
    if deck["dyn"]:
        # un filtrato non cancella carte: quelle che contiene tornano al mazzo d'origine
        where = f"did in {in_ids}"
    else:
        # come Anki: si cancellano le carte che hanno qui la loro casa, anche se ora sono
        # in un filtrato altrove (odid); quelle di un filtrato figlio con casa fuori tornano a casa
        where = f"(case when odid != 0 then odid else did end) in {in_ids}"
    cards, notes = col.db.first(f"select count(), count(distinct nid) from cards where {where}")
    return DeckInfo(
        id=deck["id"],
        full_name=deck["name"],
        filtered=bool(deck["dyn"]),
        subdecks=len(ids) - 1,
        cards=cards,
        notes=notes,
    )


@router.get("/decks/{deck_id}", response_model=DeckInfo)
def deck_info(deck_id: int, manager: CollectionManager = Depends(get_manager)):
    """Quante carte, note e sottomazzi se ne andrebbero eliminando il mazzo (per la conferma)."""
    with manager.use() as col:
        return _info(col, _deck_or_404(col, deck_id))


@router.delete("/decks/{deck_id}", response_model=DeckDeleteOut)
def delete_deck(
    deck_id: int,
    manager: CollectionManager = Depends(get_manager),
    sync: SyncService = Depends(get_sync),
):
    """Elimina il mazzo con i sottomazzi e le loro carte, come «Elimina» in Anki desktop.
    Un mazzo filtrato restituisce le carte ai mazzi d'origine. La PWA chiede conferma prima:
    da qui non si annulla, e alla sync successiva il mazzo sparisce anche da AnkiWeb."""
    with manager.use() as col:
        deck = _deck_or_404(col, deck_id)
        decks = len(col.decks.deck_and_child_ids(deck_id))
        changes = col.decks.remove([deck_id])  # type: ignore[list-item]
    sync.request_soon()
    return DeckDeleteOut(deleted_cards=changes.count, deleted_decks=decks)


@router.get("/stats/today", response_model=TodayStats)
def today_stats(manager: CollectionManager = Depends(get_manager)):
    with manager.use() as col:
        start_ms = (col.sched.day_cutoff - 86400) * 1000
        reviews, ms, again = col.db.first(
            "select count(), coalesce(sum(time), 0), "
            "coalesce(sum(case when ease = 1 then 1 else 0 end), 0) "
            "from revlog where id > ?",
            start_ms,
        )
        return TodayStats(
            reviews=reviews,
            seconds=ms // 1000,
            again=again,
            summary=strip_bidi(col.studied_today()),
        )
