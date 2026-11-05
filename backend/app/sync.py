"""Sincronizzazione con AnkiWeb tramite il backend ufficiale di Anki."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

from anki.collection import Collection
from anki.errors import SyncError, SyncErrorKind
from anki.sync_pb2 import SyncAuth, SyncCollectionResponse

from .collection import CollectionManager

log = logging.getLogger(__name__)

Required = SyncCollectionResponse.ChangesRequired


class SyncOutcome(StrEnum):
    NO_CHANGES = "no_changes"
    SYNCED = "synced"
    FULL_DOWNLOAD = "full_download"
    FULL_UPLOAD = "full_upload"
    FULL_SYNC_REQUIRED = "full_sync_required"
    NOT_LOGGED_IN = "not_logged_in"
    ERROR = "error"


@dataclass
class SyncResult:
    outcome: SyncOutcome
    finished_at: float = field(default_factory=time.time)
    server_message: str = ""
    error: str | None = None


@dataclass
class StoredAuth:
    username: str
    hkey: str
    endpoint: str | None = None


class FullSyncRequired(Exception):
    """Locale e AnkiWeb sono divergenti: serve scegliere upload o download."""


class SyncService:
    def __init__(self, manager: CollectionManager, auth_path: Path) -> None:
        self.manager = manager
        self.auth_path = auth_path
        self.last_result: SyncResult | None = None
        self._auth: StoredAuth | None = self._load_auth()

    # ---- credenziali -----------------------------------------------------

    def _load_auth(self) -> StoredAuth | None:
        try:
            return StoredAuth(**json.loads(self.auth_path.read_text()))
        except FileNotFoundError:
            return None
        except (ValueError, TypeError):
            log.warning("sync_auth.json non valido, ignorato")
            return None

    def _save_auth(self, auth: StoredAuth | None) -> None:
        self._auth = auth
        if auth is None:
            self.auth_path.unlink(missing_ok=True)
            return
        self.auth_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.auth_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(auth)))
        os.chmod(tmp, 0o600)
        tmp.replace(self.auth_path)

    @property
    def logged_in(self) -> bool:
        return self._auth is not None

    @property
    def username(self) -> str | None:
        return self._auth.username if self._auth else None

    def _sync_auth(self) -> SyncAuth:
        assert self._auth is not None
        kwargs: dict = {"hkey": self._auth.hkey}
        if self._auth.endpoint:
            kwargs["endpoint"] = self._auth.endpoint
        return SyncAuth(**kwargs)

    def login(self, username: str, password: str) -> None:
        with self.manager.use() as col:
            auth = col.sync_login(username=username, password=password, endpoint=None)
        self._save_auth(
            StoredAuth(username=username, hkey=auth.hkey, endpoint=auth.endpoint or None)
        )

    def logout(self) -> None:
        self._save_auth(None)

    # ---- sync ------------------------------------------------------------

    def sync(self) -> SyncResult:
        """Sync normale. Gestisce da solo i full sync "ovvi" (un lato vuoto)."""
        if not self._auth:
            return self._record(SyncResult(SyncOutcome.NOT_LOGGED_IN))
        try:
            with self.manager.use() as col:
                auth = self._sync_auth()
                out = col.sync_collection(auth, sync_media=True)
                self._maybe_update_endpoint(out.new_endpoint)

                if out.required == Required.FULL_DOWNLOAD:
                    self._full(col, upload=False, server_usn=out.server_media_usn)
                    outcome = SyncOutcome.FULL_DOWNLOAD
                elif out.required == Required.FULL_UPLOAD:
                    self._full(col, upload=True, server_usn=out.server_media_usn)
                    outcome = SyncOutcome.FULL_UPLOAD
                elif out.required == Required.FULL_SYNC:
                    outcome = SyncOutcome.FULL_SYNC_REQUIRED
                elif out.required == Required.NORMAL_SYNC:
                    outcome = SyncOutcome.SYNCED
                else:
                    outcome = SyncOutcome.NO_CHANGES
            return self._record(SyncResult(outcome, server_message=out.server_message))
        except SyncError as e:
            if _is_auth_error(e):
                self.logout()
                return self._record(SyncResult(SyncOutcome.NOT_LOGGED_IN, error=str(e)))
            log.exception("Sync fallita")
            return self._record(SyncResult(SyncOutcome.ERROR, error=str(e)))
        except Exception as e:  # noqa: BLE001 - riportiamo l'errore alla PWA
            log.exception("Sync fallita")
            return self._record(SyncResult(SyncOutcome.ERROR, error=str(e)))

    def full_sync(self, upload: bool) -> SyncResult:
        """Risolve un conflitto scegliendo quale lato tenere."""
        if not self._auth:
            return self._record(SyncResult(SyncOutcome.NOT_LOGGED_IN))
        try:
            with self.manager.use() as col:
                self._full(col, upload=upload, server_usn=None)
            outcome = SyncOutcome.FULL_UPLOAD if upload else SyncOutcome.FULL_DOWNLOAD
            return self._record(SyncResult(outcome))
        except Exception as e:  # noqa: BLE001
            log.exception("Full sync fallita")
            return self._record(SyncResult(SyncOutcome.ERROR, error=str(e)))

    def media_status(self) -> dict:
        try:
            with self.manager.use() as col:
                status = col.media_sync_status()
            return {
                "active": status.active,
                "checked": status.progress.checked,
                "added": status.progress.added,
                "removed": status.progress.removed,
                "error": None,
            }
        except Exception as e:  # noqa: BLE001 - media_sync_status lancia se la sync è fallita
            return {"active": False, "error": str(e)}

    # ---- interni ---------------------------------------------------------

    def _full(self, col: Collection, *, upload: bool, server_usn: int | None) -> None:
        # Stessa sequenza usata da Anki desktop (aqt/sync.py).
        col.close_for_full_sync()
        try:
            col.full_upload_or_download(
                auth=self._sync_auth(), server_usn=server_usn, upload=upload
            )
        finally:
            col.reopen(after_full_sync=True)
        if server_usn is None:
            col.sync_media(self._sync_auth())

    def _maybe_update_endpoint(self, new_endpoint: str) -> None:
        if new_endpoint and self._auth and new_endpoint != self._auth.endpoint:
            self._save_auth(
                StoredAuth(self._auth.username, self._auth.hkey, new_endpoint)
            )

    def _record(self, result: SyncResult) -> SyncResult:
        self.last_result = result
        return result


def _is_auth_error(e: SyncError) -> bool:
    return e.kind == SyncErrorKind.AUTH
