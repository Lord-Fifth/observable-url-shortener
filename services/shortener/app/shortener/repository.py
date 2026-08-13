"""Mapping persistence boundary and its Phase 0-1 in-memory adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol


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
