from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Request, status

from anki.errors import NetworkError, SyncError

from ..deps import get_sync
from ..schemas import FullSyncIn, LoginIn, SyncResultOut, SyncStatusOut
from ..security import check_login_rate, record_login_attempt
from ..sync import SyncOutcome, SyncResult, SyncService

router = APIRouter(prefix="/sync", tags=["sync"])


def _out(r: SyncResult | None) -> SyncResultOut | None:
    return SyncResultOut(**asdict(r)) if r else None


@router.get("", response_model=SyncStatusOut)
def sync_status(sync: SyncService = Depends(get_sync)):
    """Risponde subito anche durante una sync (non aspetta la collezione)."""
    return SyncStatusOut(
        logged_in=sync.logged_in,
        username=sync.username,
        last_result=_out(sync.last_result),
        media=sync.media_status(),
        running=sync.running,
        running_since=sync.running_since,
        progress=sync.progress(),
        full_sync_required=sync.full_sync_required,
        endpoint=sync.endpoint,
        endpoint_mismatch=sync.endpoint_mismatch,
        next_auto_sync_at=sync.next_auto_sync_at,
        auto_sync_failures=sync.auto_failures,
    )


@router.post("/login", status_code=204, dependencies=[Depends(check_login_rate)])
def login(request: Request, body: LoginIn, sync: SyncService = Depends(get_sync)):
    """Login ad AnkiWeb. La password non viene salvata, solo la chiave di sessione."""
    try:
        sync.login(body.username, body.password)
    except NetworkError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"AnkiWeb non raggiungibile: {e}")
    except SyncError as e:
        record_login_attempt(request, ok=False)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Login AnkiWeb fallito: {e}")
    record_login_attempt(request, ok=True)


@router.post("/logout", status_code=204)
def logout(sync: SyncService = Depends(get_sync)):
    sync.logout()


def _raise_for(result: SyncResult) -> SyncResultOut:
    if result.outcome == SyncOutcome.NOT_LOGGED_IN:
        detail = (
            "La chiave di AnkiWeb non è più valida: rifai il login"
            if result.error_kind == "auth"
            else "Non sei collegato ad AnkiWeb"
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail)
    if result.outcome == SyncOutcome.FULL_SYNC_REQUIRED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Serve una sync completa: scegli se caricare o scaricare la collezione",
        )
    if result.outcome == SyncOutcome.ERROR:
        code = (
            status.HTTP_409_CONFLICT
            if result.error_kind == "refused"
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(code, result.error or "Sync fallita")
    return _out(result)  # type: ignore[return-value]


@router.post("", response_model=SyncResultOut)
def run_sync(sync: SyncService = Depends(get_sync)):
    """Sync normale. Se AnkiWeb e il server sono divergenti risponde 409:
    la PWA deve chiedere all'utente quale versione tenere e chiamare /sync/full.
    Se c'è già una sync in corso aspetta che finisca."""
    result = sync.sync()
    assert result is not None
    return _raise_for(result)


@router.post("/full", response_model=SyncResultOut)
def full_sync(body: FullSyncIn, sync: SyncService = Depends(get_sync)):
    """ATTENZIONE: 'download' sostituisce la collezione del server con quella di
    AnkiWeb (prima ne fa un backup in data/backups), 'upload' sovrascrive AnkiWeb
    con quella del server. Va chiamata solo dopo una conferma esplicita dell'utente."""
    return _raise_for(sync.full_sync(upload=body.direction == "upload"))
