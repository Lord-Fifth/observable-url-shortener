from __future__ import annotations

import asyncio
from collections.abc import Iterable

import pytest
from shortener.repository import InMemoryUrlRepository, UrlMapping
from shortener.service import CodeAllocationExhausted, ShortenerService


class SequenceGenerator:
    def __init__(self, values: Iterable[str]) -> None:
        self._values = iter(values)
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return next(self._values)


@pytest.mark.asyncio
async def test_collision_retries_and_succeeds_without_overwrite() -> None:
    repository = InMemoryUrlRepository()
    original = UrlMapping(code="collision", url="https://original.example")
    assert await repository.insert_if_absent(original)
    generator = SequenceGenerator(["collision", "available"])
    service = ShortenerService(repository, generator, max_attempts=3)

    created = await service.create_mapping("https://new.example")

    assert created == UrlMapping(code="available", url="https://new.example")
    assert generator.calls == 2
    assert await repository.get("collision") == original


@pytest.mark.asyncio
async def test_collision_exhaustion_is_bounded() -> None:
    repository = InMemoryUrlRepository()
    for code in ("one", "two", "three"):
        assert await repository.insert_if_absent(
            UrlMapping(code=code, url=f"https://{code}.example")
        )
    generator = SequenceGenerator(["one", "two", "three"])
    service = ShortenerService(repository, generator, max_attempts=3)

    with pytest.raises(CodeAllocationExhausted):
        await service.create_mapping("https://new.example")

    assert generator.calls == 3


@pytest.mark.asyncio
async def test_collision_exhaustion_maps_to_clean_503() -> None:
    repository = InMemoryUrlRepository()
    assert await repository.insert_if_absent(
        UrlMapping(code="fixed", url="https://original.example")
    )
    generator = SequenceGenerator(["fixed"])

    from fastapi.testclient import TestClient
    from shortener.config import Settings
    from shortener.main import create_app

    app = create_app(
        settings=Settings("http://resolver.test", code_length=5, max_code_attempts=1),
        repository_factory=lambda: repository,
        code_generator=generator,
    )
    with TestClient(app) as client:
        response = client.post("/v1/urls", json={"url": "https://new.example"})

    assert response.status_code == 503
    assert response.json() == {"detail": "unable to allocate a short code"}


@pytest.mark.asyncio
async def test_insert_if_absent_is_atomic_under_concurrency() -> None:
    repository = InMemoryUrlRepository()
    first = UrlMapping(code="shared", url="https://first.example")
    second = UrlMapping(code="shared", url="https://second.example")

    results = await asyncio.gather(
        repository.insert_if_absent(first), repository.insert_if_absent(second)
    )

    assert sorted(results) == [False, True]
    assert await repository.get("shared") in {first, second}
