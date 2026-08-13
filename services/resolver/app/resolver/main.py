"""FastAPI entry point for public short-code resolution."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST

from resolver.client import MappingNotFound, ShortenerClient, UpstreamUnavailable
from resolver.config import Settings
from resolver.correlation import CorrelationIdMiddleware, require_correlation_id
from resolver.errors import UnhandledExceptionMiddleware
from resolver.logging import log_event
from resolver.models import StatusResponse
from resolver.repository import (
    InMemoryRedirectEventRepository,
    RedirectEvent,
    RedirectEventRepository,
)
from resolver.request_logging import RequestLoggingMiddleware
from resolver.telemetry import TelemetryConfig, TelemetryRuntime

EventRepositoryFactory = Callable[[], RedirectEventRepository]


def create_app(
    settings: Settings | None = None,
    event_repository_factory: EventRepositoryFactory = InMemoryRedirectEventRepository,
    transport: httpx.AsyncBaseTransport | None = None,
    telemetry: TelemetryRuntime | None = None,
) -> FastAPI:
    service_settings = settings or Settings.from_env()
    telemetry_runtime = telemetry or TelemetryRuntime(
        TelemetryConfig(
            service_name=service_settings.otel_service_name,
            otlp_endpoint=service_settings.otel_exporter_otlp_endpoint,
            export_timeout_seconds=service_settings.otel_export_timeout_seconds,
            metric_export_interval_seconds=(service_settings.otel_metric_export_interval_seconds),
        )
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as resources:
            resources.push_async_callback(telemetry_runtime.ashutdown)
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
            telemetry_runtime.instrument_httpx(http_client)
            resources.callback(telemetry_runtime.uninstrument_httpx, http_client)
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
    application.state.telemetry = telemetry_runtime
    application.add_middleware(UnhandledExceptionMiddleware)
    application.add_middleware(
        RequestLoggingMiddleware,
        red_metrics=telemetry_runtime.red_metrics,
    )
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

    @application.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(
            content=telemetry_runtime.prometheus_payload(),
            headers={"Content-Type": CONTENT_TYPE_LATEST},
        )

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
            log_event(
                logging.INFO,
                "redirect_mapping_not_found",
                "Redirect mapping not found",
                code=code,
            )
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
            log_event(
                logging.ERROR,
                "redirect_event_recording_failed",
                "Redirect event could not be recorded",
                code=code,
                exception_type=type(exc).__name__,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="redirect event could not be recorded",
            ) from exc

        log_event(
            logging.INFO,
            "redirect_event_recorded",
            "Redirect event recorded",
            code=code,
        )
        log_event(
            logging.INFO,
            "redirect_resolved",
            "Redirect resolved",
            code=code,
        )
        return RedirectResponse(url=destination, status_code=status.HTTP_302_FOUND)

    telemetry_runtime.instrument_fastapi(application)
    return application


app = create_app()
