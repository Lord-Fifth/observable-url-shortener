"""Safe final HTTP error boundary for unexpected application failures."""

from __future__ import annotations

import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from shortener.logging import log_event


class UnhandledExceptionMiddleware:
    """Return a generic 500 while allowing the outer correlation layer to respond."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        response_started = False

        async def track_response(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self._app(scope, receive, track_response)
        except Exception as exc:
            if response_started:
                raise
            log_event(
                logging.ERROR,
                "unhandled_application_error",
                "Unhandled exception while processing request",
                exception_type=type(exc).__name__,
            )
            response = JSONResponse(
                status_code=500,
                content={"detail": "internal server error"},
            )
            await response(scope, receive, send)
