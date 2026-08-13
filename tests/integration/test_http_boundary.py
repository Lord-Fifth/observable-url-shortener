from __future__ import annotations

import json
import logging

import httpx
import pytest
from opentelemetry.context import Context, attach, detach
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from resolver.config import Settings as ResolverSettings
from resolver.logging import JsonFormatter as ResolverJsonFormatter
from resolver.logging import logger as resolver_logger
from resolver.main import create_app as create_resolver_app
from resolver.repository import InMemoryRedirectEventRepository
from resolver.telemetry import TelemetryConfig as ResolverTelemetryConfig
from resolver.telemetry import TelemetryRuntime as ResolverTelemetryRuntime
from shortener.config import Settings as ShortenerSettings
from shortener.logging import JsonFormatter as ShortenerJsonFormatter
from shortener.logging import logger as shortener_logger
from shortener.main import create_app as create_shortener_app
from shortener.repository import InMemoryUrlRepository
from shortener.telemetry import TelemetryConfig as ShortenerTelemetryConfig
from shortener.telemetry import TelemetryRuntime as ShortenerTelemetryRuntime


class CapturingAsgiTransport(httpx.AsyncBaseTransport):
    def __init__(self, app: object) -> None:
        self._transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        # ASGITransport stays in-process; detach to model the real process boundary.
        token = attach(Context())
        try:
            return await self._transport.handle_async_request(request)
        finally:
            detach(token)

    async def aclose(self) -> None:
        await self._transport.aclose()


class JsonCaptureHandler(logging.Handler):
    def __init__(self, formatter: logging.Formatter) -> None:
        super().__init__()
        self.setFormatter(formatter)
        self.entries: list[dict[str, object]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.entries.append(json.loads(self.format(record)))


@pytest.mark.asyncio
async def test_create_then_resolve_across_real_asgi_http_boundary() -> None:
    shortener_logs = JsonCaptureHandler(ShortenerJsonFormatter())
    resolver_logs = JsonCaptureHandler(ResolverJsonFormatter())
    shortener_logger.addHandler(shortener_logs)
    resolver_logger.addHandler(resolver_logs)
    shortener_exporter = InMemorySpanExporter()
    resolver_exporter = InMemorySpanExporter()
    shortener_telemetry = ShortenerTelemetryRuntime(
        ShortenerTelemetryConfig("shortener", None, 1.0, 5.0),
        span_exporter=shortener_exporter,
        synchronous_spans=True,
    )
    resolver_telemetry = ResolverTelemetryRuntime(
        ResolverTelemetryConfig("resolver", None, 1.0, 5.0),
        span_exporter=resolver_exporter,
        synchronous_spans=True,
    )
    mapping_repository = InMemoryUrlRepository()
    shortener_app = create_shortener_app(
        ShortenerSettings("http://resolver.test", code_length=8, max_code_attempts=3),
        repository_factory=lambda: mapping_repository,
        code_generator=lambda: "abc12345",
        telemetry=shortener_telemetry,
    )
    shortener_transport = CapturingAsgiTransport(shortener_app)
    event_repository = InMemoryRedirectEventRepository()
    resolver_app = create_resolver_app(
        ResolverSettings("http://shortener.test", shortener_timeout_seconds=1.0),
        event_repository_factory=lambda: event_repository,
        transport=shortener_transport,
        telemetry=resolver_telemetry,
    )

    try:
        async with (
            shortener_app.router.lifespan_context(shortener_app),
            resolver_app.router.lifespan_context(resolver_app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=shortener_app),
                base_url="http://shortener.test",
            ) as shortener_client,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=resolver_app),
                base_url="http://resolver.test",
                follow_redirects=False,
            ) as resolver_client,
        ):
            created = await shortener_client.post(
                "/v1/urls",
                json={"url": "https://example.com/integration"},
                headers={"X-Correlation-ID": "create-integration"},
            )
            assert created.status_code == 201
            assert created.headers["X-Correlation-ID"] == "create-integration"
            assert created.json() == {
                "code": "abc12345",
                "short_url": "http://resolver.test/abc12345",
            }

            resolved = await resolver_client.get(
                "/abc12345",
                headers={"X-Correlation-ID": "resolve-integration"},
            )
    finally:
        shortener_logger.removeHandler(shortener_logs)
        resolver_logger.removeHandler(resolver_logs)

    assert resolved.status_code == 302
    assert resolved.headers["Location"] == "https://example.com/integration"
    assert resolved.headers["X-Correlation-ID"] == "resolve-integration"
    assert len(shortener_transport.requests) == 1
    assert shortener_transport.requests[0].headers["X-Correlation-ID"] == "resolve-integration"
    assert len(event_repository.events) == 1
    assert event_repository.events[0].correlation_id == "resolve-integration"
    assert any(
        entry["correlation_id"] == "resolve-integration"
        and entry["event"] == "url_mapping_lookup_succeeded"
        for entry in shortener_logs.entries
    )
    assert any(
        entry["correlation_id"] == "resolve-integration" and entry["event"] == "redirect_resolved"
        for entry in resolver_logs.entries
    )

    resolver_spans = resolver_exporter.get_finished_spans()
    shortener_spans = shortener_exporter.get_finished_spans()
    resolver_server = next(span for span in resolver_spans if span.kind is SpanKind.SERVER)
    resolver_client = next(span for span in resolver_spans if span.kind is SpanKind.CLIENT)
    shortener_server = next(
        span
        for span in shortener_spans
        if span.kind is SpanKind.SERVER and span.name.startswith("GET ")
    )
    shared_trace_id = resolver_server.get_span_context().trace_id

    assert shared_trace_id != 0
    assert len(f"{shared_trace_id:032x}") == 32
    assert resolver_client.get_span_context().trace_id == shared_trace_id
    assert shortener_server.get_span_context().trace_id == shared_trace_id
    assert resolver_client.parent is not None
    assert resolver_client.parent.span_id == resolver_server.get_span_context().span_id
    assert shortener_server.parent is not None
    assert shortener_server.parent.span_id == resolver_client.get_span_context().span_id
    assert len(f"{resolver_server.get_span_context().span_id:016x}") == 16
    assert len(f"{shortener_server.get_span_context().span_id:016x}") == 16
    assert f"{shared_trace_id:032x}" != "resolve-integration"

    shortener_entry = next(
        entry
        for entry in shortener_logs.entries
        if entry["event"] == "url_mapping_lookup_succeeded"
    )
    resolver_entry = next(
        entry for entry in resolver_logs.entries if entry["event"] == "redirect_resolved"
    )
    assert shortener_entry["trace_id"] == resolver_entry["trace_id"] == f"{shared_trace_id:032x}"
    assert shortener_entry["span_id"] == f"{shortener_server.get_span_context().span_id:016x}"
    assert resolver_entry["span_id"] == f"{resolver_server.get_span_context().span_id:016x}"
    assert shortener_entry["span_id"] != resolver_entry["span_id"]
    assert shortener_entry["trace_sampled"] is resolver_entry["trace_sampled"] is True
