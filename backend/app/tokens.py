"""Token per gli agenti (Claude, Hermes Agent, script): `ask_` + 32 byte casuali.

Sul disco resta solo l'hash SHA-256 (`<data>/tokens.json`, 0600, scrittura atomica come
`sync_auth.json`): il token in chiaro si vede una volta sola, alla creazione, e non si
può recuperare. Un hash veloce basta perché il token è casuale a 256 bit, non una
password scelta da una persona: non c'è niente da "indovinare" a forza bruta.

Ogni token ha un `scope` (`read` | `write`) e `review` (le sue note nascono bozza).
Il nome diventa lo slug del tag di provenienza `agent::<slug>`, per questo gli slug
sono unici e il nome non si cambia dopo la creazione.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from .logging_setup import register_secret

log = logging.getLogger(__name__)

TOKEN_PREFIX = "ask_"
# `last_used_at` si tiene in memoria a ogni uso, ma su disco si riscrive al massimo così
# spesso: un agente che fa cento richieste non deve riscrivere il file cento volte
_PERSIST_EVERY_S = 60

Scope = Literal["read", "write"]


class TokenError(Exception):
    """Errore di validazione (nome senza lettere né cifre)."""


class TokenNameTaken(TokenError):
    """Lo slug del nome (la provenienza `agent::<slug>`) è già di un altro token."""


def agent_slug(name: str) -> str:
    """Nome → slug `a-z0-9-` per il tag `agent::<slug>` ("Hermes Agent" → "hermes-agent")."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class StoredToken:
    id: str
    name: str
    scope: Scope
    review: bool
    hash: str
    created_at: int
    last_used_at: int | None = None

    @property
    def slug(self) -> str:
        return agent_slug(self.name)


class TokenStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._tokens: list[StoredToken] = self._load()
        self._persisted_at: dict[str, float] = {}

    # ---- disco -------------------------------------------------------------

    def _load(self) -> list[StoredToken]:
        try:
            raw = json.loads(self.path.read_text())
            return [StoredToken(**t) for t in raw["tokens"]]
        except FileNotFoundError:
            return []
        except (ValueError, TypeError, KeyError):
            # niente cancellazioni: il file resta com'è, ma senza token validi nessuno entra
            log.warning("tokens.json non valido, ignorato")
            return []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        # 0600 fin dalla creazione, come sync_auth.json
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"tokens": [asdict(t) for t in self._tokens]}, f)
        tmp.replace(self.path)

    # ---- gestione ----------------------------------------------------------

    def all(self) -> list[StoredToken]:
        with self._lock:
            return list(self._tokens)

    def get(self, token_id: str) -> StoredToken | None:
        with self._lock:
            return next((t for t in self._tokens if t.id == token_id), None)

    def create(self, name: str, scope: Scope, review: bool) -> tuple[StoredToken, str]:
        """Restituisce il token salvato e quello in chiaro (da mostrare una volta sola)."""
        name = name.strip()
        slug = agent_slug(name)
        if not slug:
            raise TokenError("Il nome deve contenere almeno una lettera o una cifra")
        plain = TOKEN_PREFIX + secrets.token_urlsafe(32)
        register_secret(plain)
        with self._lock:
            if any(t.slug == slug for t in self._tokens):
                # lo slug è la provenienza (`agent::<slug>`): due token con lo stesso
                # slug potrebbero modificare le note l'uno dell'altro
                raise TokenNameTaken(f"Esiste già un token con il nome «{slug}»")
            token = StoredToken(
                id=secrets.token_hex(6),
                name=name,
                scope=scope,
                review=review,
                hash=hash_token(plain),
                created_at=int(time.time()),
            )
            self._tokens.append(token)
            self._save()
        log.info("Token creato", extra={"token_id": token.id, "agent": slug, "scope": scope})
        return token, plain

    def update(self, token_id: str, *, scope: Scope | None, review: bool | None) -> StoredToken | None:
        with self._lock:
            token = next((t for t in self._tokens if t.id == token_id), None)
            if token is None:
                return None
            if scope is not None:
                token.scope = scope
            if review is not None:
                token.review = review
            self._save()
            return token

    def revoke(self, token_id: str) -> bool:
        with self._lock:
            kept = [t for t in self._tokens if t.id != token_id]
            if len(kept) == len(self._tokens):
                return False
            self._tokens = kept
            self._save()
        log.info("Token revocato", extra={"token_id": token_id})
        return True

    # ---- verifica ----------------------------------------------------------

    def verify(self, plain: str) -> StoredToken | None:
        """Il token se `plain` è valido. Confronto a tempo costante su tutti gli hash:
        non si esce al primo che corrisponde, così il tempo non dice quale posizione era."""
        digest = hash_token(plain)
        found: StoredToken | None = None
        with self._lock:
            for t in self._tokens:
                if hmac.compare_digest(t.hash, digest):
                    found = t
            if found is not None:
                self._touch(found)
        return found

    def _touch(self, token: StoredToken) -> None:
        now = time.time()
        token.last_used_at = int(now)
        if now - self._persisted_at.get(token.id, 0) >= _PERSIST_EVERY_S:
            self._persisted_at[token.id] = now
            try:
                self._save()
            except OSError:  # l'uso del token non deve fallire per un disco pieno
                log.warning("Impossibile salvare last_used_at", exc_info=True)
