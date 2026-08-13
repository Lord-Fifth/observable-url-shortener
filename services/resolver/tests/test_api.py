from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from resolver.config import Settings
from resolver.main import create_app
from resolver.repository import InMemoryRedirectEventRepository


@dataclass(slots=True)
class Harness:
    client: TestClient
    repository: InMemoryRedirectEventRepository
    requests: list[httpx.Request]
    app: object


@pytest.fixture
def known_mapping_harness() -> Iterator[Harness]:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        correlation_id = request.headers["X-Correlation-ID"]
        code = request.url.path.rsplit("/", maxsplit=1)[-1]
        return httpx.Response(
            200,
            json={"code": code, "url": "https://example.com/destination"},
            headers={"X-Correlation-ID": correlation_id},
        )

    repository = InMemoryRedirectEventRepository()
    app = create_app(
        settings=Settings("http://shortener.test", shortener_timeout_seconds=0.5),
        event_repository_factory=lambda: repository,
        transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        yield Harness(client, repository, requests, app)
    assert repository.closed
    assert app.state.http_client.is_closed


def test_known_code_returns_302_with_correct_location(
    known_mapping_harness: Harness,
) -> None:
    response = known_mapping_harness.client.get(
        "/known", headers={"X-Correlation-ID": "resolve-123"}, follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "https://example.com/destination"


def test_openapi_contract_documents_302(known_mapping_harness: Harness) -> None:
    operation = known_mapping_harness.client.get("/openapi.json").json()["paths"]["/{code}"]["get"]
    assert "302" in operation["responses"]
    assert "307" not in operation["responses"]


def test_successful_redirect_event_is_recorded(known_mapping_harness: Harness) -> None:
    before = datetime.now(UTC)
    response = known_mapping_harness.client.get(
        "/known", headers={"X-Correlation-ID": "event-123"}, follow_redirects=False
    )
    after = datetime.now(UTC)
    assert response.status_code == 302
    assert len(known_mapping_harness.repository.events) == 1
    event = known_mapping_harness.repository.events[0]
    assert event.code == "known"
    assert event.destination_url == "https://example.com/destination"
    assert event.correlation_id == "event-123"
    assert before <= event.occurred_at <= after


def test_incoming_correlation_id_is_preserved_and_propagated(
    known_mapping_harness: Harness,
) -> None:
    response = known_mapping_harness.client.get(
        "/known", headers={"X-Correlation-ID": "same-hop-id"}, follow_redirects=False
    )
    assert response.headers["X-Correlation-ID"] == "same-hop-id"
    assert known_mapping_harness.requests[0].headers["X-Correlation-ID"] == "same-hop-id"


def test_missing_correlation_id_is_generated_and_propagated(
    known_mapping_harness: Harness,
) -> None:
    response = known_mapping_harness.client.get("/known", follow_redirects=False)
    generated = response.headers["X-Correlation-ID"]
    UUID(generated)
    assert known_mapping_harness.requests[0].headers["X-Correlation-ID"] == generated


def test_unknown_code_becomes_404() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"detail": "code not found"},
            headers={"X-Correlation-ID": request.headers["X-Correlation-ID"]},
        )

    repository = InMemoryRedirectEventRepository()
    app = create_app(
        Settings("http://shortener.test", 0.5),
        event_repository_factory=lambda: repository,
        transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        response = client.get("/missing", headers={"X-Correlation-ID": "missing-id"})
        assert response.status_code == 404
        assert response.json() == {"detail": "code not found"}
        assert response.headers["X-Correlation-ID"] == "missing-id"
        assert repository.events == ()


@pytest.mark.parametrize("upstream_status", [500, 502])
def test_upstream_failure_becomes_503(upstream_status: int) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            upstream_status,
            headers={"X-Correlation-ID": request.headers["X-Correlation-ID"]},
        )

    app = create_app(
        Settings("http://shortener.test", 0.5),
        transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        response = client.get("/known")
    assert response.status_code == 503
    assert response.json() == {"detail": "mapping service unavailable"}


def test_transport_failure_becomes_503() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unavailable", request=request)

    app = create_app(
        Settings("http://shortener.test", 0.5),
        transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        response = client.get("/known")
    assert response.status_code == 503


def test_upstream_correlation_mismatch_becomes_503() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "known", "url": "https://example.com"},
            headers={"X-Correlation-ID": "different"},
        )

    app = create_app(
        Settings("http://shortener.test", 0.5),
        transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        response = client.get("/known")
    assert response.status_code == 503


@pytest.mark.parametrize(
    "invalid_url",
    [
        "https://example.com/not valid",
        "https://%zz/path",
        "https://example.com/%zz",
        "https://example.com/a\x00b",
        "http:example.com",
        "http:/example.com",
        "http:///example.com",
        "http:\\example.com",
    ],
)
def test_invalid_upstream_redirect_url_becomes_503_without_event(invalid_url: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "known", "url": invalid_url},
            headers={"X-Correlation-ID": request.headers["X-Correlation-ID"]},
        )

    repository = InMemoryRedirectEventRepository()
    app = create_app(
        Settings("http://shortener.test", 0.5),
        event_repository_factory=lambda: repository,
        transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        response = client.get("/known", follow_redirects=False)
        assert repository.events == ()

    assert response.status_code == 503
    assert "Location" not in response.headers


@pytest.mark.parametrize(
    "upstream_body",
    [
        b"not-json",
        {"code": "known"},
        {"code": "different", "url": "https://example.com"},
    ],
)
def test_invalid_upstream_contract_becomes_503_without_event(
    upstream_body: bytes | dict[str, str],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        arguments: dict[str, object]
        if isinstance(upstream_body, bytes):
            arguments = {"content": upstream_body}
        else:
            arguments = {"json": upstream_body}
        return httpx.Response(
            200,
            headers={"X-Correlation-ID": request.headers["X-Correlation-ID"]},
            **arguments,
        )

    repository = InMemoryRedirectEventRepository()
    app = create_app(
        Settings("http://shortener.test", 0.5),
        event_repository_factory=lambda: repository,
        transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        response = client.get(
            "/known",
            headers={"X-Correlation-ID": "invalid-upstream"},
            follow_redirects=False,
        )
        assert repository.events == ()

    assert response.status_code == 503
    assert response.json() == {"detail": "mapping service unavailable"}
    assert response.headers["X-Correlation-ID"] == "invalid-upstream"
    assert "Location" not in response.headers


def test_redirect_event_failure_fails_closed_without_leaking_details() -> None:
    class ExplodingEventRepository(InMemoryRedirectEventRepository):
        async def record(self, event: object) -> None:
            raise RuntimeError("sensitive event-store detail")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "known", "url": "https://example.com"},
            headers={"X-Correlation-ID": request.headers["X-Correlation-ID"]},
        )

    app = create_app(
        Settings("http://shortener.test", 0.5),
        event_repository_factory=ExplodingEventRepository,
        transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        response = client.get(
            "/known", headers={"X-Correlation-ID": "event-failure"}, follow_redirects=False
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "redirect event could not be recorded"}
    assert response.headers["X-Correlation-ID"] == "event-failure"
    assert "sensitive" not in response.text
    assert "Location" not in response.headers


def test_unhandled_error_is_generic_and_keeps_correlation_id() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        raise RuntimeError("sensitive internal detail")

    app = create_app(
        Settings("http://shortener.test", 0.5),
        transport=httpx.MockTransport(handler),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/known",
            headers={"X-Correlation-ID": "error-456"},
            follow_redirects=False,
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert "sensitive" not in response.text
    assert response.headers["X-Correlation-ID"] == "error-456"


def test_health_succeeds_without_upstream_call(known_mapping_harness: Harness) -> None:
    response = known_mapping_harness.client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
    assert known_mapping_harness.requests == []


def test_readiness_succeeds_without_upstream_call(known_mapping_harness: Harness) -> None:
    response = known_mapping_harness.client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert known_mapping_harness.requests == []


@pytest.mark.asyncio
async def test_readiness_is_503_before_lifespan_initialisation() -> None:
    app = create_app(Settings("http://shortener.test", 0.5))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://resolver.test"
    ) as client:
        response = await client.get("/readyz", headers={"X-Correlation-ID": "not-ready-resolver"})

    assert response.status_code == 503
    assert response.json() == {"detail": "service is not ready"}
    assert response.headers["X-Correlation-ID"] == "not-ready-resolver"


def test_repository_closes_when_http_client_initialisation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = InMemoryRedirectEventRepository()
    app = create_app(
        Settings("http://shortener.test", 0.5),
        event_repository_factory=lambda: repository,
    )

    def fail_client_initialisation(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("client initialisation failed")

    monkeypatch.setattr("resolver.main.httpx.AsyncClient", fail_client_initialisation)

    with pytest.raises(RuntimeError, match="client initialisation failed"), TestClient(app):
        pass

    assert repository.closed
    assert app.state.ready is False
