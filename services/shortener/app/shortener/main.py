"""FastAPI entry point for the URL mapping owner."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST

from shortener.config import Settings
from shortener.correlation import CorrelationIdMiddleware
from shortener.errors import UnhandledExceptionMiddleware
from shortener.logging import log_event
from shortener.models import (
    CreateUrlRequest,
    CreateUrlResponse,
    StatusResponse,
    UrlMappingResponse,
)
from shortener.repository import InMemoryUrlRepository, UrlRepository
from shortener.request_logging import RequestLoggingMiddleware
from shortener.service import (
    CodeAllocationExhausted,
    CodeGenerator,
    RandomCodeGenerator,
    ShortenerService,
)
from shortener.telemetry import TelemetryConfig, TelemetryRuntime

RepositoryFactory = Callable[[], UrlRepository]


def create_app(
    settings: Settings | None = None,
    repository_factory: RepositoryFactory = InMemoryUrlRepository,
    code_generator: CodeGenerator | None = None,
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
            repository = repository_factory()
            resources.push_async_callback(repository.aclose)
            generator = code_generator or RandomCodeGenerator(service_settings.code_length)
            application.state.repository = repository
            application.state.shortener_service = ShortenerService(
                repository=repository,
                code_generator=generator,
                max_attempts=service_settings.max_code_attempts,
            )
            application.state.ready = True
            try:
                yield
            finally:
                application.state.ready = False

    application = FastAPI(title="observable-url-shortener", lifespan=lifespan)
    application.state.ready = False
    application.state.telemetry = telemetry_runtime
    application.add_middleware(UnhandledExceptionMiddleware)
    application.add_middleware(
        RequestLoggingMiddleware,
        red_metrics=telemetry_runtime.red_metrics,
    )
    application.add_middleware(CorrelationIdMiddleware)

    @application.exception_handler(CodeAllocationExhausted)
    async def allocation_exhausted(
        _request: Request, _error: CodeAllocationExhausted
    ) -> JSONResponse:
        log_event(
            logging.ERROR,
            "short_code_allocation_exhausted",
            "Short-code allocation attempts exhausted",
            max_attempts=service_settings.max_code_attempts,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "unable to allocate a short code"},
        )

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

    @application.post(
        "/v1/urls",
        response_model=CreateUrlResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_url(request: Request, payload: CreateUrlRequest) -> CreateUrlResponse:
        service: ShortenerService = request.app.state.shortener_service
        mapping = await service.create_mapping(payload.url)
        log_event(
            logging.INFO,
            "url_mapping_created",
            "URL mapping created",
            code=mapping.code,
        )
        return CreateUrlResponse(
            code=mapping.code,
            short_url=f"{service_settings.resolver_base_url}/{mapping.code}",
        )

    @application.get(
        "/internal/v1/urls/{code}",
        response_model=UrlMappingResponse,
    )
    async def get_url(code: str, request: Request) -> UrlMappingResponse:
        service: ShortenerService = request.app.state.shortener_service
        mapping = await service.get_mapping(code)
        if mapping is None:
            log_event(
                logging.INFO,
                "url_mapping_lookup_not_found",
                "URL mapping not found",
                code=code,
            )
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="code not found")
        log_event(
            logging.INFO,
            "url_mapping_lookup_succeeded",
            "URL mapping lookup succeeded",
            code=code,
        )
        return UrlMappingResponse(code=mapping.code, url=mapping.url)

    telemetry_runtime.instrument_fastapi(application)
    return application


app = create_app()
