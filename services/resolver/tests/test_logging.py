from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterator
from datetime import datetime
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from resolver.config import Settings
from resolver.correlation import get_correlation_id
from resolver.logging import JsonFormatter, logger
from resolver.main import create_app


class JsonCaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.entries: list[dict[str, object]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.entries.append(json.loads(self.format(record)))


@pytest.fixture
def captured_logs() -> Iterator[JsonCaptureHandler]:
    handler = JsonCaptureHandler()
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)


def test_upstream_failure_is_error_logged_and_remains_503(
    captured_logs: JsonCaptureHandler,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sensitive connection detail", request=request)

    app = create_app(
        Settings("http://shortener.test", 0.5),
        transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        response = client.get(
            "/known",
            headers={"X-Correlation-ID": "upstream-failure"},
            follow_redirects=False,
        )

    assert response.status_code == 503
    error = next(
        entry for entry in captured_logs.entries if entry["event"] == "shortener_upstream_failed"
    )
    assert error["severity"] == "ERROR"
    assert error["service"] == "resolver"
    assert error["correlation_id"] == "upstream-failure"
    assert error["upstream_service"] == "shortener"
    assert error["operation"] == "lookup_mapping"
    assert "sensitive connection detail" not in json.dumps(captured_logs.entries)
    completion = next(
        entry for entry in captured_logs.entries if entry["event"] == "http_request_completed"
    )
    assert completion["severity"] == "ERROR"
    assert completion["status_code"] == 503
    assert datetime.fromisoformat(str(completion["timestamp"]).replace("Z", "+00:00"))


def test_unknown_mapping_does_not_log_redirect_success(
    captured_logs: JsonCaptureHandler,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            headers={"X-Correlation-ID": request.headers["X-Correlation-ID"]},
        )

    app = create_app(
        Settings("http://shortener.test", 0.5),
        transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        response = client.get(
            "/missing",
            headers={"X-Correlation-ID": "missing-resolver"},
            follow_redirects=False,
        )

    assert response.status_code == 404
    events = [entry["event"] for entry in captured_logs.entries]
    assert "redirect_mapping_not_found" in events
    assert "redirect_resolved" not in events
    assert "redirect_event_recorded" not in events


def test_generated_correlation_id_appears_in_resolver_and_upstream_logs(
    captured_logs: JsonCaptureHandler,
) -> None:
    outbound_ids: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        correlation_id = request.headers["X-Correlation-ID"]
        outbound_ids.append(correlation_id)
        return httpx.Response(
            200,
            json={"code": "known", "url": "https://example.com"},
            headers={"X-Correlation-ID": correlation_id},
        )

    app = create_app(
        Settings("http://shortener.test", 0.5),
        transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        response = client.get("/known", follow_redirects=False)

    generated_id = response.headers["X-Correlation-ID"]
    UUID(generated_id)
    assert outbound_ids == [generated_id]
    assert all(entry["correlation_id"] == generated_id for entry in captured_logs.entries)


@pytest.mark.asyncio
async def test_concurrent_requests_do_not_leak_correlation_context(
    captured_logs: JsonCaptureHandler,
) -> None:
    both_arrived = asyncio.Event()
    arrival_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal arrival_count
        arrival_count += 1
        if arrival_count == 2:
            both_arrived.set()
        await asyncio.wait_for(both_arrived.wait(), timeout=1)
        code = request.url.path.rsplit("/", maxsplit=1)[-1]
        correlation_id = request.headers["X-Correlation-ID"]
        return httpx.Response(
            200,
            json={"code": code, "url": f"https://example.com/{code}"},
            headers={"X-Correlation-ID": correlation_id},
        )

    app = create_app(
        Settings("http://shortener.test", 1.0),
        transport=httpx.MockTransport(handler),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://resolver.test",
            follow_redirects=False,
        ) as client,
    ):
        first, second = await asyncio.gather(
            client.get("/first", headers={"X-Correlation-ID": "correlation-first"}),
            client.get("/second", headers={"X-Correlation-ID": "correlation-second"}),
        )

    assert first.status_code == second.status_code == 302
    completion_by_path = {
        str(entry["path"]): entry
        for entry in captured_logs.entries
        if entry["event"] == "http_request_completed"
    }
    assert completion_by_path["/first"]["correlation_id"] == "correlation-first"
    assert completion_by_path["/second"]["correlation_id"] == "correlation-second"
    assert len(str(completion_by_path["/first"]["trace_id"])) == 32
    assert len(str(completion_by_path["/second"]["trace_id"])) == 32
    assert completion_by_path["/first"]["trace_id"] != completion_by_path["/second"]["trace_id"]
    assert completion_by_path["/first"]["trace_id"] != "correlation-first"
    assert completion_by_path["/second"]["trace_id"] != "correlation-second"
    assert len(str(completion_by_path["/first"]["span_id"])) == 16
    assert len(str(completion_by_path["/second"]["span_id"])) == 16
    assert completion_by_path["/first"]["trace_sampled"] is True
    assert completion_by_path["/second"]["trace_sampled"] is True
    for entry in captured_logs.entries:
        if entry.get("code") == "first":
            assert entry["correlation_id"] == "correlation-first"
        if entry.get("code") == "second":
            assert entry["correlation_id"] == "correlation-second"
    assert get_correlation_id() is None
