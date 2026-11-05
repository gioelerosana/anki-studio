"""Gestione della collezione Anki condivisa dal processo.

Il backend Rust di Anki non è pensato per accessi concorrenti, quindi ogni
operazione sulla collezione passa da un unico RLock. Per un uso single-user
(tu e il tuo iPad) è più che sufficiente.

Le rotte aspettano il lock al massimo `busy_timeout` secondi: se nel frattempo
c'è una sync lunga (per esempio il primo download completo da AnkiWeb) è meglio
rispondere 503 "riprova tra poco" che tenere appesa la PWA per minuti.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from anki.collection import Collection

_DEFAULT = object()


class CollectionBusy(Exception):
    """La collezione è occupata (di solito da una sync) oltre il tempo concesso."""


class CollectionManager:
    def __init__(self, path: Path, *, busy_timeout: float = 20.0) -> None:
        self.path = path
        self.busy_timeout = busy_timeout
        self.lock = threading.RLock()
        self._col: Collection | None = None

    def open(self) -> None:
        with self.lock:
            if self._col is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._col = Collection(str(self.path))

    def close(self) -> None:
        with self.lock:
            if self._col is not None:
                self._col.close()
                self._col = None

    @property
    def is_open(self) -> bool:
        return self._col is not None

    @property
    def col(self) -> Collection:
        if self._col is None:
            raise RuntimeError("Collection is not open")
        return self._col

    def peek(self) -> Collection | None:
        """La collezione SENZA lock: solo per chiamate al backend che sono sicure
        in parallelo (avanzamento sync, stato media, rete), mai per leggere o scrivere dati."""
        return self._col

    @contextmanager
    def use(self, timeout: float | None | object = _DEFAULT) -> Iterator[Collection]:
        """Accesso esclusivo. `timeout=None` aspetta per sempre (usato dalla sync)."""
        t = self.busy_timeout if timeout is _DEFAULT else timeout
        if not self.lock.acquire(timeout=-1 if t is None else t):  # type: ignore[arg-type]
            raise CollectionBusy()
        try:
            yield self.col
        finally:
            self.lock.release()
