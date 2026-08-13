"""Environment-backed configuration for the resolver service."""

from __future__ import annotations

import math
import os
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

_HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


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


@dataclass(frozen=True, slots=True)
class Settings:
    """Configuration needed by one resolver process."""

    shortener_base_url: str
    shortener_timeout_seconds: float

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            shortener_base_url=_service_base_url("SHORTENER_BASE_URL", "http://localhost:8080"),
            shortener_timeout_seconds=_positive_float("SHORTENER_TIMEOUT_SECONDS", 2.0),
        )
