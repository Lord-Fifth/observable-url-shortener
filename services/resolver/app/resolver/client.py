"""HTTP adapter for the shortener's internal mapping contract."""

from __future__ import annotations

import logging
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from resolver.correlation import CORRELATION_HEADER
from resolver.logging import log_event
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
            log_event(
                logging.ERROR,
                "shortener_upstream_failed",
                "Shortener upstream request failed",
                correlation_id=correlation_id,
                upstream_service="shortener",
                operation="lookup_mapping",
                exception_type=type(exc).__name__,
            )
            raise UpstreamUnavailable from exc

        if response.headers.get(CORRELATION_HEADER) != correlation_id:
            log_event(
                logging.ERROR,
                "shortener_upstream_failed",
                "Shortener upstream correlation contract failed",
                correlation_id=correlation_id,
                upstream_service="shortener",
                operation="lookup_mapping",
                status_code=response.status_code,
                failure_reason="correlation_mismatch",
            )
            raise UpstreamUnavailable
        if response.status_code == 404:
            log_event(
                logging.INFO,
                "shortener_upstream_completed",
                "Shortener upstream request completed",
                correlation_id=correlation_id,
                upstream_service="shortener",
                operation="lookup_mapping",
                status_code=404,
            )
            raise MappingNotFound
        if response.status_code != 200:
            log_event(
                logging.ERROR,
                "shortener_upstream_failed",
                "Shortener upstream returned an unsuccessful response",
                correlation_id=correlation_id,
                upstream_service="shortener",
                operation="lookup_mapping",
                status_code=response.status_code,
            )
            raise UpstreamUnavailable

        try:
            mapping = UpstreamUrlMapping.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            log_event(
                logging.ERROR,
                "shortener_upstream_failed",
                "Shortener upstream response violated its contract",
                correlation_id=correlation_id,
                upstream_service="shortener",
                operation="lookup_mapping",
                status_code=response.status_code,
                exception_type=type(exc).__name__,
            )
            raise UpstreamUnavailable from exc
        if mapping.code != code:
            log_event(
                logging.ERROR,
                "shortener_upstream_failed",
                "Shortener upstream response code did not match request",
                correlation_id=correlation_id,
                upstream_service="shortener",
                operation="lookup_mapping",
                status_code=response.status_code,
                failure_reason="code_mismatch",
            )
            raise UpstreamUnavailable
        log_event(
            logging.INFO,
            "shortener_upstream_completed",
            "Shortener upstream request completed",
            correlation_id=correlation_id,
            upstream_service="shortener",
            operation="lookup_mapping",
            status_code=response.status_code,
        )
        return mapping.url
