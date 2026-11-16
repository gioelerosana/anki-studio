"""Ponte del telecomando: l'app desktop si fa comandare dal telefono attraverso il server.

Il telefono apre il server (anki.jshep.xyz), l'app desktop ha un backend suo su 127.0.0.1 con
una copia locale della collezione: i due relay di app/remote.py non si vedono. Invece di una
sync fra istanze (la sync resta quella di Anki con AnkiWeb), il backend del desktop apre una
connessione **in uscita** verso `/api/remote?role=screen` del server e ci fa passare la propria
schermata:

    telefono ──WS──▶ server /api/remote ◀──WS in uscita── backend del desktop ◀── PWA desktop

- verso il server: lo stato dello schermo attivo locale (`RemoteHub.on_active_state`), con i
  passaggi in primo piano (`claim`) e `source = "desktop"`;
- dal server: i `command` del telefono, consegnati alla schermata locale con
  `RemoteHub.command`, come se li mandasse un telecomando locale; e il numero di telefoni
  (`remotes`), così la PWA desktop sa che un telecomando è collegato.

Il relay del server non tocca la collezione, quindi anche il ponte non la tocca: niente lock.
Tutto gira nell'event loop dell'app (le rotte qui sotto sono `async` come quelle di remote.py).

Accesso: un token `ask_…` con scope `remote`, che il server accetta solo per fare da schermo
(app/security.websocket_session) e per nient'altro. Il token sta in `remote_bridge.json` nella
cartella dati (0600, scrittura atomica come tokens.json), non torna mai alla PWA (che sa solo
se c'è) e non compare nei log (register_secret, e il logger di `websockets` sta zitto).

Rete che va e viene: si ricollega da solo con attesa esponenziale e jitter (1 s → 30 s). Un
handshake rifiutato (401/403: token sbagliato o revocato) aspetta di più, 5 minuti, perché i
Bearer sbagliati contano per il limite ai tentativi del server: un ponte che ritenta a raffica
farebbe bloccare l'IP di casa. Salvare di nuovo la configurazione riparte subito. Senza rete il
desktop resta usabile come sempre: il ponte è un di più.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import random
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException

from .config import Settings, get_settings
from .logging_setup import register_secret
from .remote import RemoteHub
from .schemas import RemoteBridgeIn, RemoteBridgeStatus, RemoteCommand
from .security import _bearer, desktop_identity, require_auth
from .tokens import TOKEN_PREFIX

log = logging.getLogger(__name__)
# Il logger della libreria scrive gli header dell'handshake in DEBUG, Authorization compresa: il
# filtro dei segreti la oscurerebbe comunque, ma è meglio che non ci arrivi proprio.
_ws_log = logging.getLogger("anki_studio.remote_bridge.ws")
_ws_log.setLevel(logging.WARNING)

MIN_DELAY_S = 1.0
MAX_DELAY_S = 30.0
REJECTED_DELAY_S = 300.0
OPEN_TIMEOUT_S = 10.0
# un messaggio del server è piccolo (stato, comando); un tetto evita sorprese in memoria
MAX_MESSAGE_BYTES = 1024 * 1024


class BridgeConfigError(ValueError):
    """Configurazione non valida (URL o token): il messaggio va all'utente così com'è."""


def normalize_server_url(url: str) -> str:
    """`https://anki.jshep.xyz/` → `https://anki.jshep.xyz`. Solo https, tranne verso questa
    stessa macchina (prove in locale): il token viaggia nell'header, in chiaro non deve uscire."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise BridgeConfigError("Indirizzo del server non valido: deve iniziare con https://")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise BridgeConfigError("Indirizzo del server non valido: solo https://host[:porta]")
    if parts.scheme == "http" and not _is_loopback(parts.hostname):
        raise BridgeConfigError("Serve https://: il token non può viaggiare in chiaro")
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}"


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def websocket_url(server_url: str, screen_id: str) -> str:
    scheme = "wss" if server_url.startswith("https://") else "ws"
    rest = server_url.split("://", 1)[1]
    return f"{scheme}://{rest}/api/remote?role=screen&screen_id={quote(screen_id)}"


def _new_screen_id() -> str:
    # stesso formato degli id delle schede (`^[A-Za-z0-9-]{8,64}$`, app/remote.py)
    return f"desktop-{secrets.token_hex(12)}"


@dataclass
class BridgeConfig:
    server_url: str | None = None
    token: str | None = None
    enabled: bool = False
    # stabile per installazione: una riconnessione sostituisce la connessione vecchia sul
    # server (CLOSE_REPLACED) invece di lasciare due schermi uguali
    screen_id: str = field(default_factory=_new_screen_id)

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.server_url and self.token)


