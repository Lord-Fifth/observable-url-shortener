"""Redirect-event persistence boundary and Phase 0-1 in-memory adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import uuid4

from azure.cosmos.aio import CosmosClient
from azure.identity.aio import DefaultAzureCredential


@dataclass(frozen=True, slots=True)
class RedirectEvent:
    code: str
    destination_url: str
    correlation_id: str
    occurred_at: datetime


class RedirectEventRepository(Protocol):
    async def record(self, event: RedirectEvent) -> None: ...

    async def aclose(self) -> None: ...


class CosmosContainer(Protocol):
    """Write-only Cosmos SDK boundary for resolver-owned redirect events."""

    async def create_item(self, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]: ...


class AsyncCloseable(Protocol):
    async def close(self) -> None: ...


class InMemoryRedirectEventRepository:
    """Process-local event adapter; only completed lookups are recorded."""

    def __init__(self) -> None:
        self._events: list[RedirectEvent] = []
        self._lock = asyncio.Lock()
        self.closed = False

    @property
    def events(self) -> tuple[RedirectEvent, ...]:
        return tuple(self._events)

    async def record(self, event: RedirectEvent) -> None:
        if self.closed:
            raise RuntimeError("redirect event repository is closed")
        async with self._lock:
            self._events.append(event)

    async def aclose(self) -> None:
        self.closed = True


class CosmosRedirectEventRepository:
    """Cosmos adapter that can only write resolver-owned redirect-event documents."""

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

    async def record(self, event: RedirectEvent) -> None:
        if self._closed:
            raise RuntimeError("redirect event repository is closed")
        await self._container.create_item(
            body={
                "id": str(uuid4()),
                "code": event.code,
                "correlation_id": event.correlation_id,
                "created_at": event.occurred_at.isoformat(),
            }
        )

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


async def create_cosmos_redirect_event_repository(
    endpoint: str,
    database_name: str,
    container_name: str,
) -> CosmosRedirectEventRepository:
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
    return CosmosRedirectEventRepository(container, client=client, credential=credential)
