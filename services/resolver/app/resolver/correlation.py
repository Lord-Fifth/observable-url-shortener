"""HTTP correlation semantics independent of logging and tracing libraries."""

from __future__ import annotations

from contextvars import ContextVar
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

CORRELATION_HEADER = "X-Correlation-ID"
_CORRELATION_HEADER_BYTES = b"x-correlation-id"
_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def _is_valid(value: str) -> bool:
    """Accept a compact visible-ASCII identifier and reject ambiguous input."""

    return 1 <= len(value) <= 128 and all(33 <= ord(character) <= 126 for character in value)


def _incoming_correlation_id(scope: Scope) -> str | None:
    for name, raw_value in scope.get("headers", []):
        if name.lower() == _CORRELATION_HEADER_BYTES:
            value = raw_value.decode("latin-1")
            return value if _is_valid(value) else None
    return None


def get_correlation_id() -> str | None:
    """Return the ID for the active request, if called in request context."""

    return _correlation_id.get()


def require_correlation_id() -> str:
    """Return the active request ID or fail on incorrect adapter usage."""

    correlation_id = get_correlation_id()
    if correlation_id is None:
        raise RuntimeError("correlation ID is unavailable outside an HTTP request")
    return correlation_id


class CorrelationIdMiddleware:
    """Preserve or generate a correlation ID and add it to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        correlation_id = _incoming_correlation_id(scope) or str(uuid4())
        token = _correlation_id.set(correlation_id)
        scope.setdefault("state", {})["correlation_id"] = correlation_id

        async def send_with_correlation(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != _CORRELATION_HEADER_BYTES
                ]
                headers.append((_CORRELATION_HEADER_BYTES, correlation_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self._app(scope, receive, send_with_correlation)
        finally:
            _correlation_id.reset(token)
