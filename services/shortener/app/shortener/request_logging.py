"""ASGI request-completion logging."""

from __future__ import annotations

import logging
from time import perf_counter

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from shortener.logging import log_event
from shortener.telemetry import EXCLUDED_HTTP_PATHS, RedMetrics


class RequestLoggingMiddleware:
    """Emit one useful completion record after each HTTP response."""

    def __init__(self, app: ASGIApp, red_metrics: RedMetrics) -> None:
        self._app = app
        self._red_metrics = red_metrics

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
            duration_seconds = perf_counter() - started_at
            duration_ms = round(duration_seconds * 1000, 3)
            if scope["path"] not in EXCLUDED_HTTP_PATHS:
                route = getattr(scope.get("route"), "path", "UNMATCHED")
                self._red_metrics.record(
                    method=scope["method"],
                    route=route,
                    status_code=status_code,
                    duration_seconds=duration_seconds,
                )
            log_event(
                logging.ERROR if status_code >= 500 else logging.INFO,
                "http_request_completed",
                "HTTP request completed",
                method=scope["method"],
                path=scope["path"],
                status_code=status_code,
                duration_ms=duration_ms,
            )
