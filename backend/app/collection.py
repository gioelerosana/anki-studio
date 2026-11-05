"""Gestione della collezione Anki condivisa dal processo.

Il backend Rust di Anki non è pensato per accessi concorrenti, quindi ogni
operazione sulla collezione passa da un unico RLock. Per un uso single-user
(tu e il tuo iPad) è più che sufficiente.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from anki.collection import Collection


class CollectionManager:
    def __init__(self, path: Path) -> None:
        self.path = path
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
    def col(self) -> Collection:
        if self._col is None:
            raise RuntimeError("Collection is not open")
        return self._col

    @contextmanager
    def use(self) -> Iterator[Collection]:
        with self.lock:
            yield self.col
