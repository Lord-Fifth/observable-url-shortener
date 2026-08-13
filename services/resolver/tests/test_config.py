from __future__ import annotations

import pytest
from resolver.config import Settings


def test_settings_are_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHORTENER_BASE_URL", "https://shortener.example/")
    monkeypatch.setenv("SHORTENER_TIMEOUT_SECONDS", "1.25")

    settings = Settings.from_env()

    assert settings == Settings(
        shortener_base_url="https://shortener.example",
        shortener_timeout_seconds=1.25,
    )


@pytest.mark.parametrize(
    "invalid_base_url",
    [
        "ftp://shortener.example",
        "http://localhost:notaport",
        "http://user:secret@shortener.example",
        "http://shortener.example/path",
        "http://shortener.example?tenant=one",
        "http://shortener.example?",
        "http://shortener.example#fragment",
        "http://shortener.example#",
        "http://%zz",
        "http:shortener.example",
    ],
)
def test_invalid_shortener_origin_is_rejected(
    monkeypatch: pytest.MonkeyPatch, invalid_base_url: str
) -> None:
    monkeypatch.setenv("SHORTENER_BASE_URL", invalid_base_url)
    with pytest.raises(RuntimeError):
        Settings.from_env()


@pytest.mark.parametrize("invalid_timeout", ["0", "-1", "nan", "inf", "not-a-number"])
def test_invalid_timeout_is_rejected(monkeypatch: pytest.MonkeyPatch, invalid_timeout: str) -> None:
    monkeypatch.setenv("SHORTENER_TIMEOUT_SECONDS", invalid_timeout)
    with pytest.raises(RuntimeError):
        Settings.from_env()
