from __future__ import annotations

from typing import Any

import pytest
from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError
from fastapi.testclient import TestClient
from shortener.config import Settings
from shortener.main import create_app
from shortener.repository import (
    CosmosUrlRepository,
    UrlMapping,
    create_cosmos_url_repository,
)


class FakeContainer:
    def __init__(self) -> None:
        self.documents: dict[str, dict[str, Any]] = {}
        self.create_error: Exception | None = None
        self.read_error: Exception | None = None

    async def create_item(self, body: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        if self.create_error is not None:
            raise self.create_error
        if body["id"] in self.documents:
            raise CosmosResourceExistsError(message="duplicate")
        self.documents[body["id"]] = dict(body)
        return body

    async def read_item(self, item: str, partition_key: str, **_kwargs: Any) -> dict[str, Any]:
        assert partition_key == item
        if self.read_error is not None:
            raise self.read_error
        try:
            return self.documents[item]
        except KeyError as exc:
            raise CosmosResourceNotFoundError(message="missing") from exc


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
            assert name == "url_mappings"
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

    monkeypatch.setattr("shortener.repository.DefaultAzureCredential", lambda: credential)
    monkeypatch.setattr("shortener.repository.CosmosClient", client_factory)

    repository = await create_cosmos_url_repository(
        "https://account.documents.azure.com:443",
        "database",
        "url_mappings",
    )
    assert clients[0].entered
    await repository.aclose()
    assert clients[0].closed
    assert credential.closed


@pytest.mark.asyncio
async def test_cosmos_mapping_create_and_lookup_preserve_url() -> None:
    container = FakeContainer()
    repository = CosmosUrlRepository(container)
    mapping = UrlMapping("atomic123", "https://example.com/path?kept=yes")

    assert await repository.insert_if_absent(mapping) is True
    assert container.documents["atomic123"]["id"] == "atomic123"
    assert container.documents["atomic123"]["code"] == "atomic123"
    assert container.documents["atomic123"]["url"] == mapping.url
    assert container.documents["atomic123"]["created_at"].endswith("+00:00")
    assert await repository.get("atomic123") == mapping


@pytest.mark.asyncio
async def test_cosmos_duplicate_create_is_atomic_collision() -> None:
    container = FakeContainer()
    repository = CosmosUrlRepository(container)
    mapping = UrlMapping("samecode", "https://example.com")

    assert await repository.insert_if_absent(mapping) is True
    assert await repository.insert_if_absent(mapping) is False


@pytest.mark.asyncio
async def test_cosmos_not_found_maps_to_none() -> None:
    repository = CosmosUrlRepository(FakeContainer())
    assert await repository.get("missing") is None


@pytest.mark.asyncio
async def test_cosmos_unexpected_failure_propagates_to_safe_http_boundary() -> None:
    container = FakeContainer()
    container.create_error = RuntimeError("sensitive Cosmos failure")
    repository = CosmosUrlRepository(container)
    app = create_app(
        Settings("http://resolver.test", 8, 5),
        repository_factory=lambda: repository,
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/v1/urls",
            json={"url": "https://example.com"},
            headers={"X-Correlation-ID": "cosmos-failure"},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert "sensitive" not in response.text
    assert response.headers["X-Correlation-ID"] == "cosmos-failure"


def test_cosmos_backend_is_selected_and_lifecycle_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeCloseable()
    credential = FakeCloseable()
    repository = CosmosUrlRepository(FakeContainer(), client=client, credential=credential)
    calls: list[tuple[str, str, str]] = []

    async def fake_factory(endpoint: str, database: str, container: str) -> CosmosUrlRepository:
        calls.append((endpoint, database, container))
        return repository

    monkeypatch.setattr("shortener.main.create_cosmos_url_repository", fake_factory)
    settings = Settings(
        "https://resolver.test",
        8,
        5,
        repository_backend="cosmos",
        cosmos_endpoint="https://account.documents.azure.com:443",
        cosmos_database_name="database",
        cosmos_mappings_container="url_mappings",
    )
    app = create_app(settings)

    with TestClient(app) as test_client:
        assert test_client.get("/readyz").status_code == 200

    assert calls == [("https://account.documents.azure.com:443", "database", "url_mappings")]
    assert client.closed
    assert credential.closed
