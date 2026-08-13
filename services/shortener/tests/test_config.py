from __future__ import annotations

import pytest
from shortener.config import Settings


def test_settings_are_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESOLVER_BASE_URL", "https://resolver.example/")
    monkeypatch.setenv("SHORT_CODE_LENGTH", "10")
    monkeypatch.setenv("SHORT_CODE_MAX_ATTEMPTS", "7")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "shortener-test")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector.test:4318/")
    monkeypatch.setenv("OTEL_EXPORT_TIMEOUT_SECONDS", "1.5")
    monkeypatch.setenv("OTEL_METRIC_EXPORT_INTERVAL_SECONDS", "3")
    monkeypatch.setenv("REPOSITORY_BACKEND", "cosmos")
    monkeypatch.setenv("COSMOS_ENDPOINT", "https://account.documents.azure.com:443/")
    monkeypatch.setenv("COSMOS_DATABASE_NAME", "assessment")
    monkeypatch.setenv("COSMOS_MAPPINGS_CONTAINER", "mappings")

    settings = Settings.from_env()

    assert settings == Settings(
        resolver_base_url="https://resolver.example",
        code_length=10,
        max_code_attempts=7,
        otel_service_name="shortener-test",
        otel_exporter_otlp_endpoint="http://collector.test:4318",
        otel_export_timeout_seconds=1.5,
        otel_metric_export_interval_seconds=3.0,
        repository_backend="cosmos",
        cosmos_endpoint="https://account.documents.azure.com:443",
        cosmos_database_name="assessment",
        cosmos_mappings_container="mappings",
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


def test_memory_backend_is_default_and_requires_no_cosmos_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REPOSITORY_BACKEND", raising=False)
    monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)
    settings = Settings.from_env()
    assert settings.repository_backend == "memory"
    assert settings.cosmos_endpoint is None


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("REPOSITORY_BACKEND", "postgres"),
        ("COSMOS_ENDPOINT", "http://account.documents.azure.com"),
        ("COSMOS_DATABASE_NAME", "bad/name"),
        ("COSMOS_MAPPINGS_CONTAINER", "bad name"),
    ],
)
def test_invalid_cosmos_configuration_is_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv("REPOSITORY_BACKEND", "cosmos")
    monkeypatch.setenv("COSMOS_ENDPOINT", "https://account.documents.azure.com:443")
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError):
        Settings.from_env()


def test_cosmos_backend_requires_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPOSITORY_BACKEND", "cosmos")
    monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)
    with pytest.raises(RuntimeError, match="COSMOS_ENDPOINT"):
        Settings.from_env()
