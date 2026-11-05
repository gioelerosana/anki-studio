"""Helper per i test di sync: un sync server locale e un "Anki desktop" finto.

Il pacchetto `anki` include lo stesso sync server che si può self-hostare
(`python -m anki.syncserver`): parla lo stesso protocollo di AnkiWeb, quindi i
test esercitano il percorso vero senza toccare la rete.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from anki.collection import Collection
from anki.sync_pb2 import SyncAuth, SyncCollectionResponse

Required = SyncCollectionResponse.ChangesRequired


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class SyncServer:
    def __init__(self, base: Path, users: dict[str, str]) -> None:
        self.base = base
        self.users = users
        self.port = free_port()
        self.proc: subprocess.Popen | None = None
        self.log = base.parent / "syncserver.log"

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def start(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("SYNC_")}
        env.update(
            SYNC_BASE=str(self.base),
            SYNC_HOST="127.0.0.1",
            SYNC_PORT=str(self.port),
            RUST_LOG="warn",
        )
        for i, (user, pw) in enumerate(self.users.items(), start=1):
            env[f"SYNC_USER{i}"] = f"{user}:{pw}"
        self.base.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "anki.syncserver"],
            env=env,
            stdout=self.log.open("ab"),
            stderr=subprocess.STDOUT,
        )
        deadline = time.time() + 15
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"sync server terminato: {self.log.read_text()}")
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("sync server non partito")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def restart(self, users: dict[str, str] | None = None) -> None:
        self.stop()
        if users is not None:
            self.users = users
        self.start()


class Desktop:
    """Un secondo client (come Anki desktop o AnkiMobile) sullo stesso account."""

    def __init__(self, path: Path, endpoint: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.col = Collection(str(path))
        self.endpoint = endpoint
        self.auth: SyncAuth | None = None

    def login(self, user: str, password: str) -> None:
        a = self.col.sync_login(user, password, self.endpoint)
        self.auth = SyncAuth(hkey=a.hkey, endpoint=self.endpoint)

    def sync(self, on_conflict: str = "fail") -> str:
        """Sync come fa aqt/sync.py. on_conflict: 'fail' | 'upload' | 'download'."""
        assert self.auth is not None
        before = self.col.db.first("select mod, ls, usn from col")
        out = self.col.sync_collection(self.auth, sync_media=True)
        req = out.required
        if req == Required.FULL_SYNC:
            if on_conflict == "fail":
                return "conflict"
            req = Required.FULL_UPLOAD if on_conflict == "upload" else Required.FULL_DOWNLOAD
        if req in (Required.FULL_UPLOAD, Required.FULL_DOWNLOAD):
            self.col.close_for_full_sync()
            try:
                self.col.full_upload_or_download(
                    auth=self.auth,
                    server_usn=out.server_media_usn,
                    upload=req == Required.FULL_UPLOAD,
                )
            finally:
                self.col.reopen(after_full_sync=True)
        self.wait_media()
        if req == Required.FULL_UPLOAD:
            return "full_upload"
        if req == Required.FULL_DOWNLOAD:
            return "full_download"
        # dopo una sync normale `required` è NO_CHANGES: contano i timestamp
        after = self.col.db.first("select mod, ls, usn from col")
        return "synced" if after != before else "no_changes"

    def wait_media(self, timeout: float = 15) -> None:
        deadline = time.time() + timeout
        while self.col.media_sync_status().active:
            if time.time() > deadline:
                raise TimeoutError("sync media del desktop non finita")
            time.sleep(0.05)

    def media_files(self) -> set[str]:
        return set(os.listdir(self.col.media.dir()))

    def close(self) -> None:
        self.col.close()
