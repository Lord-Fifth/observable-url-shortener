from __future__ import annotations

import httpx
import pytest
from resolver.config import Settings as ResolverSettings
from resolver.main import create_app as create_resolver_app
from resolver.repository import InMemoryRedirectEventRepository
from shortener.config import Settings as ShortenerSettings
from shortener.main import create_app as create_shortener_app
from shortener.repository import InMemoryUrlRepository


class CapturingAsgiTransport(httpx.AsyncBaseTransport):
    def __init__(self, app: object) -> None:
        self._transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return await self._transport.handle_async_request(request)

    async def aclose(self) -> None:
        await self._transport.aclose()


@pytest.mark.asyncio
async def test_create_then_resolve_across_real_asgi_http_boundary() -> None:
    mapping_repository = InMemoryUrlRepository()
    shortener_app = create_shortener_app(
        ShortenerSettings("http://resolver.test", code_length=8, max_code_attempts=3),
        repository_factory=lambda: mapping_repository,
        code_generator=lambda: "abc12345",
    )
    shortener_transport = CapturingAsgiTransport(shortener_app)
    event_repository = InMemoryRedirectEventRepository()
    resolver_app = create_resolver_app(
        ResolverSettings("http://shortener.test", shortener_timeout_seconds=1.0),
        event_repository_factory=lambda: event_repository,
        transport=shortener_transport,
    )

    async with (
        shortener_app.router.lifespan_context(shortener_app),
        resolver_app.router.lifespan_context(resolver_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=shortener_app),
            base_url="http://shortener.test",
        ) as shortener_client,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=resolver_app),
            base_url="http://resolver.test",
            follow_redirects=False,
        ) as resolver_client,
    ):
        created = await shortener_client.post(
            "/v1/urls",
            json={"url": "https://example.com/integration"},
            headers={"X-Correlation-ID": "create-integration"},
        )
        assert created.status_code == 201
        assert created.headers["X-Correlation-ID"] == "create-integration"
        assert created.json() == {
            "code": "abc12345",
            "short_url": "http://resolver.test/abc12345",
        }

        resolved = await resolver_client.get(
            "/abc12345",
            headers={"X-Correlation-ID": "resolve-integration"},
        )

    assert resolved.status_code == 302
    assert resolved.headers["Location"] == "https://example.com/integration"
    assert resolved.headers["X-Correlation-ID"] == "resolve-integration"
    assert len(shortener_transport.requests) == 1
    assert shortener_transport.requests[0].headers["X-Correlation-ID"] == "resolve-integration"
    assert len(event_repository.events) == 1
    assert event_repository.events[0].correlation_id == "resolve-integration"
