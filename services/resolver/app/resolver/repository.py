"""Redirect-event persistence boundary and Phase 0-1 in-memory adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RedirectEvent:
    code: str
    destination_url: str
    correlation_id: str
    occurred_at: datetime


class RedirectEventRepository(Protocol):
    async def record(self, event: RedirectEvent) -> None: ...

    async def aclose(self) -> None: ...


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
