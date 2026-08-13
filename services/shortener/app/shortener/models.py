"""Public and internal HTTP schemas for URL mappings."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    TypeAdapter,
    ValidationError,
    field_validator,
)

_HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


def validate_http_url(value: str) -> str:
    """Validate without normalising the caller's redirect destination."""

    if not value or value != value.strip():
        raise ValueError("URL must not be empty or surrounded by whitespace")
    if any(character.isspace() or unicodedata.category(character) == "Cc" for character in value):
        raise ValueError("URL must not contain whitespace or control characters")
    if "\\" in value or not value.lower().startswith(("http://", "https://")):
        raise ValueError("URL must contain an explicit HTTP(S) authority")

    if _INVALID_PERCENT_ESCAPE.search(value):
        raise ValueError("URL contains invalid percent encoding")
    try:
        parsed = urlsplit(value)
        _ = parsed.port
        _HTTP_URL_ADAPTER.validate_python(value)
    except (ValidationError, ValueError) as exc:
        raise ValueError("URL is malformed") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise ValueError("URL must use HTTP or HTTPS and include a host")
    return value


class CreateUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str

    @field_validator("url")
    @classmethod
    def url_must_be_http_or_https(cls, value: str) -> str:
        return validate_http_url(value)


class CreateUrlResponse(BaseModel):
    code: str
    short_url: str


class UrlMappingResponse(BaseModel):
    code: str
    url: str


class StatusResponse(BaseModel):
    status: str
