"""HTTP adapter for the shortener's internal mapping contract."""

from __future__ import annotations

from urllib.parse import quote

import httpx
from pydantic import ValidationError

from resolver.correlation import CORRELATION_HEADER
from resolver.models import UpstreamUrlMapping


class MappingNotFound(Exception):
    """The shortener has no mapping for the requested code."""


class UpstreamUnavailable(Exception):
    """The shortener failed or violated its response contract."""


class ShortenerClient:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http_client = http_client

    async def get_destination(self, code: str, correlation_id: str) -> str:
        path_code = quote(code, safe="")
        try:
            response = await self._http_client.get(
                f"/internal/v1/urls/{path_code}",
                headers={CORRELATION_HEADER: correlation_id},
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise UpstreamUnavailable from exc

        if response.headers.get(CORRELATION_HEADER) != correlation_id:
            raise UpstreamUnavailable
        if response.status_code == 404:
            raise MappingNotFound
        if response.status_code != 200:
            raise UpstreamUnavailable

        try:
            mapping = UpstreamUrlMapping.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise UpstreamUnavailable from exc
        if mapping.code != code:
            raise UpstreamUnavailable
        return mapping.url
