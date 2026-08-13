"""Dependency-free smoke test for the real Docker Compose HTTP path."""

from __future__ import annotations

import http.client
import json
import os
import re
import subprocess
import time
import uuid
from email.message import Message
from urllib.parse import urlsplit

TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
SPAN_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")


def compose_logs(service: str) -> str:
    """Read one Compose service's logs without container-name prefixes."""

    completed = subprocess.run(  # noqa: S603 - fixed local validation command, no shell
        ["docker", "compose", "logs", "--no-color", "--no-log-prefix", service],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    return completed.stdout


def compose_application_logs(service: str) -> list[dict[str, object]]:
    """Read parseable application JSON entries from one Compose service."""

    entries: list[dict[str, object]] = []
    for line in compose_logs(service).splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and "event" in entry:
            entries.append(entry)
    return entries


def wait_for_correlated_log(
    service: str, correlation_id: str, timeout_seconds: float = 10.0
) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        matching = [
            entry
            for entry in compose_application_logs(service)
            if entry.get("correlation_id") == correlation_id
        ]
        if matching:
            return matching[-1]
        time.sleep(0.2)
    raise RuntimeError(f"no correlated JSON log found for {service}: {correlation_id}")


def call(
    method: str,
    url: str,
    *,
    correlation_id: str,
    body: dict[str, str] | None = None,
) -> tuple[int, Message, bytes]:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or not parsed.hostname:
        raise RuntimeError(f"smoke test supports local HTTP URLs only: {url}")
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    payload = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json", "X-Correlation-ID": correlation_id}
    if payload is not None:
        headers["Content-Type"] = "application/json"

    connection = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=5)
    try:
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        response_body = response.read()
        return response.status, response.headers, response_body
    finally:
        connection.close()


def wait_until_ready(base_url: str, timeout_seconds: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            status, _headers, _body = call(
                "GET",
                f"{base_url}/readyz",
                correlation_id="smoke-readiness",
            )
            if status == 200:
                return
        except OSError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"service did not become ready: {base_url}")


def telemetry_events(raw_logs: str, signal: str) -> list[str]:
    """Split Collector debug output into individual trace or metric exports."""

    events = re.split(
        r"(?=^\d{4}-\d{2}-\d{2}T.*\tinfo\t(?:Traces|Metrics)\t\{)",
        raw_logs,
        flags=re.MULTILINE,
    )
    marker = f'"otelcol.signal": "{signal}"'
    return [event for event in events if marker in event[:1000]]


def exported_spans(event: str, trace_id: str) -> list[tuple[str, str, str]]:
    """Return (parent ID, span ID, kind) from one detailed trace export."""

    pattern = re.compile(
        rf"Trace ID\s*:\s*{re.escape(trace_id)}\s+"
        r"Parent ID\s*:\s*([0-9a-f]*)\s+"
        r"ID\s*:\s*([0-9a-f]{16})\s+"
        r"Name\s*:\s*.*?\s+"
        r"Kind\s*:\s*(Server|Client)",
        flags=re.DOTALL,
    )
    return pattern.findall(event)


def wait_for_collector_evidence(
    trace_id: str,
    resolver_span_id: str,
    shortener_span_id: str,
    timeout_seconds: float = 15.0,
) -> str:
    """Prove trace topology and OTLP metrics from Collector debug output."""

    deadline = time.monotonic() + timeout_seconds
    last_reason = "Collector output was empty"
    while time.monotonic() < deadline:
        raw_logs = compose_logs("otel-collector")
        trace_events = [
            event for event in telemetry_events(raw_logs, "traces") if trace_id in event
        ]
        resolver_events = [
            event for event in trace_events if "service.name: Str(resolver)" in event
        ]
        shortener_events = [
            event for event in trace_events if "service.name: Str(shortener)" in event
        ]

        resolver_spans = [
            span for event in resolver_events for span in exported_spans(event, trace_id)
        ]
        shortener_spans = [
            span for event in shortener_events for span in exported_spans(event, trace_id)
        ]
        resolver_server = next(
            (
                span
                for span in resolver_spans
                if span[1] == resolver_span_id and span[2] == "Server"
            ),
            None,
        )
        resolver_client = next(
            (
                span
                for span in resolver_spans
                if span[0] == resolver_span_id and span[2] == "Client"
            ),
            None,
        )
        shortener_server = next(
            (
                span
                for span in shortener_spans
                if span[1] == shortener_span_id and span[2] == "Server"
            ),
            None,
        )
        topology_ok = bool(
            resolver_server
            and resolver_client
            and shortener_server
            and shortener_server[0] == resolver_client[1]
        )

        metric_events = telemetry_events(raw_logs, "metrics")
        resolver_metrics_ok = any(
            "service.name: Str(resolver)" in event
            and "Name: url_shortener.http.server.requests" in event
            and "Name: url_shortener.http.server.request.duration" in event
            and "http.route: Str(/{code})" in event
            and "http.response.status_code: Int(302)" in event
            for event in metric_events
        )
        shortener_metrics_ok = any(
            "service.name: Str(shortener)" in event
            and "Name: url_shortener.http.server.requests" in event
            and "Name: url_shortener.http.server.request.duration" in event
            and "http.route: Str(/internal/v1/urls/{code})" in event
            and "http.response.status_code: Int(200)" in event
            for event in metric_events
        )
        if topology_ok and resolver_metrics_ok and shortener_metrics_ok:
            assert resolver_client is not None
            return resolver_client[1]

        last_reason = (
            f"topology={topology_ok}, resolver_metrics={resolver_metrics_ok}, "
            f"shortener_metrics={shortener_metrics_ok}"
        )
        time.sleep(0.25)
    raise RuntimeError(f"Collector evidence incomplete: {last_reason}")


