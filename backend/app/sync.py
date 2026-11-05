"""Sincronizzazione con AnkiWeb (o un sync server compatibile) tramite il backend di Anki.

Concorrenza, in breve:

- `_run_lock` garantisce **una sola sync alla volta** (manuale, automatica o completa).
- La collezione resta bloccata (`manager.use()`) solo per la parte che la tocca davvero:
  il controllo iniziale `sync_status` è una chiamata di rete che il backend Rust fa
  senza bloccare la collezione, quindi la facciamo fuori dal lock; i media si
  sincronizzano in background nel backend e non bloccano niente.
- Lo stato ("sync in corso", avanzamento) vive in campi propri protetti da
  `_state_lock`, così `GET /api/sync` risponde subito anche durante una full sync.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path

from anki.collection import Collection
from anki.errors import NetworkError, SyncError, SyncErrorKind
from anki.sync_pb2 import SyncAuth, SyncCollectionResponse, SyncStatusResponse

from .collection import CollectionManager
from .logging_setup import register_secret

log = logging.getLogger(__name__)

Required = SyncCollectionResponse.ChangesRequired
StatusRequired = SyncStatusResponse.Required

# Caratteri di isolamento bidi che Anki mette nelle stringhe tradotte ("Checked: ⁨18⁩")
_BIDI = str.maketrans("", "", "⁨⁩")


class SyncOutcome(StrEnum):
    NO_CHANGES = "no_changes"
    SYNCED = "synced"
    FULL_DOWNLOAD = "full_download"
    FULL_UPLOAD = "full_upload"
    FULL_SYNC_REQUIRED = "full_sync_required"
    NOT_LOGGED_IN = "not_logged_in"
    ERROR = "error"


class ErrorKind(StrEnum):
    NETWORK = "network"  # offline, timeout, DNS: si riprova
    AUTH = "auth"  # chiave revocata o scaduta: serve un nuovo login
    SERVER = "server"  # AnkiWeb ha rifiutato la sync (messaggio da mostrare)
    REFUSED = "refused"  # rifiutata da noi per proteggere i dati
    OTHER = "other"


@dataclass
class SyncResult:
    outcome: SyncOutcome
    finished_at: float = field(default_factory=time.time)
    server_message: str = ""
    error: str | None = None
    error_kind: ErrorKind | None = None


@dataclass
class StoredAuth:
    username: str
    hkey: str
    # endpoint attuale: AnkiWeb può spostare l'account su un altro shard
    endpoint: str | None = None
    # server configurato al momento del login (None = AnkiWeb): se cambia
    # ANKI_SYNC_ENDPOINT la chiave non vale più e serve un nuovo login
    server: str | None = None


class SyncService:
    def __init__(
        self,
        manager: CollectionManager,
        auth_path: Path,
        *,
        endpoint: str | None = None,
        backup_dir: Path | None = None,
        io_timeout_secs: int | None = None,
    ) -> None:
        self.manager = manager
        self.auth_path = auth_path
        self.endpoint = normalize_endpoint(endpoint)
        self.backup_dir = backup_dir
        self.io_timeout_secs = io_timeout_secs

        self._run_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._running: str | None = None
        self._running_since: float | None = None
        self.last_result: SyncResult | None = None
        self.next_auto_sync_at: float | None = None
        self.auto_failures = 0

        self._auth: StoredAuth | None = self._load_auth()
        if self._auth:
            register_secret(self._auth.hkey)
            if self._auth.server != self.endpoint:
                log.warning(
                    "Collegamento salvato per un altro server di sync: serve un nuovo login",
                    extra={"saved_server": self._auth.server or "ankiweb",
                           "configured_server": self.endpoint or "ankiweb"},
                )

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
        register_secret(auth.hkey)
        self.auth_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.auth_path.with_suffix(".tmp")
        # 0600 fin dalla creazione: la chiave non deve mai essere leggibile da altri
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(asdict(auth), f)
        tmp.replace(self.auth_path)

    @property
    def logged_in(self) -> bool:
        return self._auth is not None and self._auth.server == self.endpoint

    @property
    def endpoint_mismatch(self) -> bool:
        return self._auth is not None and self._auth.server != self.endpoint

    @property
    def username(self) -> str | None:
        return self._auth.username if self.logged_in and self._auth else None

    def _sync_auth(self, io_timeout_secs: int | None = None) -> SyncAuth:
        assert self._auth is not None
        kwargs: dict = {"hkey": self._auth.hkey}
        endpoint = self._auth.endpoint or self.endpoint
        if endpoint:
            kwargs["endpoint"] = endpoint
        timeout = io_timeout_secs or self.io_timeout_secs
        if timeout:
            kwargs["io_timeout_secs"] = timeout
        return SyncAuth(**kwargs)

    def login(self, username: str, password: str) -> None:
        """Il login è solo rete: non serve bloccare la collezione."""
        register_secret(password)
        col = self.manager.col
        auth = col.sync_login(username=username, password=password, endpoint=self.endpoint)
        self._save_auth(
            StoredAuth(
                username=username,
                hkey=auth.hkey,
                endpoint=auth.endpoint or None,
                server=self.endpoint,
            )
        )
        log.info("Login di sync riuscito", extra={"server": self.endpoint or "ankiweb"})

    def logout(self) -> None:
        self._save_auth(None)

    # ---- stato -----------------------------------------------------------

    @property
    def running(self) -> str | None:
        with self._state_lock:
            return self._running

    @property
    def running_since(self) -> float | None:
        with self._state_lock:
            return self._running_since

    @property
    def full_sync_required(self) -> bool:
        r = self.last_result
        return r is not None and r.outcome == SyncOutcome.FULL_SYNC_REQUIRED

    def _set_running(self, kind: str | None) -> None:
        with self._state_lock:
            self._running = kind
            self._running_since = time.time() if kind else None

    def progress(self) -> dict | None:
        """Avanzamento della sync in corso, letto dal backend senza bloccare la collezione."""
        if not self.running:
            return None
        col = self.manager.peek()
        if col is None:
            return None
        try:
            p = col.latest_progress()
        except Exception:  # noqa: BLE001 - è solo informativo
            return None
        kind = p.WhichOneof("value")
        if kind == "full_sync":
            return {
                "kind": "full_sync",
                "transferred": p.full_sync.transferred,
                "total": p.full_sync.total,
            }
        if kind == "normal_sync":
            return {
                "kind": "normal_sync",
                "stage": p.normal_sync.stage.translate(_BIDI),
                "added": p.normal_sync.added.translate(_BIDI),
                "removed": p.normal_sync.removed.translate(_BIDI),
            }
        return None

    def media_status(self) -> dict:
        col = self.manager.peek()
        if col is None:
            return {"active": False, "error": None}
        try:
            status = col.media_sync_status()
            return {
                "active": status.active,
                "checked": status.progress.checked.translate(_BIDI),
                "added": status.progress.added.translate(_BIDI),
                "removed": status.progress.removed.translate(_BIDI),
                "error": None,
            }
        except Exception as e:  # noqa: BLE001 - media_sync_status lancia se la sync è fallita
            return {"active": False, "error": str(e)}

    # ---- sync ------------------------------------------------------------

    def sync(
        self, *, wait: bool = True, quick: bool = False, io_timeout_secs: int | None = None
    ) -> SyncResult | None:
        """Sync normale. Gestisce da sola i full sync "ovvi" (un lato vuoto).

        - `wait=False`: se c'è già una sync in corso restituisce None (sync automatica);
          con `wait=True` aspetta che finisca e poi ne fa una sua, di solito senza niente da fare.
        - `quick=True`: prima un controllo leggero che non blocca la collezione; se né
          il server né AnkiWeb hanno modifiche si ferma lì. Il backend tiene in cache la
          risposta di AnkiWeb per qualche minuto, quindi va bene per la sync automatica
          e per lo spegnimento, non per il pulsante "Sincronizza".
        """
        if not self._run_lock.acquire(blocking=wait):
            return None
        try:
            if not self.logged_in:
                return self._record(self._not_logged_in())
            self._set_running("normal")
            return self._record(self._sync_locked(quick, io_timeout_secs))
        finally:
            self._set_running(None)
            self._run_lock.release()

    def _not_logged_in(self) -> SyncResult:
        if self.endpoint_mismatch:
            return SyncResult(
                SyncOutcome.NOT_LOGGED_IN,
                error="Il server di sync è cambiato: rifai il login",
                error_kind=ErrorKind.AUTH,
            )
        return SyncResult(SyncOutcome.NOT_LOGGED_IN)

    def _sync_locked(self, quick: bool, io_timeout_secs: int | None) -> SyncResult:
        try:
            if quick:
                auth = self._sync_auth(io_timeout_secs)
                # rete senza lock: lo studio continua mentre aspettiamo AnkiWeb
                status = self.manager.col.sync_status(auth)
                self._maybe_update_endpoint(status.new_endpoint)
                if status.required == StatusRequired.NO_CHANGES:
                    # collezione allineata, ma ci possono essere media da scambiare
                    self.manager.col.sync_media(self._sync_auth(io_timeout_secs))
                    return SyncResult(SyncOutcome.NO_CHANGES)

            # sync vera: il backend blocca comunque la collezione per tutta la durata
            with self.manager.use(timeout=None) as col:
                before = _stamps(col)
                out = col.sync_collection(self._sync_auth(io_timeout_secs), sync_media=True)
                self._maybe_update_endpoint(out.new_endpoint)
                auth = self._sync_auth(io_timeout_secs)

                if out.required == Required.FULL_DOWNLOAD:
                    # il server non ha dati da perdere (collezione vuota)
                    self._set_running("full_download")
                    self._full(col, auth, upload=False, server_usn=out.server_media_usn)
                    outcome = SyncOutcome.FULL_DOWNLOAD
                elif out.required == Required.FULL_UPLOAD:
                    # AnkiWeb è vuoto: caricare non sovrascrive niente
                    self._set_running("full_upload")
                    self._full(col, auth, upload=True, server_usn=out.server_media_usn)
                    outcome = SyncOutcome.FULL_UPLOAD
                elif out.required == Required.FULL_SYNC:
                    # divergenza vera: decide l'utente con /sync/full
                    outcome = SyncOutcome.FULL_SYNC_REQUIRED
                else:
                    # dopo una sync normale `required` dice cosa RESTA da fare (niente):
                    # per sapere se è cambiato qualcosa guardiamo i timestamp di sync
                    outcome = (
                        SyncOutcome.SYNCED if _stamps(col) != before else SyncOutcome.NO_CHANGES
                    )
            return SyncResult(outcome, server_message=out.server_message)
        except Exception as e:  # noqa: BLE001 - riportiamo l'errore alla PWA
            return self._error(e, "Sync fallita")

    def full_sync(self, upload: bool) -> SyncResult:
        """Risolve un conflitto scegliendo quale lato tenere. Solo su richiesta esplicita."""
        with self._run_lock:
            if not self.logged_in:
                return self._record(self._not_logged_in())
            self._set_running("full_upload" if upload else "full_download")
            try:
                with self.manager.use(timeout=None) as col:
                    if upload and col.card_count() == 0:
                        # caricare una collezione vuota cancellerebbe AnkiWeb: quasi
                        # sempre è un errore (es. server appena installato)
                        return self._record(
                            SyncResult(
                                SyncOutcome.ERROR,
                                error="La collezione del server è vuota: caricarla "
                                "cancellerebbe quella di AnkiWeb. Scegli il download.",
                                error_kind=ErrorKind.REFUSED,
                            )
                        )
                    self._full(col, self._sync_auth(), upload=upload, server_usn=None)
                outcome = SyncOutcome.FULL_UPLOAD if upload else SyncOutcome.FULL_DOWNLOAD
                return self._record(SyncResult(outcome))
            except Exception as e:  # noqa: BLE001
                return self._record(self._error(e, "Sync completa fallita"))
            finally:
                self._set_running(None)

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Aspetta la fine della sync in corso (usato allo spegnimento)."""
        if not self._run_lock.acquire(timeout=-1 if timeout is None else timeout):
            return False
        self._run_lock.release()
        return True

    def backup(self, *, force: bool) -> bool:
        """Backup .colpkg della collezione (senza media) con la rotazione di Anki."""
        if self.backup_dir is None:
            return False
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        with self.manager.use(timeout=None) as col:
            return col.create_backup(
                backup_folder=str(self.backup_dir), force=force, wait_for_completion=True
            )

    # ---- interni ---------------------------------------------------------

    def _full(self, col: Collection, auth: SyncAuth, *, upload: bool, server_usn: int | None) -> None:
        if not upload and col.card_count() > 0:
            # il download sostituisce la collezione del server: prima una copia
            # (create_backup lancia se fallisce, e allora non scarichiamo niente)
            if self.backup_dir is not None:
                self.backup_dir.mkdir(parents=True, exist_ok=True)
                col.create_backup(
                    backup_folder=str(self.backup_dir), force=True, wait_for_completion=True
                )
                log.info("Backup creato prima del download completo")
        # Stessa sequenza di Anki desktop (aqt/sync.py). Se il trasferimento fallisce
        # il backend riapre la collezione com'era, quindi reopen() va chiamato sempre.
        col.close_for_full_sync()
        try:
            col.full_upload_or_download(auth=auth, server_usn=server_usn, upload=upload)
        finally:
            col.reopen(after_full_sync=True)
        if server_usn is None:
            # con server_usn il backend avvia da solo la sync dei media
            col.sync_media(auth)

    def _maybe_update_endpoint(self, new_endpoint: str) -> None:
        if new_endpoint and self._auth and new_endpoint != self._auth.endpoint:
            log.info("Il server di sync ha indicato un nuovo endpoint")
            self._save_auth(
                StoredAuth(
                    self._auth.username, self._auth.hkey, new_endpoint, self._auth.server
                )
            )

    def _error(self, e: Exception, what: str) -> SyncResult:
        if isinstance(e, SyncError) and e.kind == SyncErrorKind.AUTH:
            # chiave revocata (password cambiata, logout da AnkiWeb): si dimentica
            # solo la chiave, la collezione resta intatta
            log.warning("%s: autenticazione rifiutata, serve un nuovo login", what)
            self.logout()
            return SyncResult(SyncOutcome.NOT_LOGGED_IN, error=str(e), error_kind=ErrorKind.AUTH)
        if isinstance(e, NetworkError):
            log.warning("%s: errore di rete: %s", what, e)
            return SyncResult(SyncOutcome.ERROR, error=str(e), error_kind=ErrorKind.NETWORK)
        if isinstance(e, SyncError):
            log.warning("%s: %s", what, e)
            return SyncResult(SyncOutcome.ERROR, error=str(e), error_kind=ErrorKind.SERVER)
        log.exception(what)
        return SyncResult(SyncOutcome.ERROR, error=str(e), error_kind=ErrorKind.OTHER)

    def _record(self, result: SyncResult) -> SyncResult:
        self.last_result = result
        return result


