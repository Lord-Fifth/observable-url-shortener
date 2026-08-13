"""ASGI request-completion logging."""

from __future__ import annotations

import logging
from time import perf_counter

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from resolver.logging import log_event


class RequestLoggingMiddleware:
    """Emit one useful completion record after each HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        started_at = perf_counter()
        status_code = 500

        async def capture_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self._app(scope, receive, capture_status)
        finally:
            duration_ms = round((perf_counter() - started_at) * 1000, 3)
            log_event(
                logging.ERROR if status_code >= 500 else logging.INFO,
                "http_request_completed",
                "HTTP request completed",
                method=scope["method"],
                path=scope["path"],
                status_code=status_code,
                duration_ms=duration_ms,
            )
