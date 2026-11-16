"""Telecomando: il telefono preme i pulsanti, lo schermo che studia (il computer) esegue.

Due ruoli sullo stesso WebSocket `/api/remote`:

- `screen`: la schermata di studio aperta. Manda il proprio stato (mazzo, carta girata
  o no, etichette dei pulsanti) e riceve i comandi;
- `remote`: il telefono. Riceve lo stato dello schermo attivo e manda i comandi.

Niente abbinamento con QR o codici: chi apre il WebSocket ha già fatto l'accesso con
Authentik, e la collezione (quindi l'utente) è una sola. Se gli schermi aperti sono più
d'uno, comanda quello usato per ultimo (l'ultimo che era in primo piano).

Il server non decide niente e non tocca la collezione: inoltra. Lo studio resta tutto
nella schermata (`StudyScreen`), che esegue un comando come farebbe con la tastiera:
timer, audio, 409 sulla coda cambiata, undo funzionano come sempre. Per questo le rotte
sono `async` (le altre sono `def` perché prendono il lock della collezione): qui c'è solo
lo stato in memoria, toccato sempre dallo stesso event loop, quindi niente lock.

Perché WebSocket e non Server-Sent Events: allo spegnimento uvicorn chiude i WebSocket
subito (codice 1012), mentre uno stream SSE lo aspetterebbe fino al timeout (30 s).

L'app desktop ha un backend suo (127.0.0.1, copia locale della collezione), mentre il
telefono apre il server: per farli incontrare il backend del desktop apre un ponte in uscita
verso questo stesso WebSocket del server, come `screen`, con un token di scope `remote`
(app/remote_bridge.py). Dal lato del server il ponte è uno schermo come gli altri; dal lato
del desktop è un telefono in più: riceve lo stato dello schermo attivo (`on_active_state`) e
consegna i comandi con `command`, come farebbe un telecomando locale. La sync non c'entra:
resta quella di Anki con AnkiWeb, il relay inoltra soltanto.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from .config import Settings, get_settings
from .schemas import RemoteCommand, RemoteScreenState
from .security import websocket_session

log = logging.getLogger(__name__)

# un utente solo: bastano e avanzano, e un client impazzito non apre connessioni all'infinito
MAX_PEERS = 32
# codici di chiusura applicativi (4000–4999)
CLOSE_REPLACED = 4409  # stessa schermata riconnessa: la connessione vecchia non serve più
CLOSE_BAD_MESSAGE = 4400


@dataclass(eq=False)
class Peer:
    ws: WebSocket
    role: Literal["screen", "remote"]
    screen_id: str | None = None
    state: dict[str, Any] | None = None
    # l'ultima volta che lo schermo era in primo piano: vince il più recente
    active_at: float = field(default=0.0)

    async def send(self, message: dict[str, Any]) -> None:
        try:
            await self.ws.send_json(message)
        except Exception:  # noqa: BLE001 - connessione già chiusa: la toglie il suo loop
            pass


class RemoteHub:
    def __init__(self, max_peers: int = MAX_PEERS) -> None:
        self.max_peers = max_peers
        self.screens: dict[str, Peer] = {}
        self.remotes: set[Peer] = set()
        self._last_sent: dict[str, Any] | None | bool = False  # False = mai inviato
        # i telefoni collegati al server, quando questo è il backend dell'app desktop e il ponte
        # è su: per la schermata contano come telefoni locali (avviso «Telecomando collegato»)
        self.bridged_remotes = 0
        # il ponte (app/remote_bridge.py): `(stato dello schermo attivo | None, claim)` a ogni
        # cambio. Sincrono e senza attese: il ponte mette da parte e spedisce dal suo task
        self.on_active_state: Callable[[dict[str, Any] | None, bool], None] | None = None

    @property
    def remote_count(self) -> int:
        return len(self.remotes) + self.bridged_remotes

    @property
    def full(self) -> bool:
        return len(self.screens) + len(self.remotes) >= self.max_peers

    def active_screen(self) -> Peer | None:
        candidates = [p for p in self.screens.values() if p.state is not None]
        return max(candidates, key=lambda p: p.active_at, default=None)

    # ---- registrazione ----------------------------------------------------

    async def add_screen(self, peer: Peer) -> None:
        assert peer.screen_id is not None
        old = self.screens.get(peer.screen_id)
        self.screens[peer.screen_id] = peer
        if old is not None:
            # la stessa scheda si è riconnessa prima che la vecchia connessione cadesse
            try:
                await old.ws.close(CLOSE_REPLACED)
            except Exception:  # noqa: BLE001
                pass
        await peer.send({"type": "remotes", "count": self.remote_count})

    async def add_remote(self, peer: Peer) -> None:
        self.remotes.add(peer)
        await peer.send(self._state_message())
        await self._broadcast_remotes()

    async def remove(self, peer: Peer) -> None:
        if peer.role == "remote":
            if peer in self.remotes:
                self.remotes.discard(peer)
                await self._broadcast_remotes()
            return
        if peer.screen_id and self.screens.get(peer.screen_id) is peer:
            del self.screens[peer.screen_id]
            await self._broadcast_state()
            self._notify_bridge(claim=False)

    async def set_bridged_remotes(self, count: int) -> None:
        if count != self.bridged_remotes:
            self.bridged_remotes = count
            await self._broadcast_remotes()

    # ---- messaggi ---------------------------------------------------------

    async def screen_state(
        self, peer: Peer, state: RemoteScreenState | None, claim: bool
    ) -> None:
        # None: lo schermo c'è ma non ha niente da comandare (il ponte del desktop senza
        # nessuna finestra aperta): per il telefono è come se non ci fosse
        peer.state = state.model_dump() if state is not None else None
        if claim:
            peer.active_at = time.monotonic()
        await self._broadcast_state()
        self._notify_bridge(claim=claim and self.active_screen() is peer)

    def current_state(self) -> dict[str, Any] | None:
        screen = self.active_screen()
        return screen.state if screen else None

    def ever_claimed(self) -> bool:
        """Lo schermo attivo è stato in primo piano almeno una volta (per il ponte che si
        ricollega: rivendica il telefono solo se la finestra l'aveva già fatto)."""
        screen = self.active_screen()
        return screen is not None and screen.active_at > 0

    def _notify_bridge(self, claim: bool) -> None:
        if self.on_active_state is not None:
            self.on_active_state(self.current_state(), claim)

    async def command(self, command: RemoteCommand) -> bool:
        """Inoltra il comando allo schermo attivo; False se non ce n'è uno."""
        screen = self.active_screen()
        if screen is None:
            return False
        await screen.send({"type": "command", "command": command.model_dump()})
        return True

    def _state_message(self) -> dict[str, Any]:
        screen = self.active_screen()
        return {"type": "state", "screen": screen.state if screen else None}

    async def _broadcast_state(self) -> None:
        message = self._state_message()
        if message["screen"] == self._last_sent:
            return  # niente di nuovo per i telefoni (es. stato ripetuto da uno schermo)
        self._last_sent = message["screen"]
        for remote in list(self.remotes):
            await remote.send(message)

    async def _broadcast_remotes(self) -> None:
        message = {"type": "remotes", "count": self.remote_count}
        for screen in list(self.screens.values()):
            await screen.send(message)


router = APIRouter(tags=["remote"])


@router.websocket("/remote")
async def remote_socket(
    websocket: WebSocket,
    role: Literal["screen", "remote"] = Query("remote"),
    screen_id: str | None = Query(None, pattern=r"^[A-Za-z0-9-]{8,64}$"),
    settings: Settings = Depends(get_settings),
):
    """WebSocket del telecomando. Messaggi JSON:

    - schermo → server: `{"type": "state", "state": RemoteScreenState | null, "claim": bool}`
      (`claim`: la schermata è in primo piano e diventa quella comandata; `null`: niente da
      comandare, lo manda il ponte del desktop quando non c'è nessuna finestra aperta);
    - telefono → server: `{"type": "command", "command": RemoteCommand}` (reveal, answer,
      undo, replay, bury, suspend, flag);
    - server → telefono: `{"type": "state", "screen": RemoteScreenState | null}`;
    - server → schermo: `{"type": "command", "command": …}` e `{"type": "remotes", "count": n}`.
    """
    hub: RemoteHub = websocket.app.state.remote
    # chiusura prima di accept() = handshake rifiutato (403): niente dettagli a chi non è entrato
    # Bearer: `ANKI_API_TOKEN`, o un token `remote` solo come schermo (il ponte del desktop)
    if websocket_session(websocket, settings, role) is None:
        await websocket.close(status.WS_1008_POLICY_VIOLATION)
        return
    if hub.full or (role == "screen" and screen_id is None):
        await websocket.close(status.WS_1013_TRY_AGAIN_LATER if hub.full else status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    peer = Peer(websocket, role, screen_id if role == "screen" else None)
    if role == "screen":
        await hub.add_screen(peer)
    else:
        await hub.add_remote(peer)
    try:
        while True:
            data = await websocket.receive_json()
            try:
                if not isinstance(data, dict):
                    raise ValueError("messaggio non valido")
                kind = data.get("type")
                if role == "screen" and kind == "state":
                    raw = data.get("state")
                    state = None if raw is None else RemoteScreenState.model_validate(raw)
                    await hub.screen_state(peer, state, bool(data.get("claim")))
                elif role == "remote" and kind == "command":
                    command = RemoteCommand.model_validate(data.get("command"))
                    if not await hub.command(command):
                        # nessuno schermo: il telefono ridisegna lo stato "nessuna sessione"
                        await peer.send(hub._state_message())
                elif kind == "ping":
                    await peer.send({"type": "pong"})
                else:
                    raise ValueError("messaggio non previsto")
            except (ValidationError, ValueError):
                await websocket.close(CLOSE_BAD_MESSAGE)
                return
    except (WebSocketDisconnect, ValueError):
        # ValueError: JSON non valido da receive_json
        pass
    finally:
        await hub.remove(peer)