def _stamps(col: Collection) -> tuple:
    # mod = ultima modifica, ls = ultima sync, usn = contatore di sync: cambiano solo
    # se la sync ha davvero scambiato qualcosa
    return tuple(col.db.first("select mod, ls, usn from col"))


def normalize_endpoint(endpoint: str | None) -> str | None:
    """'' e None = AnkiWeb; altrimenti l'URL base con lo slash finale che Anki si aspetta."""
    if not endpoint or not endpoint.strip():
        return None
    endpoint = endpoint.strip()
    return endpoint if endpoint.endswith("/") else endpoint + "/"


def next_auto_delay(result: SyncResult | None, failures: int, interval_s: float) -> tuple[float, int]:
    """Quando riprovare la sync automatica: (secondi, nuovi fallimenti consecutivi).

    Errori temporanei (rete, server) -> backoff esponenziale da 30 s fino all'intervallo.
    Tutto il resto (ok, conflitto da risolvere, non collegato) -> intervallo normale.
    """
    if result is not None and result.outcome == SyncOutcome.ERROR and result.error_kind in (
        ErrorKind.NETWORK,
        ErrorKind.SERVER,
        ErrorKind.OTHER,
    ):
        failures += 1
        return min(interval_s, 30.0 * 2 ** (failures - 1)), failures
    return interval_s, 0
