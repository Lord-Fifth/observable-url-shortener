from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from shortener.config import Settings
from shortener.logging import JsonFormatter, logger
from shortener.main import create_app


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


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(Settings("http://resolver.test", code_length=8, max_code_attempts=5))
    with TestClient(app) as test_client:
        yield test_client


def test_request_completion_log_has_stable_json_schema(
    client: TestClient, captured_logs: JsonCaptureHandler
) -> None:
    response = client.get("/healthz", headers={"X-Correlation-ID": "schema-test"})

    completion = next(
        entry for entry in captured_logs.entries if entry["event"] == "http_request_completed"
    )
    assert response.status_code == 200
    assert completion == {
        **completion,
        "severity": "INFO",
        "service": "shortener",
        "event": "http_request_completed",
        "message": "HTTP request completed",
        "correlation_id": "schema-test",
        "method": "GET",
        "path": "/healthz",
        "status_code": 200,
    }
    assert isinstance(completion["duration_ms"], float)
    assert completion["duration_ms"] >= 0
    assert datetime.fromisoformat(str(completion["timestamp"]).replace("Z", "+00:00"))


def test_generated_correlation_id_appears_in_logs(
    client: TestClient, captured_logs: JsonCaptureHandler
) -> None:
    response = client.get("/readyz")
    generated_id = response.headers["X-Correlation-ID"]

    UUID(generated_id)
    assert any(
        entry["event"] == "http_request_completed" and entry["correlation_id"] == generated_id
        for entry in captured_logs.entries
    )


def test_sensitive_long_url_is_not_logged(
    client: TestClient, captured_logs: JsonCaptureHandler
) -> None:
    sensitive_url = "https://example.com/private?token=super-secret&customer=123"
    response = client.post(
        "/v1/urls",
        json={"url": sensitive_url},
        headers={"X-Correlation-ID": "privacy-test"},
    )

    assert response.status_code == 201
    serialized_logs = json.dumps(captured_logs.entries)
    assert sensitive_url not in serialized_logs
    assert "super-secret" not in serialized_logs
    assert any(entry["event"] == "url_mapping_created" for entry in captured_logs.entries)


def test_unknown_mapping_has_no_misleading_success_event(
    client: TestClient, captured_logs: JsonCaptureHandler
) -> None:
    response = client.get(
        "/internal/v1/urls/missing",
        headers={"X-Correlation-ID": "missing-test"},
    )

    assert response.status_code == 404
    events = [entry["event"] for entry in captured_logs.entries]
    assert "url_mapping_lookup_not_found" in events
    assert "url_mapping_lookup_succeeded" not in events
