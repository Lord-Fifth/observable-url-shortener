"""Environment-backed configuration for the resolver service."""

from __future__ import annotations

import math
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal, cast
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

_HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)
_SERVICE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_COSMOS_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,255}$")
RepositoryBackend = Literal["memory", "cosmos"]


def _service_base_url(name: str, default: str) -> str:
    value = os.getenv(name, default)
    if any(character.isspace() or unicodedata.category(character) == "Cc" for character in value):
        raise RuntimeError(f"{name} must not contain whitespace or control characters")
    if (
        "?" in value
        or "#" in value
        or "\\" in value
        or not value.lower().startswith(("http://", "https://"))
    ):
        raise RuntimeError(f"{name} must be an HTTP(S) origin")
    try:
        _HTTP_URL_ADAPTER.validate_python(value)
        parsed = urlsplit(value)
        _ = parsed.port
    except (ValidationError, ValueError) as exc:
        raise RuntimeError(f"{name} must be a valid HTTP(S) base URL") from exc
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.scheme.lower() not in {"http", "https"}
        or not parsed.netloc
        or not parsed.hostname
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise RuntimeError(f"{name} must be an HTTP(S) origin without credentials or a path")
    return value.rstrip("/")


def _positive_float(name: str, default: float) -> float:
    raw_value = os.getenv(name, str(default))
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number") from exc
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError(f"{name} must be a finite number greater than zero")
    return value


def _repository_backend() -> RepositoryBackend:
    value = os.getenv("REPOSITORY_BACKEND", "memory").lower()
    if value not in {"memory", "cosmos"}:
        raise RuntimeError("REPOSITORY_BACKEND must be memory or cosmos")
    return cast(RepositoryBackend, value)


def _cosmos_name(name: str, default: str) -> str:
    value = os.getenv(name, default)
    if _COSMOS_NAME_PATTERN.fullmatch(value) is None:
        raise RuntimeError(f"{name} must be a compact Cosmos resource name")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    """Configuration needed by one resolver process."""

    shortener_base_url: str
    shortener_timeout_seconds: float
    otel_service_name: str = "resolver"
    otel_exporter_otlp_endpoint: str | None = None
    otel_export_timeout_seconds: float = 2.0
    otel_metric_export_interval_seconds: float = 5.0
    repository_backend: RepositoryBackend = "memory"
    cosmos_endpoint: str | None = None
    cosmos_database_name: str = "url-shortener"
    cosmos_redirect_events_container: str = "redirect_events"

    @classmethod
    def from_env(cls) -> Settings:
        otel_service_name = os.getenv("OTEL_SERVICE_NAME", "resolver")
        if _SERVICE_NAME_PATTERN.fullmatch(otel_service_name) is None:
            raise RuntimeError("OTEL_SERVICE_NAME must be a compact service identifier")
        raw_otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
        repository_backend = _repository_backend()
        raw_cosmos_endpoint = os.getenv("COSMOS_ENDPOINT")
        if repository_backend == "cosmos" and raw_cosmos_endpoint is None:
            raise RuntimeError("COSMOS_ENDPOINT is required when REPOSITORY_BACKEND=cosmos")
        cosmos_endpoint = (
            _service_base_url("COSMOS_ENDPOINT", raw_cosmos_endpoint)
            if raw_cosmos_endpoint
            else None
        )
        if cosmos_endpoint is not None and not cosmos_endpoint.startswith("https://"):
            raise RuntimeError("COSMOS_ENDPOINT must use HTTPS")
        return cls(
            shortener_base_url=_service_base_url("SHORTENER_BASE_URL", "http://localhost:8080"),
            shortener_timeout_seconds=_positive_float("SHORTENER_TIMEOUT_SECONDS", 2.0),
            otel_service_name=otel_service_name,
            otel_exporter_otlp_endpoint=(
                _service_base_url("OTEL_EXPORTER_OTLP_ENDPOINT", raw_otlp_endpoint)
                if raw_otlp_endpoint
                else None
            ),
            otel_export_timeout_seconds=_positive_float("OTEL_EXPORT_TIMEOUT_SECONDS", 2.0),
            otel_metric_export_interval_seconds=_positive_float(
                "OTEL_METRIC_EXPORT_INTERVAL_SECONDS", 5.0
            ),
            repository_backend=repository_backend,
            cosmos_endpoint=cosmos_endpoint,
            cosmos_database_name=_cosmos_name("COSMOS_DATABASE_NAME", "url-shortener"),
            cosmos_redirect_events_container=_cosmos_name(
                "COSMOS_REDIRECT_EVENTS_CONTAINER", "redirect_events"
            ),
        )
