"""Logging: testo leggibile in sviluppo, JSON (una riga per evento) in produzione.

Ogni record passa da un filtro che oscura i segreti noti (token dell'API, chiave
di sync, password appena usata per il login), anche se finissero per sbaglio in
un messaggio d'errore o in un traceback.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time

_secrets: set[str] = set()
_secrets_lock = threading.Lock()
_MASK = "***"

# attributi standard di LogRecord: tutto il resto è un campo "extra" da includere nel JSON
_STD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName", "color_message"}


def register_secret(value: str | None) -> None:
    """Da qui in poi `value` non comparirà più nei log."""
    if value and len(value) >= 4:
        with _secrets_lock:
            _secrets.add(value)


def redact(text: str) -> str:
    with _secrets_lock:
        secrets = sorted(_secrets, key=len, reverse=True)
    for s in secrets:
        if s in text:
            text = text.replace(s, _MASK)
    return text


class SecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        if record.exc_info and not record.exc_text:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact(record.exc_text)
        for k, v in list(vars(record).items()):
            if k not in _STD_ATTRS and isinstance(v, str):
                setattr(record, k, redact(v))
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k, v in vars(record).items():
            if k not in _STD_ATTRS and not k.startswith("_"):
                out[k] = v if isinstance(v, (int, float, bool, type(None))) else str(v)
        if record.exc_text:
            out["exc"] = record.exc_text
        elif record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extra = {
            k: v for k, v in vars(record).items() if k not in _STD_ATTRS and not k.startswith("_")
        }
        if extra:
            base += " " + " ".join(f"{k}={v}" for k, v in extra.items())
        return base


def setup_logging(fmt: str = "text", level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    handler.addFilter(SecretFilter())
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_anki_studio", False):
            root.removeHandler(h)
    handler._anki_studio = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(level.upper())
    # i log di uvicorn passano dallo stesso handler (e dallo stesso filtro)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # il log di accesso lo scriviamo noi (con durata e senza query string)
    logging.getLogger("uvicorn.access").disabled = True
