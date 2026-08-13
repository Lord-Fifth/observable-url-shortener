"""Mapping persistence boundary and its Phase 0-1 in-memory adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from azure.cosmos.aio import CosmosClient
from azure.cosmos.exceptions import CosmosResourceExistsError, CosmosResourceNotFoundError
from azure.identity.aio import DefaultAzureCredential


@dataclass(frozen=True, slots=True)
class UrlMapping:
    code: str
    url: str


class UrlRepository(Protocol):
    async def insert_if_absent(self, mapping: UrlMapping) -> bool:
        """Atomically insert a mapping, returning false when its code exists."""
        ...

    async def get(self, code: str) -> UrlMapping | None: ...

    async def aclose(self) -> None: ...


class CosmosContainer(Protocol):
    """Small async Cosmos SDK boundary used by the production adapter and fakes."""

    async def create_item(self, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]: ...

    async def read_item(self, item: str, partition_key: str, **kwargs: Any) -> dict[str, Any]: ...


class AsyncCloseable(Protocol):
    async def close(self) -> None: ...


class InMemoryUrlRepository:
    """Process-local repository with atomic collision detection."""

    def __init__(self) -> None:
        self._mappings: dict[str, UrlMapping] = {}
        self._lock = asyncio.Lock()
        self.closed = False

    def _ensure_open(self) -> None:
        if self.closed:
            raise RuntimeError("URL repository is closed")

    async def insert_if_absent(self, mapping: UrlMapping) -> bool:
        self._ensure_open()
        async with self._lock:
            if mapping.code in self._mappings:
                return False
            self._mappings[mapping.code] = mapping
            return True

    async def get(self, code: str) -> UrlMapping | None:
        self._ensure_open()
        async with self._lock:
            return self._mappings.get(code)

    async def aclose(self) -> None:
        self.closed = True


class CosmosUrlRepository:
    """Cosmos mapping adapter using create-only writes for atomic collision detection."""

    def __init__(
        self,
        container: CosmosContainer,
        *,
        client: AsyncCloseable | None = None,
        credential: AsyncCloseable | None = None,
    ) -> None:
        self._container = container
        self._client = client
        self._credential = credential
        self._closed = False

    async def insert_if_absent(self, mapping: UrlMapping) -> bool:
        if self._closed:
            raise RuntimeError("URL repository is closed")
        document = {
            "id": mapping.code,
            "code": mapping.code,
            "url": mapping.url,
            "created_at": datetime.now(UTC).isoformat(),
        }
        try:
            await self._container.create_item(body=document)
        except CosmosResourceExistsError:
            return False
        return True

    async def get(self, code: str) -> UrlMapping | None:
        if self._closed:
            raise RuntimeError("URL repository is closed")
        try:
            document = await self._container.read_item(item=code, partition_key=code)
        except CosmosResourceNotFoundError:
            return None
        stored_code = document.get("code")
        stored_url = document.get("url")
        if stored_code != code or not isinstance(stored_url, str):
            raise RuntimeError("Cosmos mapping document violates the repository contract")
        return UrlMapping(code=stored_code, url=stored_url)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._client is not None:
                await self._client.close()
        finally:
            if self._credential is not None:
                await self._credential.close()


async def create_cosmos_url_repository(
    endpoint: str,
    database_name: str,
    container_name: str,
) -> CosmosUrlRepository:
    """Create one lifespan-owned Cosmos client using secretless Azure identity."""

    credential = DefaultAzureCredential()
    client = CosmosClient(endpoint, credential=credential)
    try:
        await client.__aenter__()
    except Exception:
        try:
            await client.close()
        finally:
            await credential.close()
        raise
    container = client.get_database_client(database_name).get_container_client(container_name)
    return CosmosUrlRepository(container, client=client, credential=credential)
