from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest
import shortener.telemetry as telemetry_module
from fastapi.testclient import TestClient
from opentelemetry.sdk.metrics.export import (
    MetricExporter,
    MetricExportResult,
    MetricsData,
)
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from prometheus_client.parser import text_string_to_metric_families
from shortener.config import Settings
from shortener.main import create_app
from shortener.repository import InMemoryUrlRepository
from shortener.telemetry import TelemetryConfig, TelemetryRuntime


def metric_samples(payload: str, family_name: str) -> list[object]:
    families = {family.name: family for family in text_string_to_metric_families(payload)}
    return list(families[family_name].samples)


def test_shortener_creates_server_span_and_exposes_red_metrics() -> None:
    exporter = InMemorySpanExporter()
    telemetry = TelemetryRuntime(
        TelemetryConfig("shortener", None, 1.0, 5.0),
        span_exporter=exporter,
        synchronous_spans=True,
    )
    app = create_app(
        Settings("http://resolver.test", 8, 5),
        code_generator=lambda: "abc12345",
        telemetry=telemetry,
    )

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 200
        created = client.post(
            "/v1/urls",
            json={"url": "https://example.com/private?token=not-a-label"},
            headers={"X-Correlation-ID": "metric-correlation"},
        )
        missing = client.get("/internal/v1/urls/missing-code")
        metrics = client.get("/metrics")

        assert created.status_code == 201
        assert missing.status_code == 404
        assert metrics.status_code == 200
        assert metrics.headers["Content-Type"].startswith("text/plain")
        payload = metrics.text

    spans = exporter.get_finished_spans()
    server_span = next(span for span in spans if span.name == "POST /v1/urls")
    assert server_span.kind is SpanKind.SERVER
    assert server_span.get_span_context().trace_id != 0
    assert server_span.get_span_context().span_id != 0
    assert server_span.resource.attributes["service.name"] == "shortener"

    requests = metric_samples(payload, "url_shortener_http_server_requests")
    request_totals = [sample for sample in requests if sample.name.endswith("_total")]
    assert sum(sample.value for sample in request_totals) == 2
    assert {sample.labels["http_route"] for sample in request_totals} == {
        "/v1/urls",
        "/internal/v1/urls/{code}",
    }
    assert {sample.labels["http_response_status_code"] for sample in request_totals} == {
        "201",
        "404",
    }
    assert "url_shortener_http_server_errors" not in {
        family.name for family in text_string_to_metric_families(payload)
    }
    duration = metric_samples(payload, "url_shortener_http_server_request_duration_seconds")
    assert sum(sample.value for sample in duration if sample.name.endswith("_count")) == 2
    assert "/healthz" not in payload
    assert "/readyz" not in payload
    assert "/metrics" not in payload
    assert "missing-code" not in payload
    assert "metric-correlation" not in payload
    assert "not-a-label" not in payload


def test_real_500_increments_shortener_error_counter() -> None:
    class FailingRepository(InMemoryUrlRepository):
        async def insert_if_absent(self, mapping: object) -> bool:
            raise RuntimeError("repository failed")

    telemetry = TelemetryRuntime(TelemetryConfig("shortener", None, 1.0, 5.0))
    app = create_app(
        Settings("http://resolver.test", 8, 5),
        repository_factory=FailingRepository,
        telemetry=telemetry,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        failed = client.post("/v1/urls", json={"url": "https://example.com"})
        payload = client.get("/metrics").text

    assert failed.status_code == 500
    errors = metric_samples(payload, "url_shortener_http_server_errors")
    totals = [sample for sample in errors if sample.name.endswith("_total")]
    assert sum(sample.value for sample in totals) == 1
    assert totals[0].labels["http_response_status_code"] == "500"


class CapturingCredential:
    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        self.closed = False

    def close(self) -> None:
        self.closed = True


class CapturingSpanExporter(SpanExporter):
    def __init__(self) -> None:
        self.shutdown_called = False

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        self.shutdown_called = True


class CapturingMetricExporter(MetricExporter):
    def __init__(self) -> None:
        super().__init__()
        self.shutdown_called = False

    def export(
        self,
        metrics_data: MetricsData,
        timeout_millis: float = 10_000,
        **kwargs: object,
    ) -> MetricExportResult:
        return MetricExportResult.SUCCESS

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        return True

    def shutdown(self, timeout_millis: float = 30_000, **kwargs: object) -> None:
        self.shutdown_called = True


def test_azure_monitor_exporters_share_the_explicit_managed_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_string = (
        "InstrumentationKey=00000000-0000-0000-0000-000000000000;"
        "IngestionEndpoint=https://example.test/"
    )
    credential = CapturingCredential("11111111-1111-1111-1111-111111111111")
    span_exporter = CapturingSpanExporter()
    metric_exporter = CapturingMetricExporter()
    calls: dict[str, dict[str, object]] = {}

    def credential_factory(*, client_id: str) -> CapturingCredential:
        assert client_id == credential.client_id
        return credential

    def trace_factory(**kwargs: object) -> CapturingSpanExporter:
        calls["trace"] = kwargs
        return span_exporter

    def metric_factory(**kwargs: object) -> CapturingMetricExporter:
        calls["metric"] = kwargs
        return metric_exporter

    monkeypatch.setattr(telemetry_module, "ManagedIdentityCredential", credential_factory)
    monkeypatch.setattr(telemetry_module, "AzureMonitorTraceExporter", trace_factory)
    monkeypatch.setattr(telemetry_module, "AzureMonitorMetricExporter", metric_factory)

    runtime = TelemetryRuntime(
        TelemetryConfig(
            "shortener",
            None,
            1.0,
            60.0,
            azure_monitor_enabled=True,
            application_insights_connection_string=connection_string,
            azure_client_id=credential.client_id,
        )
    )
    runtime.red_metrics.record("POST", "/v1/urls", 201, 0.01)

    assert runtime.remote_backend == "azure_monitor"
    assert set(calls) == {"trace", "metric"}
    for call in calls.values():
        assert call["connection_string"] == connection_string
        assert call["credential"] is credential
        assert call["disable_offline_storage"] is True
    assert b"url_shortener_http_server_requests" in runtime.prometheus_payload()

    asyncio.run(runtime.ashutdown())
    assert credential.closed
    assert span_exporter.shutdown_called
    assert metric_exporter.shutdown_called


def test_conflicting_remote_exporters_are_rejected() -> None:
    with pytest.raises(ValueError, match="mutually exclusive"):
        TelemetryConfig(
            "shortener",
            "http://collector.test:4318",
            1.0,
            5.0,
            azure_monitor_enabled=True,
            application_insights_connection_string="InstrumentationKey=unused",
            azure_client_id="11111111-1111-1111-1111-111111111111",
        )


def test_no_remote_backend_keeps_prometheus_active() -> None:
    runtime = TelemetryRuntime(TelemetryConfig("shortener", None, 1.0, 5.0))
    runtime.red_metrics.record("POST", "/v1/urls", 201, 0.01)

    assert runtime.remote_backend == "none"
    assert b"url_shortener_http_server_requests" in runtime.prometheus_payload()

    asyncio.run(runtime.ashutdown())
