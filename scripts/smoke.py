"""Dependency-free smoke test for the real Docker Compose HTTP path."""

from __future__ import annotations

import http.client
import json
import os
import subprocess
import time
import uuid
from email.message import Message
from urllib.parse import urlsplit


def compose_application_logs(service: str) -> list[dict[str, object]]:
    """Read parseable application JSON entries from one Compose service."""

    completed = subprocess.run(  # noqa: S603 - fixed local validation command, no shell
        ["docker", "compose", "logs", "--no-color", "--no-log-prefix", service],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    entries: list[dict[str, object]] = []
    for line in completed.stdout.splitlines():
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
    combined_logs = json.dumps([shortener_log, resolver_log])
    assert target_url not in combined_logs

    print(f"PASS code={code} correlation_id={resolve_id}")
    print(f"SHORTENER_LOG {json.dumps(shortener_log, separators=(',', ':'))}")
    print(f"RESOLVER_LOG {json.dumps(resolver_log, separators=(',', ':'))}")


if __name__ == "__main__":
    main()
