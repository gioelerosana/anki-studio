from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status

from anki.errors import SyncError

from ..deps import get_sync
from ..schemas import FullSyncIn, LoginIn, SyncResultOut, SyncStatusOut
from ..sync import SyncOutcome, SyncResult, SyncService

router = APIRouter(prefix="/sync", tags=["sync"])


def _out(r: SyncResult | None) -> SyncResultOut | None:
    return SyncResultOut(**asdict(r)) if r else None


@router.get("", response_model=SyncStatusOut)
def sync_status(sync: SyncService = Depends(get_sync)):
    return SyncStatusOut(
        logged_in=sync.logged_in,
        username=sync.username,
        last_result=_out(sync.last_result),
        media=sync.media_status(),
    )


@router.post("/login", status_code=204)
def login(body: LoginIn, sync: SyncService = Depends(get_sync)):
    """Login ad AnkiWeb. La password non viene salvata, solo la chiave di sessione."""
    try:
        sync.login(body.username, body.password)
    except SyncError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Login AnkiWeb fallito: {e}")


@router.post("/logout", status_code=204)
def logout(sync: SyncService = Depends(get_sync)):
    sync.logout()


@router.post("", response_model=SyncResultOut)
def run_sync(sync: SyncService = Depends(get_sync)):
    """Sync normale. Se AnkiWeb e il server sono divergenti risponde 409:
    la PWA deve chiedere all'utente quale versione tenere e chiamare /sync/full."""
    result = sync.sync()
    if result.outcome == SyncOutcome.NOT_LOGGED_IN:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Non sei collegato ad AnkiWeb")
    if result.outcome == SyncOutcome.FULL_SYNC_REQUIRED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Serve una sync completa: scegli se caricare o scaricare la collezione",
        )
    if result.outcome == SyncOutcome.ERROR:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, result.error or "Sync fallita")
    return _out(result)


@router.post("/full", response_model=SyncResultOut)
def full_sync(body: FullSyncIn, sync: SyncService = Depends(get_sync)):
    """ATTENZIONE: 'download' sostituisce la collezione del server con quella di
    AnkiWeb, 'upload' sovrascrive AnkiWeb con quella del server."""
    result = sync.full_sync(upload=body.direction == "upload")
    if result.outcome == SyncOutcome.NOT_LOGGED_IN:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Non sei collegato ad AnkiWeb")
    if result.outcome == SyncOutcome.ERROR:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, result.error or "Sync fallita")
    return _out(result)
