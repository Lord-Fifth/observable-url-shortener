from __future__ import annotations

import pytest
from shortener.config import Settings


def test_settings_are_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESOLVER_BASE_URL", "https://resolver.example/")
    monkeypatch.setenv("SHORT_CODE_LENGTH", "10")
    monkeypatch.setenv("SHORT_CODE_MAX_ATTEMPTS", "7")

    settings = Settings.from_env()

    assert settings == Settings(
        resolver_base_url="https://resolver.example",
        code_length=10,
        max_code_attempts=7,
    )


@pytest.mark.parametrize(
    "invalid_base_url",
    [
        "ftp://resolver.example",
        "http://localhost:notaport",
        "http://user:secret@resolver.example",
        "http://resolver.example/path",
        "http://resolver.example?tenant=one",
        "http://resolver.example?",
        "http://resolver.example#fragment",
        "http://resolver.example#",
        "http://%zz",
        "http:resolver.example",
    ],
)
def test_invalid_resolver_origin_is_rejected(
    monkeypatch: pytest.MonkeyPatch, invalid_base_url: str
) -> None:
    monkeypatch.setenv("RESOLVER_BASE_URL", invalid_base_url)
    with pytest.raises(RuntimeError):
        Settings.from_env()


@pytest.mark.parametrize(
    ("name", "value"),
    [("SHORT_CODE_LENGTH", "0"), ("SHORT_CODE_MAX_ATTEMPTS", "-1"), ("SHORT_CODE_LENGTH", "x")],
)
def test_invalid_positive_integer_setting_is_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError):
        Settings.from_env()
