"""Tiny live-cloud acceptance and durability checks for Azure Container Apps."""

from __future__ import annotations

import argparse
import http.client
import json
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
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise RuntimeError(f"Azure smoke requires a credential-free HTTPS URL: {url}")
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    payload = None if body is None else json.dumps(body).encode()
    headers = {"Accept": "application/json", "X-Correlation-ID": correlation_id}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    connection = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443, timeout=20)
    try:
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        return response.status, response.headers, response.read()
    finally:
        connection.close()


def wait_for_status(base_url: str, path: str, timeout_seconds: float = 180.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_result: object = "no response"
    while time.monotonic() < deadline:
        try:
            status, _headers, body = call(
                "GET",
                f"{base_url}{path}",
                correlation_id=f"azure-wait-{uuid.uuid4()}",
            )
            last_result = (status, body)
            if status == 200:
                return
        except OSError as exc:
            last_result = exc
        time.sleep(2)
    raise RuntimeError(f"endpoint did not become ready: {base_url}{path}: {last_result}")


def assert_resolves(
    resolver_url: str,
    code: str,
    target_url: str,
    correlation_id: str,
) -> None:
    status, headers, body = call(
        "GET",
        f"{resolver_url}/{code}",
        correlation_id=correlation_id,
    )
    assert status == 302, (status, body)
    assert headers.get("Location") == target_url
    assert headers.get("X-Correlation-ID") == correlation_id


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shortener-url", required=True)
    parser.add_argument("--resolver-url", required=True)
    parser.add_argument("--existing-code")
    parser.add_argument("--expected-target")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    shortener_url = args.shortener_url.rstrip("/")
    resolver_url = args.resolver_url.rstrip("/")

    for base_url in (shortener_url, resolver_url):
        wait_for_status(base_url, "/healthz")
        wait_for_status(base_url, "/readyz")

    if args.existing_code:
        if not args.expected_target:
            raise RuntimeError("--expected-target is required with --existing-code")
        correlation_id = f"azure-durability-{uuid.uuid4()}"
        assert_resolves(
            resolver_url,
            args.existing_code,
            args.expected_target,
            correlation_id,
        )
        print(
            json.dumps(
                {
                    "code": args.existing_code,
                    "target_url": args.expected_target,
                    "correlation_id": correlation_id,
                    "durability": "passed",
                },
                separators=(",", ":"),
            )
        )
        return

    target_url = f"https://example.com/azure-smoke/{uuid.uuid4()}"
    correlation_id = f"azure-smoke-{uuid.uuid4()}"
    status, headers, body = call(
        "POST",
        f"{shortener_url}/v1/urls",
        correlation_id=correlation_id,
        body={"url": target_url},
    )
    assert status == 201, (status, body)
    assert headers.get("X-Correlation-ID") == correlation_id
    created = json.loads(body)
    code = created["code"]
    assert created["short_url"] == f"{resolver_url}/{code}"

    assert_resolves(resolver_url, code, target_url, correlation_id)

    missing_id = f"azure-missing-{uuid.uuid4()}"
    status, headers, body = call(
        "GET",
        f"{resolver_url}/missing-{uuid.uuid4().hex}",
        correlation_id=missing_id,
    )
    assert status == 404, (status, body)
    assert headers.get("X-Correlation-ID") == missing_id

    # A fresh connection proves a subsequent lookup and another fail-closed event write.
    later_id = f"azure-later-{uuid.uuid4()}"
    assert_resolves(resolver_url, code, target_url, later_id)
    print(
        json.dumps(
            {
                "code": code,
                "target_url": target_url,
                "correlation_id": correlation_id,
                "later_correlation_id": later_id,
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
