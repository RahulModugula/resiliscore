"""Request IDs, one JSON access-log line per request, and JSON log formatting. Stdlib logging only."""

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
# An incoming id is untrusted input: accept only short, plain tokens so it can't inject log lines or markup.
_VALID_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
_ACCESS_FIELDS = ("method", "path", "status", "latency_ms", "request_id")

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
access_log = logging.getLogger("resiliscore.access")


def current_request_id() -> str | None:
    return request_id_var.get()


class JsonFormatter(logging.Formatter):
    """One JSON object per line. Access-log fields are copied across when present."""

    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _ACCESS_FIELDS:
            if hasattr(record, field):
                line[field] = getattr(record, field)
        if record.exc_info:
            line["exc"] = self.formatException(record.exc_info)
        return json.dumps(line, separators=(",", ":"), default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Attach the JSON handler to the `resiliscore` logger once. Repeat calls are no-ops."""
    logger = logging.getLogger("resiliscore")
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)


def _incoming_request_id(scope: Scope) -> str | None:
    raw = Headers(scope=scope).get(REQUEST_ID_HEADER)
    if raw is not None and _VALID_REQUEST_ID.fullmatch(raw):
        return raw
    return None


class RequestContextMiddleware:
    """Pure ASGI middleware. Honours or generates the request id, echoes it, and logs one line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope) or str(uuid.uuid4())
        status = 500
        started = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        token = request_id_var.set(request_id)
        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            request_id_var.reset(token)
            access_log.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    "request_id": request_id,
                },
            )
