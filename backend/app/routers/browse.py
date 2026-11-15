"""Ricerca delle note, tag, statistiche e opzioni del mazzo.

Tutto in sola lettura, tranne `extend-limits` (il "Studia altre N carte oggi" di
Anki), che passa dallo scheduler come le altre operazioni, e il salvataggio delle opzioni
del mazzo, che passa da `update_deck_configs` come la schermata di Anki desktop.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query, status

from anki.collection import Collection
from anki.deck_config_pb2 import UpdateDeckConfigsMode
from anki.decks import UpdateDeckConfigs
from anki.errors import SearchError

from ..collection import CollectionManager
from ..deps import get_manager, get_sync
from ..schemas import (
    CardCounts,
    DayForecast,
    DayReviews,
    DeckLimits,
    DeckOptions,
    DeckOptionsIn,
    DeckPreset,
    ExtendLimitsIn,
    NoteSearchItem,
    NoteSearchOut,
    StatsOut,
    StudyState,
)
from ..sync import SyncService
from .study import _select_deck, _state

router = APIRouter(tags=["browse"])

_MAX_LIMIT = 200


def _deck_or_404(col: Collection, deck_id: int) -> dict:
    deck = col.decks.get(deck_id, default=False)
    if deck is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mazzo non trovato")
    return deck


def _ids_sql(ids) -> str:
    return "(" + ",".join(str(int(i)) for i in ids) + ")"


# ---- ricerca -------------------------------------------------------------------


@router.get("/search/notes", response_model=NoteSearchOut)
def search_notes(
    q: str = Query("", description='Sintassi di ricerca di Anki, es. `deck:Spagnolo tag:verbi "is:due"`'),
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    manager: CollectionManager = Depends(get_manager),
):
    """Note che corrispondono alla ricerca, dalla modificata più di recente."""
    with manager.use() as col:
        try:
            ids = list(col.find_notes(q, order="n.mod desc"))
        except SearchError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Ricerca non valida: {e}")
        page = ids[offset : offset + limit]
        items: list[NoteSearchItem] = []
        if page:
            rows = {
                nid: (mid, sfld, tags, mod)
                for nid, mid, sfld, tags, mod in col.db.execute(
                    f"select id, mid, sfld, tags, mod from notes where id in {_ids_sql(page)}"
                )
            }
            cards: dict[int, list[tuple[int, int]]] = {}
            for nid, cid, did in col.db.execute(
                f"select nid, id, did from cards where nid in {_ids_sql(page)} order by ord"
            ):
                cards.setdefault(nid, []).append((cid, did))
            names: dict[int, str] = {}
            for nid in page:
                mid, sfld, tags, mod = rows[nid]
                if mid not in names:
                    nt = col.models.get(mid)
                    names[mid] = nt["name"] if nt else "?"
                note_cards = cards.get(nid, [])
                items.append(
                    NoteSearchItem(
                        id=nid,
                        notetype_id=mid,
                        notetype_name=names[mid],
                        sort_field=str(sfld),
                        tags=col.tags.split(tags),
                        card_ids=[c for c, _ in note_cards],
                        deck_name=col.decks.name(note_cards[0][1]) if note_cards else None,
                        modified=mod,
                    )
                )
        return NoteSearchOut(total=len(ids), offset=offset, notes=items)


@router.get("/tags", response_model=list[str])
def list_tags(manager: CollectionManager = Depends(get_manager)):
    """Tutti i tag, in ordine alfabetico (quelli gerarchici come `spagnolo::verbi`)."""
    with manager.use() as col:
        return sorted(col.tags.all(), key=str.casefold)


# ---- statistiche ---------------------------------------------------------------


@router.get("/stats", response_model=StatsOut)
def stats(
    deck_id: int | None = Query(None, description="Solo questo mazzo e i suoi figli"),
    days: int = Query(30, ge=1, le=365),
    manager: CollectionManager = Depends(get_manager),
):
    with manager.use() as col:
        if deck_id is not None:
            _deck_or_404(col, deck_id)
            dids = _ids_sql(col.decks.deck_and_child_ids(deck_id))
            where = f"(did in {dids} or odid in {dids})"
        else:
            where = "1"

        counts = CardCounts(
            **dict(
                zip(
                    ("new", "learning", "young", "mature", "suspended", "buried", "total"),
                    col.db.first(
                        f"""select
                          coalesce(sum(type = 0 and queue >= 0), 0),
                          coalesce(sum(type in (1, 3) and queue >= 0), 0),
                          coalesce(sum(type = 2 and queue >= 0 and ivl < 21), 0),
                          coalesce(sum(type = 2 and queue >= 0 and ivl >= 21), 0),
                          coalesce(sum(queue = -1), 0),
                          coalesce(sum(queue in (-2, -3)), 0),
                          count()
                        from cards where {where}"""
                    ),
                )
            )
        )

        # review per giorno: giorno 0 = oggi secondo l'orario di Anki (cambio giorno incluso)
        today_start = col.sched.day_cutoff - 86400
        since = today_start - (days - 1) * 86400
        by_day: dict[int, list[int]] = {}
        passed = total_reviews = 0
        revlog_where = "1" if deck_id is None else f"cid in (select id from cards where {where})"
        for rid, ease, ms, rtype in col.db.execute(
            f"select id, ease, time, type from revlog where id >= ? and {revlog_where} "
            "and type < 4",  # 4 = riprogrammazione manuale, 5 = filtrato senza voto
            since * 1000,
        ):
            day = int((rid // 1000 - today_start) // 86400)
            d = by_day.setdefault(day, [0, 0, 0])
            d[0] += 1
            d[1] += ease == 1
            d[2] += ms
            if rtype == 1:  # solo i ripassi veri contano per la ritenzione
                total_reviews += 1
                passed += ease > 1
        reviews = [
            DayReviews(day=d, reviews=v[0], again=v[1], seconds=v[2] // 1000)
            for d in range(-(days - 1), 1)
            for v in [by_day.get(d, [0, 0, 0])]
        ]

        # carte da ripassare nei prossimi 7 giorni (le scadute contano per oggi)
        today = col.sched.today
        forecast = [0] * 7
        for queue, due in col.db.execute(
            f"select queue, due from cards where queue in (1, 2, 3) and {where}"
        ):
            if queue == 1:  # apprendimento: due è un timestamp
                day = 0 if due < col.sched.day_cutoff else 1
            else:
                day = max(0, due - today)
            if day < 7:
                forecast[day] += 1

        return StatsOut(
            cards=counts,
            reviews=reviews,
            retention=round(passed / total_reviews, 4) if total_reviews else None,
            forecast=[DayForecast(day=i, due=n) for i, n in enumerate(forecast)],
            generated_at=time.time(),
        )


# ---- opzioni del mazzo ---------------------------------------------------------


def _preset_out(preset, use_count: int) -> DeckPreset:
    cfg = preset.config
    return DeckPreset(
        id=preset.id,
        name=preset.name,
        use_count=use_count,
        new_per_day=cfg.new_per_day,
        reviews_per_day=cfg.reviews_per_day,
        learn_steps_min=[round(x, 4) for x in cfg.learn_steps],
        relearn_steps_min=[round(x, 4) for x in cfg.relearn_steps],
        max_answer_seconds=cfg.cap_answer_time_to_secs,
        bury_new_siblings=cfg.bury_new,
        bury_review_siblings=cfg.bury_reviews,
        desired_retention=round(cfg.desired_retention, 4),
    )


def _options_out(col: Collection, deck_id: int, deck: dict) -> DeckOptions:
    if deck.get("dyn"):
        return DeckOptions(deck_id=deck_id, deck_name=deck["name"], filtered=True)
    # La stessa vista della schermata delle opzioni di Anki desktop: preset, limiti del mazzo
    # e opzioni della collezione arrivano insieme e si salvano insieme (update_deck_configs).
    upd = col.decks.get_deck_configs_for_update(deck_id)
    current = upd.current_deck
    preset = next(c.config for c in upd.all_config if c.config.id == current.config_id)
    cfg = preset.config
    lim = current.limits
    return DeckOptions(
        deck_id=deck_id,
        deck_name=deck["name"],
        filtered=False,
        preset_id=preset.id,
        preset_name=preset.name,
        presets=[_preset_out(c.config, c.use_count) for c in upd.all_config],
        new_per_day=cfg.new_per_day,
        reviews_per_day=cfg.reviews_per_day,
        deck_limits=DeckLimits(
            new=lim.new if lim.HasField("new") else None,
            review=lim.review if lim.HasField("review") else None,
            new_today=lim.new_today if lim.new_today_active and lim.HasField("new_today") else None,
            review_today=(
                lim.review_today if lim.review_today_active and lim.HasField("review_today") else None
            ),
        ),
        learn_steps_min=[round(x, 4) for x in cfg.learn_steps],
        relearn_steps_min=[round(x, 4) for x in cfg.relearn_steps],
        max_answer_seconds=cfg.cap_answer_time_to_secs,
        bury_new_siblings=cfg.bury_new,
        bury_review_siblings=cfg.bury_reviews,
        new_cards_ignore_review_limit=upd.new_cards_ignore_review_limit,
        apply_all_parent_limits=upd.apply_all_parent_limits,
        fsrs=upd.fsrs,
        desired_retention=round(cfg.desired_retention, 4) if upd.fsrs else None,
    )


@router.get("/decks/{deck_id}/options", response_model=DeckOptions)
def deck_options(deck_id: int, manager: CollectionManager = Depends(get_manager)):
    """Il preset di opzioni del mazzo, i limiti propri del mazzo e le opzioni della collezione."""
    with manager.use() as col:
        deck = _deck_or_404(col, deck_id)
        return _options_out(col, deck_id, deck)


@router.put("/decks/{deck_id}/options", response_model=DeckOptions)
def update_deck_options(
    deck_id: int,
    body: DeckOptionsIn,
    manager: CollectionManager = Depends(get_manager),
    sync: SyncService = Depends(get_sync),
):
    """Salva le opzioni come la schermata di Anki desktop: assegna il mazzo a `preset_id`,
    scrive i campi del preset (che valgono per tutti i mazzi che lo usano) e i limiti propri
    del mazzo. Passa da `update_deck_configs`, quindi è un'operazione annullabile di Anki e
    i campi che la PWA non mostra restano com'erano."""
    with manager.use() as col:
        deck = _deck_or_404(col, deck_id)
        if deck.get("dyn"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "I mazzi filtrati non hanno opzioni")
        upd = col.decks.get_deck_configs_for_update(deck_id)
        preset = next((c.config for c in upd.all_config if c.config.id == body.preset_id), None)
        if preset is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Preset non trovato")
        cfg = preset.config
        cfg.new_per_day = body.new_per_day
        cfg.reviews_per_day = body.reviews_per_day
        cfg.learn_steps[:] = body.learn_steps_min
        cfg.relearn_steps[:] = body.relearn_steps_min
        cfg.cap_answer_time_to_secs = body.max_answer_seconds
        cfg.bury_new = body.bury_new_siblings
        cfg.bury_reviews = body.bury_review_siblings
        if upd.fsrs and body.desired_retention is not None:
            cfg.desired_retention = body.desired_retention

        lim = upd.current_deck.limits
        dl = body.deck_limits
        # Campo assente = limite del preset. «Solo oggi» il backend di Anki lo lega al giorno
        # corrente: domani torna da sé al limite normale (i flag `*_active` sono solo in lettura).
        for field, value in (
            ("new", dl.new),
            ("review", dl.review),
            ("new_today", dl.new_today),
            ("review_today", dl.review_today),
        ):
            if value is None:
                lim.ClearField(field)
            else:
                setattr(lim, field, value)

        col.decks.update_deck_configs(
            UpdateDeckConfigs(
                target_deck_id=deck_id,
                # il mazzo prende l'ultimo preset dell'elenco: qui l'unico
                configs=[preset],
                removed_config_ids=[],
                mode=UpdateDeckConfigsMode.UPDATE_DECK_CONFIGS_MODE_NORMAL,
                card_state_customizer=upd.card_state_customizer,
                limits=lim,
                new_cards_ignore_review_limit=body.new_cards_ignore_review_limit,
                apply_all_parent_limits=body.apply_all_parent_limits,
                fsrs=upd.fsrs,
                fsrs_reschedule=False,
                fsrs_health_check=upd.fsrs_health_check,
            )
        )
        out = _options_out(col, deck_id, col.decks.get(deck_id))
    sync.request_soon()
    return out


@router.post("/decks/{deck_id}/extend-limits", response_model=StudyState)
def extend_limits(
    deck_id: int, body: ExtendLimitsIn, manager: CollectionManager = Depends(get_manager)
):
    """"Studia altre N carte oggi": alza i limiti di oggi solo per questo mazzo,
    come lo studio personalizzato di Anki, e restituisce la carta successiva."""
    with manager.use() as col:
        deck = _deck_or_404(col, deck_id)
        if deck.get("dyn"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Non vale per i mazzi filtrati")
        _select_deck(col, deck_id)
        col.sched.extend_limits(body.new, body.review)
        return _state(col)
