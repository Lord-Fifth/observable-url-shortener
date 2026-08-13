from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from shortener.config import Settings
from shortener.main import create_app
from shortener.repository import InMemoryUrlRepository


@pytest.fixture
def shortener_client() -> Iterator[tuple[TestClient, InMemoryUrlRepository]]:
    repository = InMemoryUrlRepository()
    app = create_app(
        settings=Settings(
            resolver_base_url="http://resolver.test",
            code_length=8,
            max_code_attempts=5,
        ),
        repository_factory=lambda: repository,
    )
    with TestClient(app) as client:
        yield client, repository
    assert repository.closed


def test_valid_url_creates_and_retrieves_mapping(
    shortener_client: tuple[TestClient, InMemoryUrlRepository],
) -> None:
    client, _repository = shortener_client

    created = client.post("/v1/urls", json={"url": "https://example.com/some/path"})

    assert created.status_code == 201
    body = created.json()
    assert len(body["code"]) == 8
    assert body["short_url"] == f"http://resolver.test/{body['code']}"

    retrieved = client.get(f"/internal/v1/urls/{body['code']}")
    assert retrieved.status_code == 200
    assert retrieved.json() == {
        "code": body["code"],
        "url": "https://example.com/some/path",
    }


@pytest.mark.parametrize(
    "invalid_url",
    [
        "not-a-url",
        "ftp://example.com/file",
        "https://",
        " https://example.com",
        "https://exa mple.com",
        "https://example.com/a b",
        "https://example.com:notaport/path",
        "https://%zz/path",
        "https://example.com/%zz",
        "https://example.com/a\x00b",
        "http:example.com",
        "http:/example.com",
        "http:///example.com",
        "http:\\example.com",
    ],
)
def test_invalid_url_is_rejected(
    shortener_client: tuple[TestClient, InMemoryUrlRepository], invalid_url: str
) -> None:
    client, _repository = shortener_client
    response = client.post(
        "/v1/urls",
        json={"url": invalid_url},
        headers={"X-Correlation-ID": "invalid-url"},
    )
    assert response.status_code == 422
    assert response.headers["X-Correlation-ID"] == "invalid-url"


def test_unknown_code_returns_404(
    shortener_client: tuple[TestClient, InMemoryUrlRepository],
) -> None:
    client, _repository = shortener_client
    response = client.get("/internal/v1/urls/missing")
    assert response.status_code == 404
    assert response.json() == {"detail": "code not found"}


def test_health_succeeds(
    shortener_client: tuple[TestClient, InMemoryUrlRepository],
) -> None:
    client, _repository = shortener_client
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_readiness_succeeds_after_lifespan_initialisation(
    shortener_client: tuple[TestClient, InMemoryUrlRepository],
) -> None:
    client, _repository = shortener_client
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_incoming_correlation_id_is_preserved(
    shortener_client: tuple[TestClient, InMemoryUrlRepository],
) -> None:
    client, _repository = shortener_client
    response = client.get("/healthz", headers={"X-Correlation-ID": "caller-123"})
    assert response.headers["X-Correlation-ID"] == "caller-123"


def test_missing_correlation_id_is_generated(
    shortener_client: tuple[TestClient, InMemoryUrlRepository],
) -> None:
    client, _repository = shortener_client
    response = client.get("/healthz")
    UUID(response.headers["X-Correlation-ID"])


def test_invalid_correlation_id_is_replaced(
    shortener_client: tuple[TestClient, InMemoryUrlRepository],
) -> None:
    client, _repository = shortener_client
    response = client.get("/healthz", headers={"X-Correlation-ID": " "})
    UUID(response.headers["X-Correlation-ID"])


def test_unhandled_error_is_generic_and_keeps_correlation_id() -> None:
    class ExplodingRepository(InMemoryUrlRepository):
        async def insert_if_absent(self, mapping: object) -> bool:
            raise RuntimeError("sensitive internal detail")

    app = create_app(
        settings=Settings("http://resolver.test", code_length=8, max_code_attempts=1),
        repository_factory=ExplodingRepository,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/urls",
            json={"url": "https://example.com"},
            headers={"X-Correlation-ID": "error-123"},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert "sensitive" not in response.text
    assert response.headers["X-Correlation-ID"] == "error-123"


@pytest.mark.asyncio
async def test_readiness_is_503_before_lifespan_initialisation() -> None:
    app = create_app(settings=Settings("http://resolver.test", 8, 5))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://shortener.test"
    ) as client:
        response = await client.get("/readyz", headers={"X-Correlation-ID": "not-ready-shortener"})

    assert response.status_code == 503
    assert response.json() == {"detail": "service is not ready"}
    assert response.headers["X-Correlation-ID"] == "not-ready-shortener"
