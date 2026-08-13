"""Short-code allocation use case."""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass
from typing import Protocol

from shortener.repository import UrlMapping, UrlRepository

BASE62_ALPHABET = string.ascii_letters + string.digits


class CodeGenerator(Protocol):
    def __call__(self) -> str: ...


@dataclass(frozen=True, slots=True)
class RandomCodeGenerator:
    length: int

    def __call__(self) -> str:
        return "".join(secrets.choice(BASE62_ALPHABET) for _ in range(self.length))


class CodeAllocationExhausted(Exception):
    """Raised when every bounded allocation attempt collides."""


class ShortenerService:
    def __init__(
        self,
        repository: UrlRepository,
        code_generator: CodeGenerator,
        max_attempts: int,
    ) -> None:
        self._repository = repository
        self._code_generator = code_generator
        self._max_attempts = max_attempts

    async def create_mapping(self, url: str) -> UrlMapping:
        for _ in range(self._max_attempts):
            mapping = UrlMapping(code=self._code_generator(), url=url)
            if await self._repository.insert_if_absent(mapping):
                return mapping
        raise CodeAllocationExhausted

    async def get_mapping(self, code: str) -> UrlMapping | None:
        return await self._repository.get(code)
