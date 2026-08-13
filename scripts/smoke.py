"""Dependency-free smoke test for the real Docker Compose HTTP path."""

from __future__ import annotations

import http.client
import json
import os
import time
import uuid
from email.message import Message
from urllib.parse import urlsplit


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

    # Resolver accepts the 302 only if shortener echoed this exact ID on the internal hop.
    print(f"PASS code={code} correlation_id={resolve_id}")


if __name__ == "__main__":
    main()
