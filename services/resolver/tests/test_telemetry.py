from __future__ import annotations

from collections.abc import Sequence

import httpx
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from prometheus_client.parser import text_string_to_metric_families
from resolver.config import Settings
from resolver.main import create_app
from resolver.telemetry import TelemetryConfig, TelemetryRuntime


def metric_samples(payload: str, family_name: str) -> list[object]:
    families = {family.name: family for family in text_string_to_metric_families(payload)}
    return list(families[family_name].samples)


def test_resolver_red_metrics_use_bounded_routes_and_500_error_semantics() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        code = request.url.path.rsplit("/", maxsplit=1)[-1]
        correlation_id = request.headers["X-Correlation-ID"]
        if code == "missing-code":
            return httpx.Response(404, headers={"X-Correlation-ID": correlation_id})
        if code == "failed-code":
            return httpx.Response(500, headers={"X-Correlation-ID": correlation_id})
        return httpx.Response(
            200,
            json={"code": code, "url": "https://example.com/destination"},
            headers={"X-Correlation-ID": correlation_id},
        )

    telemetry = TelemetryRuntime(TelemetryConfig("resolver", None, 1.0, 5.0))
    app = create_app(
        Settings("http://shortener.test", 0.5),
        transport=httpx.MockTransport(handler),
        telemetry=telemetry,
    )
    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 200
        assert client.get("/known-code", follow_redirects=False).status_code == 302
        assert client.get("/missing-code", follow_redirects=False).status_code == 404
        assert client.get("/failed-code", follow_redirects=False).status_code == 503
        metrics = client.get("/metrics")
        payload = metrics.text

    assert metrics.status_code == 200
    requests = metric_samples(payload, "url_shortener_http_server_requests")
    request_totals = [sample for sample in requests if sample.name.endswith("_total")]
    assert sum(sample.value for sample in request_totals) == 3
    assert {sample.labels["http_route"] for sample in request_totals} == {"/{code}"}
    assert {sample.labels["http_response_status_code"] for sample in request_totals} == {
        "302",
        "404",
        "503",
    }

    errors = metric_samples(payload, "url_shortener_http_server_errors")
    error_totals = [sample for sample in errors if sample.name.endswith("_total")]
    assert sum(sample.value for sample in error_totals) == 1
    assert error_totals[0].labels["http_response_status_code"] == "503"
    duration = metric_samples(payload, "url_shortener_http_server_request_duration_seconds")
    assert sum(sample.value for sample in duration if sample.name.endswith("_count")) == 3

    assert "/healthz" not in payload
    assert "/readyz" not in payload
    assert "/metrics" not in payload
    assert "known-code" not in payload
    assert "missing-code" not in payload
    assert "failed-code" not in payload
    assert "X-Correlation-ID" not in payload
    assert "trace_id" not in payload
    assert "span_id" not in payload


class FailingSpanExporter(SpanExporter):
    def __init__(self) -> None:
        self.export_calls = 0
        self.shutdown_called = False

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.export_calls += 1
        return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        self.shutdown_called = True


def test_telemetry_export_failure_does_not_break_request_and_shutdown_runs() -> None:
    exporter = FailingSpanExporter()

    async def handler(request: httpx.Request) -> httpx.Response:
        correlation_id = request.headers["X-Correlation-ID"]
        return httpx.Response(
            200,
            json={"code": "known", "url": "https://example.com"},
            headers={"X-Correlation-ID": correlation_id},
        )

    telemetry = TelemetryRuntime(
        TelemetryConfig("resolver", None, 1.0, 5.0),
        span_exporter=exporter,
        synchronous_spans=True,
    )
    app = create_app(
        Settings("http://shortener.test", 0.5),
        transport=httpx.MockTransport(handler),
        telemetry=telemetry,
    )
    with TestClient(app) as client:
        response = client.get("/known", follow_redirects=False)

    assert response.status_code == 302
    assert exporter.export_calls >= 2
    assert exporter.shutdown_called