def assert_metrics(
    service: str,
    base_url: str,
    expected_route: str,
    *,
    forbidden_values: tuple[str, ...],
) -> str:
    """Validate scrape output and its bounded label strategy."""

    status, headers, raw_body = call(
        "GET",
        f"{base_url}/metrics",
        correlation_id=f"smoke-metrics-{service}",
    )
    assert status == 200, (status, raw_body)
    assert headers.get_content_type() == "text/plain"
    payload = raw_body.decode()
    assert "url_shortener_http_server_requests_total" in payload
    assert "url_shortener_http_server_request_duration_seconds_count" in payload
    assert f'http_route="{expected_route}"' in payload
    assert 'http_response_status_code="' in payload
    assert 'http_request_method="' in payload
    assert 'http_route="/healthz"' not in payload
    assert 'http_route="/readyz"' not in payload
    assert 'http_route="/metrics"' not in payload
    for value in forbidden_values:
        assert value not in payload
    return payload


def main() -> None:
    shortener_url = os.getenv("SHORTENER_URL", "http://localhost:8080").rstrip("/")
    resolver_url = os.getenv("RESOLVER_URL", "http://localhost:8081").rstrip("/")
    target_url = "https://example.com/smoke-target"

    wait_until_ready(shortener_url)
    wait_until_ready(resolver_url)

    create_id = f"smoke-create-{uuid.uuid4()}"
    status, headers, raw_body = call(
        "POST",
        f"{shortener_url}/v1/urls",
        body={"url": target_url},
        correlation_id=create_id,
    )
    assert status == 201, (status, raw_body)
    assert headers.get("X-Correlation-ID") == create_id
    created = json.loads(raw_body)
    code = created["code"]
    assert created["short_url"] == f"{resolver_url}/{code}"

    resolve_id = f"smoke-resolve-{uuid.uuid4()}"
    status, headers, raw_body = call(
        "GET",
        f"{resolver_url}/{code}",
        correlation_id=resolve_id,
    )
    assert status == 302, (status, raw_body)
    assert headers.get("Location") == target_url
    assert headers.get("X-Correlation-ID") == resolve_id

    # The 302 proves the strict echo contract; logs prove both processes emitted the same ID.
    shortener_log = wait_for_correlated_log("shortener", resolve_id)
    resolver_log = wait_for_correlated_log("resolver", resolve_id)
    for service, entry in (("shortener", shortener_log), ("resolver", resolver_log)):
        assert entry["service"] == service
        assert entry["severity"] in {"INFO", "ERROR"}
        assert entry["event"]
        assert entry["timestamp"]
        assert TRACE_ID_PATTERN.fullmatch(str(entry["trace_id"]))
        assert SPAN_ID_PATTERN.fullmatch(str(entry["span_id"]))
        assert entry["trace_sampled"] is True
    trace_id = str(resolver_log["trace_id"])
    resolver_span_id = str(resolver_log["span_id"])
    shortener_span_id = str(shortener_log["span_id"])
    assert shortener_log["trace_id"] == trace_id
    assert shortener_span_id != resolver_span_id
    assert trace_id != resolve_id
    combined_logs = json.dumps([shortener_log, resolver_log])
    assert target_url not in combined_logs

    forbidden_values = (code, resolve_id, trace_id, target_url)
    shortener_metrics = assert_metrics(
        "shortener",
        shortener_url,
        "/internal/v1/urls/{code}",
        forbidden_values=forbidden_values,
    )
    resolver_metrics = assert_metrics(
        "resolver",
        resolver_url,
        "/{code}",
        forbidden_values=forbidden_values,
    )
    # Error counters are created lazily: with only 2xx/3xx traffic their absence is zero.
    assert "url_shortener_http_server_errors_total" not in shortener_metrics
    assert "url_shortener_http_server_errors_total" not in resolver_metrics

    client_span_id = wait_for_collector_evidence(
        trace_id,
        resolver_span_id,
        shortener_span_id,
    )

    print(
        f"PASS code={code} correlation_id={resolve_id} trace_id={trace_id} "
        f"resolver_span_id={resolver_span_id} client_span_id={client_span_id} "
        f"shortener_span_id={shortener_span_id}"
    )
    print(f"SHORTENER_LOG {json.dumps(shortener_log, separators=(',', ':'))}")
    print(f"RESOLVER_LOG {json.dumps(resolver_log, separators=(',', ':'))}")


if __name__ == "__main__":
    main()