class RemoteBridge:
    def __init__(
        self,
        hub: RemoteHub,
        path: Path,
        *,
        min_delay: float = MIN_DELAY_S,
        max_delay: float = MAX_DELAY_S,
        rejected_delay: float = REJECTED_DELAY_S,
    ) -> None:
        self.hub = hub
        self.path = path
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.rejected_delay = rejected_delay
        self.config = self._load()
        register_secret(self.config.token)
        self._task: asyncio.Task[None] | None = None
        self._wake: asyncio.Event | None = None
        # l'ultimo stato locale e se nel frattempo c'è stato un passaggio in primo piano
        self._state: dict[str, Any] | None = None
        self._claim = False
        self._status = "off"
        self._last_error: str | None = None
        self._connected_at: float | None = None
        self._retry_at: float | None = None

    # ---- disco -------------------------------------------------------------

    def _load(self) -> BridgeConfig:
        try:
            raw = json.loads(self.path.read_text())
            config = BridgeConfig(
                server_url=raw.get("server_url"),
                token=raw.get("token"),
                enabled=bool(raw.get("enabled")),
                screen_id=str(raw.get("screen_id") or _new_screen_id()),
            )
        except FileNotFoundError:
            return BridgeConfig()
        except (ValueError, TypeError, AttributeError, OSError):
            # niente contenuto nel log: c'è il token
            log.warning("remote_bridge.json non leggibile: ponte del telecomando da configurare")
            return BridgeConfig()
        return config

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(asdict(self.config), f)
        tmp.replace(self.path)

    # ---- ciclo di vita -----------------------------------------------------

    async def start(self) -> None:
        """Nel lifespan dell'app: ascolta lo schermo attivo e, se configurato, si collega."""
        self._wake = asyncio.Event()
        self.hub.on_active_state = self._local_state
        self._state = self.hub.current_state()
        self._restart()

    async def stop(self) -> None:
        if self.hub.on_active_state == self._local_state:
            self.hub.on_active_state = None
        await self._cancel()

    async def configure(self, server_url: str, token: str | None, enabled: bool) -> None:
        url = normalize_server_url(server_url)
        if token is not None:
            token = token.strip()
            if not token.startswith(TOKEN_PREFIX):
                raise BridgeConfigError(
                    "Token non valido: crealo sul server (Impostazioni → Agenti, «Solo telecomando»)"
                )
            register_secret(token)
        if enabled and not (token or self.config.token):
            raise BridgeConfigError("Incolla il token creato sul server")
        self.config.server_url = url
        if token is not None:
            self.config.token = token
        self.config.enabled = enabled
        self._save()
        await self._cancel()
        self._restart()

    async def forget(self) -> None:
        """Scollega e dimentica il token (l'URL resta, è comodo per ricollegarsi)."""
        self.config.token = None
        self.config.enabled = False
        self._save()
        await self._cancel()

    def _restart(self) -> None:
        self._last_error = None
        self._retry_at = None
        if self.config.ready:
            self._status = "connecting"
            self._task = asyncio.create_task(self._run(), name="remote-bridge")
            log.info(
                "Ponte del telecomando attivo",
                extra={"server": urlsplit(self.config.server_url or "").netloc},
            )
        else:
            self._status = "off"

    async def _cancel(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._status = "off"
        self._connected_at = None
        self._retry_at = None
        await self.hub.set_bridged_remotes(0)

    def status(self) -> RemoteBridgeStatus:
        return RemoteBridgeStatus(
            server_url=self.config.server_url,
            token_set=bool(self.config.token),
            enabled=self.config.enabled,
            status=self._status,  # type: ignore[arg-type]
            last_error=self._last_error,
            connected_at=int(self._connected_at) if self._connected_at else None,
            retry_at=int(self._retry_at) if self._retry_at else None,
            remotes=self.hub.bridged_remotes,
        )

    # ---- stato locale → server ----------------------------------------------

    def _local_state(self, state: dict[str, Any] | None, claim: bool) -> None:
        self._state = state
        self._claim = self._claim or claim
        if self._wake is not None:
            self._wake.set()

    async def _send_loop(self, ws: Any) -> None:
        last: str | None = None
        # alla connessione: se la finestra era già in primo piano, il telefono passa a lei
        self._claim = self._claim or self.hub.ever_claimed()
        assert self._wake is not None
        self._wake.set()
        while True:
            await self._wake.wait()
            self._wake.clear()
            state = None if self._state is None else {**self._state, "source": "desktop"}
            claim, self._claim = self._claim, False
            body = json.dumps(state, sort_keys=True)
            if body == last and not claim:
                continue
            await ws.send(json.dumps({"type": "state", "state": state, "claim": claim}))
            last = body

    # ---- server → schermata locale ------------------------------------------

    async def _handle(self, raw: str | bytes) -> None:
        try:
            data = json.loads(raw)
        except ValueError:
            return
        if not isinstance(data, dict):
            return
        kind = data.get("type")
        if kind == "command":
            try:
                command = RemoteCommand.model_validate(data.get("command"))
            except ValidationError:
                log.warning("Comando del telecomando non valido dal server: ignorato")
                return
            await self.hub.command(command)
        elif kind == "remotes" and isinstance(data.get("count"), int):
            await self.hub.set_bridged_remotes(max(0, data["count"]))

    # ---- connessione --------------------------------------------------------

    async def _run(self) -> None:
        failures = 0
        url = websocket_url(self.config.server_url or "", self.config.screen_id)
        host = urlsplit(url).netloc
        while True:
            rejected = False
            try:
                async with connect(
                    url,
                    additional_headers={"Authorization": f"Bearer {self.config.token}"},
                    user_agent_header="AnkiStudioDesktop",
                    open_timeout=OPEN_TIMEOUT_S,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=MAX_MESSAGE_BYTES,
                    logger=_ws_log,
                ) as ws:
                    failures = 0
                    self._status = "connected"
                    self._last_error = None
                    self._retry_at = None
                    self._connected_at = time.time()
                    log.info("Ponte del telecomando collegato", extra={"server": host})
                    sender = asyncio.create_task(self._send_loop(ws))
                    try:
                        async for message in ws:
                            await self._handle(message)
                    finally:
                        sender.cancel()
                        try:
                            await sender
                        except (asyncio.CancelledError, ConnectionClosed):
                            pass
                    code = ws.close_code
                self._last_error = f"Connessione chiusa dal server (codice {code})"
            except asyncio.CancelledError:
                raise
            except InvalidStatus as e:
                code = e.response.status_code
                rejected = code in (401, 403)
                self._last_error = (
                    "Il server ha rifiutato il token: controlla che sia di tipo «Solo telecomando» e non revocato"
                    if rejected
                    else f"Il server ha risposto {code}"
                )
            except ConnectionClosed as e:
                self._last_error = f"Connessione caduta (codice {e.rcvd.code if e.rcvd else 'nessuno'})"
            except (OSError, TimeoutError, WebSocketException) as e:
                self._last_error = _describe(e)
            finally:
                self._connected_at = None
                await self.hub.set_bridged_remotes(0)
            failures += 1
            if rejected:
                delay = self.rejected_delay
            else:
                delay = min(self.max_delay, self.min_delay * 2 ** (failures - 1))
                delay *= random.uniform(0.5, 1.0)  # jitter: niente raffiche dopo un riavvio
            self._status = "retrying"
            self._retry_at = time.time() + delay
            log.info(
                "Ponte del telecomando non collegato: riprovo",
                extra={"server": host, "error": self._last_error, "retry_s": round(delay, 1)},
            )
            await asyncio.sleep(delay)
            self._retry_at = None


def _describe(e: BaseException) -> str:
    if isinstance(e, TimeoutError):
        return "Il server non risponde"
    if isinstance(e, ConnectionRefusedError):
        return "Server non raggiungibile (connessione rifiutata)"
    if isinstance(e, OSError):
        return "Server non raggiungibile: controlla la rete"
    return f"Errore di connessione ({type(e).__name__})"


# ---- rotte (solo app desktop) -----------------------------------------------


def require_desktop(
    request: Request,
    settings: Settings = Depends(get_settings),
    _identity=Depends(require_auth),
) -> RemoteBridge:
    """Solo la PWA dentro l'app desktop (la chiave dell'avvio): niente Bearer, neanche admin.
    La configurazione contiene un token del server, ed è del computer, non di un agente."""
    bridge: RemoteBridge | None = getattr(request.app.state, "bridge", None)
    if (
        bridge is None
        or _bearer(request) is not None
        or desktop_identity(request, settings) is None
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo dall'app desktop")
    return bridge


router = APIRouter(prefix="/desktop/remote-bridge", tags=["desktop"])


@router.get("", response_model=RemoteBridgeStatus)
async def bridge_status(bridge: RemoteBridge = Depends(require_desktop)):
    """Stato del ponte. Il token non torna mai indietro: solo `token_set`."""
    return bridge.status()


@router.put("", response_model=RemoteBridgeStatus)
async def bridge_configure(body: RemoteBridgeIn, bridge: RemoteBridge = Depends(require_desktop)):
    """Salva URL e token (`token` null = tieni quello salvato) e collega o scollega subito."""
    try:
        await bridge.configure(body.server_url, body.token, body.enabled)
    except BridgeConfigError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from None
    return bridge.status()


@router.delete("", response_model=RemoteBridgeStatus)
async def bridge_forget(bridge: RemoteBridge = Depends(require_desktop)):
    """Scollega e cancella il token dal disco."""
    await bridge.forget()
    return bridge.status()
