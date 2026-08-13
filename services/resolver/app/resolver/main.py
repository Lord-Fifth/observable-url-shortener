"""FastAPI entry point for public short-code resolution."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from resolver.client import MappingNotFound, ShortenerClient, UpstreamUnavailable
from resolver.config import Settings
from resolver.correlation import CorrelationIdMiddleware, require_correlation_id
from resolver.errors import UnhandledExceptionMiddleware
from resolver.models import StatusResponse
from resolver.repository import (
    InMemoryRedirectEventRepository,
    RedirectEvent,
    RedirectEventRepository,
)

EventRepositoryFactory = Callable[[], RedirectEventRepository]


def create_app(
    settings: Settings | None = None,
    event_repository_factory: EventRepositoryFactory = InMemoryRedirectEventRepository,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    service_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as resources:
            event_repository = event_repository_factory()
            resources.push_async_callback(event_repository.aclose)
            http_client = await resources.enter_async_context(
                httpx.AsyncClient(
                    base_url=service_settings.shortener_base_url,
                    timeout=httpx.Timeout(service_settings.shortener_timeout_seconds),
                    follow_redirects=False,
                    transport=transport,
                )
            )
            application.state.event_repository = event_repository
            application.state.http_client = http_client
            application.state.shortener_client = ShortenerClient(http_client)
            application.state.ready = True
            try:
                yield
            finally:
                application.state.ready = False

    application = FastAPI(title="observable-url-resolver", lifespan=lifespan)
    application.state.ready = False
    application.add_middleware(UnhandledExceptionMiddleware)
    application.add_middleware(CorrelationIdMiddleware)

    @application.get("/healthz", response_model=StatusResponse)
    async def health() -> StatusResponse:
        return StatusResponse(status="healthy")

    @application.get("/readyz", response_model=StatusResponse)
    async def readiness(request: Request) -> StatusResponse:
        if not request.app.state.ready:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="service is not ready",
            )
        return StatusResponse(status="ready")

    @application.get(
        "/{code}",
        response_class=RedirectResponse,
        status_code=status.HTTP_302_FOUND,
    )
    async def resolve(code: str, request: Request) -> RedirectResponse:
        correlation_id = require_correlation_id()
        shortener_client: ShortenerClient = request.app.state.shortener_client
        try:
            destination = await shortener_client.get_destination(code, correlation_id)
        except MappingNotFound as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="code not found"
            ) from exc
        except UpstreamUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="mapping service unavailable",
            ) from exc

        event_repository: RedirectEventRepository = request.app.state.event_repository
        try:
            await event_repository.record(
                RedirectEvent(
                    code=code,
                    destination_url=destination,
                    correlation_id=correlation_id,
                    occurred_at=datetime.now(UTC),
                )
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="redirect event could not be recorded",
            ) from exc

        return RedirectResponse(url=destination, status_code=status.HTTP_302_FOUND)

    return application


app = create_app()
