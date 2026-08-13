from __future__ import annotations

import pytest
from resolver.config import Settings


def test_settings_are_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHORTENER_BASE_URL", "https://shortener.example/")
    monkeypatch.setenv("SHORTENER_TIMEOUT_SECONDS", "1.25")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "resolver-test")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.test:4318/")
    monkeypatch.setenv("OTEL_EXPORT_TIMEOUT_SECONDS", "1.5")
    monkeypatch.setenv("OTEL_METRIC_EXPORT_INTERVAL_SECONDS", "3")

    settings = Settings.from_env()

    assert settings == Settings(
        shortener_base_url="https://shortener.example",
        shortener_timeout_seconds=1.25,
        otel_service_name="resolver-test",
        otel_exporter_otlp_endpoint="http://collector.test:4318",
        otel_export_timeout_seconds=1.5,
        otel_metric_export_interval_seconds=3.0,
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


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("OTEL_SERVICE_NAME", "not a service"),
        ("OTEL_EXPORTER_OTLP_ENDPOINT", "collector:4318"),
        ("OTEL_EXPORT_TIMEOUT_SECONDS", "0"),
        ("OTEL_METRIC_EXPORT_INTERVAL_SECONDS", "nan"),
    ],
)
def test_invalid_telemetry_setting_is_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError):
        Settings.from_env()
