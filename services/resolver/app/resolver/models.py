"""Schemas consumed from the shortener's internal HTTP contract."""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, BaseModel, TypeAdapter, ValidationError, field_validator

_HTTP_URL_ADAPTER = TypeAdapter(AnyHttpUrl)
_INVALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


def validate_redirect_url(value: str) -> str:
    if not value or value != value.strip():
        raise ValueError("redirect URL is empty or surrounded by whitespace")
    if any(character.isspace() or unicodedata.category(character) == "Cc" for character in value):
        raise ValueError("redirect URL contains whitespace or control characters")
    if "\\" in value or not value.lower().startswith(("http://", "https://")):
        raise ValueError("redirect URL must contain an explicit HTTP(S) authority")
    if _INVALID_PERCENT_ESCAPE.search(value):
        raise ValueError("redirect URL contains invalid percent encoding")
    try:
        parsed = urlsplit(value)
        _ = parsed.port
        _HTTP_URL_ADAPTER.validate_python(value)
    except (ValidationError, ValueError) as exc:
        raise ValueError("redirect URL is malformed") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise ValueError("redirect URL must use HTTP or HTTPS and include a host")
    return value


class UpstreamUrlMapping(BaseModel):
    code: str
    url: str

    @field_validator("url")
    @classmethod
    def url_must_be_safe_for_redirect(cls, value: str) -> str:
        return validate_redirect_url(value)


class StatusResponse(BaseModel):
    status: str
