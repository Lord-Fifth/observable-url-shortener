"""Lifecycle-owned OpenTelemetry tracing and explicit RED metrics."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from threading import Lock

import httpx
from fastapi import FastAPI
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.metrics import NoOpMeterProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.semconv.resource import ResourceAttributes
from prometheus_client import CollectorRegistry, generate_latest

SERVICE_VERSION = "0.3.0"
METRIC_REQUESTS = "url_shortener.http.server.requests"
METRIC_ERRORS = "url_shortener.http.server.errors"
METRIC_DURATION = "url_shortener.http.server.request.duration"
EXCLUDED_HTTP_PATHS = frozenset({"/healthz", "/readyz", "/metrics"})
_EXCLUDED_URLS_PATTERN = r".*/(?:healthz|readyz|metrics)$"


@dataclass(frozen=True, slots=True)
class TelemetryConfig:
    service_name: str
    otlp_endpoint: str | None
    export_timeout_seconds: float
    metric_export_interval_seconds: float


class RedMetrics:
    """Three explicit, low-cardinality application RED instruments."""

    def __init__(self, meter_provider: MeterProvider) -> None:
        meter = meter_provider.get_meter("observable-url-shortener.red", SERVICE_VERSION)
        self._requests = meter.create_counter(
            METRIC_REQUESTS,
            unit="{request}",
            description="Incoming application HTTP requests",
        )
        self._errors = meter.create_counter(
            METRIC_ERRORS,
            unit="{error}",
            description="Application HTTP responses with status >= 500",
        )
        self._duration = meter.create_histogram(
            METRIC_DURATION,
            unit="s",
            description="Application HTTP request duration",
        )

    def record(self, method: str, route: str, status_code: int, duration_seconds: float) -> None:
        attributes = {
            "http.request.method": method,
            "http.route": route,
            "http.response.status_code": status_code,
        }
        self._requests.add(1, attributes)
        if status_code >= 500:
            self._errors.add(1, attributes)
        self._duration.record(duration_seconds, attributes)


class TelemetryRuntime:
    """Own providers, exporters, instrumentation, and their bounded shutdown."""

    def __init__(
        self,
        config: TelemetryConfig,
        *,
        span_exporter: SpanExporter | None = None,
        metric_exporter: MetricExporter | None = None,
        synchronous_spans: bool = False,
    ) -> None:
        self.config = config
        self.registry = CollectorRegistry(auto_describe=True)
        resource = Resource.create(
            {
                ResourceAttributes.SERVICE_NAME: config.service_name,
                ResourceAttributes.SERVICE_VERSION: SERVICE_VERSION,
            }
        )

        self.tracer_provider = TracerProvider(resource=resource)
        effective_span_exporter = span_exporter or self._otlp_span_exporter(config)
        if effective_span_exporter is not None:
            processor = (
                SimpleSpanProcessor(effective_span_exporter)
                if synchronous_spans
                else BatchSpanProcessor(effective_span_exporter)
            )
            self.tracer_provider.add_span_processor(processor)

        prometheus_reader = PrometheusMetricReader(registry=self.registry)
        metric_readers = [prometheus_reader]
        effective_metric_exporter = metric_exporter or self._otlp_metric_exporter(config)
        if effective_metric_exporter is not None:
            metric_readers.append(
                PeriodicExportingMetricReader(
                    effective_metric_exporter,
                    export_interval_millis=config.metric_export_interval_seconds * 1000,
                    export_timeout_millis=config.export_timeout_seconds * 1000,
                )
            )
        self.meter_provider = MeterProvider(
            resource=resource,
            metric_readers=metric_readers,
            views=[
                View(
                    instrument_name=METRIC_DURATION,
                    aggregation=ExplicitBucketHistogramAggregation(
                        boundaries=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)
                    ),
                )
            ],
        )
        self.red_metrics = RedMetrics(self.meter_provider)
        self._shutdown_lock = Lock()
        self._shutdown = False

    @staticmethod
    def _otlp_span_exporter(config: TelemetryConfig) -> SpanExporter | None:
        if config.otlp_endpoint is None:
            return None
        return OTLPSpanExporter(
            endpoint=f"{config.otlp_endpoint}/v1/traces",
            timeout=config.export_timeout_seconds,
        )

    @staticmethod
    def _otlp_metric_exporter(config: TelemetryConfig) -> MetricExporter | None:
        if config.otlp_endpoint is None:
            return None
        return OTLPMetricExporter(
            endpoint=f"{config.otlp_endpoint}/v1/metrics",
            timeout=config.export_timeout_seconds,
        )

    def instrument_fastapi(self, application: FastAPI) -> None:
        FastAPIInstrumentor.instrument_app(
            application,
            tracer_provider=self.tracer_provider,
            meter_provider=NoOpMeterProvider(),
            excluded_urls=_EXCLUDED_URLS_PATTERN,
            exclude_spans=["receive", "send"],
        )

    def instrument_httpx(self, client: httpx.AsyncClient) -> None:
        HTTPXClientInstrumentor.instrument_client(
            client,
            tracer_provider=self.tracer_provider,
            meter_provider=NoOpMeterProvider(),
        )

    def uninstrument_httpx(self, client: httpx.AsyncClient) -> None:
        HTTPXClientInstrumentor.uninstrument_client(client)

    def prometheus_payload(self) -> bytes:
        return generate_latest(self.registry)

    async def ashutdown(self) -> None:
        with self._shutdown_lock:
            if self._shutdown:
                return
            self._shutdown = True
        timeout_millis = self.config.export_timeout_seconds * 1000
        # Provider shutdown drains the batch span queue and performs the metric reader's final
        # collection. Run the independent providers concurrently so an unavailable backend costs
        # one bounded exporter timeout rather than a serial force-flush/shutdown retry chain.
        await asyncio.gather(
            asyncio.to_thread(self.tracer_provider.shutdown),
            asyncio.to_thread(
                self.meter_provider.shutdown,
                timeout_millis=timeout_millis,
            ),
        )
