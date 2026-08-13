from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from resolver.config import Settings
from resolver.main import create_app
from resolver.repository import (
    CosmosRedirectEventRepository,
    RedirectEvent,
    create_cosmos_redirect_event_repository,
)


class FakeContainer:
    def __init__(self) -> None:
        self.documents: list[dict[str, Any]] = []
        self.create_error: Exception | None = None

    async def create_item(self, body: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        if self.create_error is not None:
            raise self.create_error
        self.documents.append(dict(body))
        return body


class FakeCloseable:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_cosmos_factory_uses_default_azure_credential_and_enters_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential = FakeCloseable()
    container = FakeContainer()

    class FakeDatabase:
        def get_container_client(self, name: str) -> FakeContainer:
            assert name == "redirect_events"
            return container

    class FakeClient(FakeCloseable):
        def __init__(self, endpoint: str, *, credential: object) -> None:
            super().__init__()
            assert endpoint == "https://account.documents.azure.com:443"
            assert credential is globals_credential
            self.entered = False

        async def __aenter__(self) -> FakeClient:
            self.entered = True
            return self

        def get_database_client(self, name: str) -> FakeDatabase:
            assert self.entered
            assert name == "database"
            return FakeDatabase()

    globals_credential = credential
    clients: list[FakeClient] = []

    def client_factory(endpoint: str, *, credential: object) -> FakeClient:
        client = FakeClient(endpoint, credential=credential)
        clients.append(client)
        return client

    monkeypatch.setattr("resolver.repository.DefaultAzureCredential", lambda: credential)
    monkeypatch.setattr("resolver.repository.CosmosClient", client_factory)

    repository = await create_cosmos_redirect_event_repository(
        "https://account.documents.azure.com:443",
        "database",
        "redirect_events",
    )
    assert clients[0].entered
    await repository.aclose()
    assert clients[0].closed
    assert credential.closed


@pytest.mark.asyncio
async def test_cosmos_redirect_event_contains_only_owned_data() -> None:
    container = FakeContainer()
    repository = CosmosRedirectEventRepository(container)
    event = RedirectEvent(
        code="known",
        destination_url="https://example.com/must-not-persist",
        correlation_id="event-correlation",
        occurred_at=datetime(2026, 8, 14, 1, 2, 3, tzinfo=UTC),
    )

    await repository.record(event)

    [document] = container.documents
    assert set(document) == {"id", "code", "correlation_id", "created_at"}
    assert document["code"] == "known"
    assert document["correlation_id"] == "event-correlation"
    assert document["created_at"] == "2026-08-14T01:02:03+00:00"
    assert isinstance(document["id"], str)
    assert event.destination_url not in str(document)


def test_cosmos_persistence_failure_keeps_fail_closed_semantics() -> None:
    container = FakeContainer()
    container.create_error = RuntimeError("sensitive Cosmos failure")
    repository = CosmosRedirectEventRepository(container)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": "known", "url": "https://example.com"},
            headers={"X-Correlation-ID": request.headers["X-Correlation-ID"]},
        )

    app = create_app(
        Settings("http://shortener.test", 0.5),
        event_repository_factory=lambda: repository,
        transport=httpx.MockTransport(handler),
    )
    with TestClient(app) as client:
        response = client.get(
            "/known",
            headers={"X-Correlation-ID": "cosmos-event-failure"},
            follow_redirects=False,
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "redirect event could not be recorded"}
    assert "sensitive" not in response.text
    assert "Location" not in response.headers


def test_cosmos_backend_is_selected_and_lifecycle_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = FakeContainer()
    cosmos_client = FakeCloseable()
    credential = FakeCloseable()
    repository = CosmosRedirectEventRepository(
        container,
        client=cosmos_client,
        credential=credential,
    )
    calls: list[tuple[str, str, str]] = []

    async def fake_factory(
        endpoint: str, database: str, container_name: str
    ) -> CosmosRedirectEventRepository:
        calls.append((endpoint, database, container_name))
        return repository

    monkeypatch.setattr("resolver.main.create_cosmos_redirect_event_repository", fake_factory)
    settings = Settings(
        "http://shortener",
        0.5,
        repository_backend="cosmos",
        cosmos_endpoint="https://account.documents.azure.com:443",
        cosmos_database_name="database",
        cosmos_redirect_events_container="redirect_events",
    )
    app = create_app(settings, transport=httpx.MockTransport(lambda _request: None))

    with TestClient(app) as test_client:
        assert test_client.get("/readyz").status_code == 200

    assert calls == [("https://account.documents.azure.com:443", "database", "redirect_events")]
    assert cosmos_client.closed
    assert credential.closed


def test_resolver_cosmos_adapter_has_no_mapping_read_path() -> None:
    repository = CosmosRedirectEventRepository(FakeContainer())
    assert not hasattr(repository, "get")
    assert not hasattr(repository, "read_mapping")
