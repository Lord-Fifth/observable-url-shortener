"""Environment-backed configuration for the shortener service."""

from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, TypeAdapter, ValidationError

_HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)


def _positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


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


@dataclass(frozen=True, slots=True)
class Settings:
    """Configuration needed by one shortener process."""

    resolver_base_url: str
    code_length: int
    max_code_attempts: int

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            resolver_base_url=_service_base_url("RESOLVER_BASE_URL", "http://localhost:8081"),
            code_length=_positive_int("SHORT_CODE_LENGTH", 8),
            max_code_attempts=_positive_int("SHORT_CODE_MAX_ATTEMPTS", 5),
        )
