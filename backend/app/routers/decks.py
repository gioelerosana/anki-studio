from fastapi import APIRouter, Depends

from ..collection import CollectionManager
from ..deps import get_manager
from ..rendering import strip_bidi
from ..schemas import Counts, DeckNode, TodayStats

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
