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
COLLECTOR_RESOURCE_PATTERN = re.compile(
    r"^(?:\S+\tinfo\t)?(ResourceSpans|ResourceMetrics) #\d+\s*$",
    flags=re.MULTILINE,
)
COMPOSE_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+\s+\|\s?")
ExportedSpan = tuple[str, str, str, str]


def compose_logs(service: str) -> str:
    """Read one Compose service's logs without container-name prefixes."""

    completed = subprocess.run(  # noqa: S603 - fixed local validation command, no shell
        ["docker", "compose", "logs", "--no-color", "--no-log-prefix", service],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    streams = [stream.rstrip("\r\n") for stream in (completed.stdout, completed.stderr) if stream]
    return "\n".join(streams)


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


def _normalize_compose_prefixes(raw_logs: str) -> str:
    """Remove optional Linux Compose service prefixes without altering payload lines."""

    return "\n".join(
        COMPOSE_PREFIX_PATTERN.sub("", line, count=1) for line in raw_logs.splitlines()
    )


def _collector_events(raw_logs: str, signal: str) -> list[str]:
    """Return detailed Collector resource payloads independent of exporter headlines."""

    resource_type = {"traces": "ResourceSpans", "metrics": "ResourceMetrics"}[signal]
    normalized = _normalize_compose_prefixes(raw_logs)
    matches = list(COLLECTOR_RESOURCE_PATTERN.finditer(normalized))
    return [
        normalized[match.start() : matches[index + 1].start() if index + 1 < len(matches) else None]
        for index, match in enumerate(matches)
        if match.group(1) == resource_type
    ]


def _exported_spans(raw_logs: str, trace_id: str) -> list[ExportedSpan]:
    """Return (service, parent ID, span ID, kind) from detailed resource payloads."""

    span_pattern = re.compile(
        rf"Trace ID\s*:\s*{re.escape(trace_id)}\s+"
        r"Parent ID\s*:\s*([0-9a-f]*)\s+"
        r"ID\s*:\s*([0-9a-f]{16})\s+"
        r"Name\s*:\s*.*?\s+"
        r"Kind\s*:\s*(Server|Client)",
        flags=re.DOTALL,
    )
    spans: list[ExportedSpan] = []
    for event in _collector_events(raw_logs, "traces"):
        service_match = re.search(r"service\.name:\s*Str\(([^)]+)\)", event)
        if service_match is None:
            continue
        service = service_match.group(1)
        spans.extend(
            (service, parent_id, span_id, kind)
            for parent_id, span_id, kind in span_pattern.findall(event)
        )
    return spans


def _strict_client_span_id(
    spans: list[ExportedSpan],
    resolver_span_id: str,
    shortener_span_id: str,
) -> str | None:
    """Return the resolver CLIENT span only for the exact required three-span chain."""

    resolver_server = next(
        (
            span
            for span in spans
            if span[0] == "resolver"
            and span[1] == ""
            and span[2] == resolver_span_id
            and span[3] == "Server"
        ),
        None,
    )
    shortener_server = next(
        (
            span
            for span in spans
            if span[0] == "shortener" and span[2] == shortener_span_id and span[3] == "Server"
        ),
        None,
    )
    if resolver_server is None or shortener_server is None:
        return None

    return next(
        (
            span[2]
            for span in spans
            if span[0] == "resolver"
            and span[1] == resolver_span_id
            and span[3] == "Client"
            and shortener_server[1] == span[2]
        ),
        None,
    )


def wait_for_collector_evidence(
    trace_id: str,
    resolver_span_id: str,
    shortener_span_id: str,
    timeout_seconds: float = 15.0,
) -> str:
    """Prove trace topology and OTLP metrics from Collector debug output."""

    deadline = time.monotonic() + timeout_seconds
    last_reason = "Collector output was empty"
    observed_spans: dict[tuple[str, str], ExportedSpan] = {}
    resolver_metrics_ok = False
    shortener_metrics_ok = False
    while time.monotonic() < deadline:
        raw_logs = compose_logs("otel-collector")
        for span in _exported_spans(raw_logs, trace_id):
            observed_spans[(span[0], span[2])] = span
        client_span_id = _strict_client_span_id(
            list(observed_spans.values()), resolver_span_id, shortener_span_id
        )
        topology_ok = client_span_id is not None

        metric_events = _collector_events(raw_logs, "metrics")
        resolver_metrics_ok = resolver_metrics_ok or any(
            "service.name: Str(resolver)" in event
            and "Name: url_shortener.http.server.requests" in event
            and "Name: url_shortener.http.server.request.duration" in event
            and "http.route: Str(/{code})" in event
            and "http.response.status_code: Int(302)" in event
            for event in metric_events
        )
        shortener_metrics_ok = shortener_metrics_ok or any(
            "service.name: Str(shortener)" in event
            and "Name: url_shortener.http.server.requests" in event
            and "Name: url_shortener.http.server.request.duration" in event
            and "http.route: Str(/internal/v1/urls/{code})" in event
            and "http.response.status_code: Int(200)" in event
            for event in metric_events
        )
        if topology_ok and resolver_metrics_ok and shortener_metrics_ok:
            assert client_span_id is not None
            return client_span_id

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
