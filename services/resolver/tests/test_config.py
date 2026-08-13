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
    monkeypatch.setenv("REPOSITORY_BACKEND", "cosmos")
    monkeypatch.setenv("COSMOS_ENDPOINT", "https://account.documents.azure.com:443/")
    monkeypatch.setenv("COSMOS_DATABASE_NAME", "assessment")
    monkeypatch.setenv("COSMOS_REDIRECT_EVENTS_CONTAINER", "events")

    settings = Settings.from_env()

    assert settings == Settings(
        shortener_base_url="https://shortener.example",
        shortener_timeout_seconds=1.25,
        otel_service_name="resolver-test",
        otel_exporter_otlp_endpoint="http://collector.test:4318",
        otel_export_timeout_seconds=1.5,
        otel_metric_export_interval_seconds=3.0,
        repository_backend="cosmos",
        cosmos_endpoint="https://account.documents.azure.com:443",
        cosmos_database_name="assessment",
        cosmos_redirect_events_container="events",
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
        ("COSMOS_REDIRECT_EVENTS_CONTAINER", "bad name"),
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


def test_azure_monitor_configuration_uses_explicit_managed_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection_string = (
        "InstrumentationKey=00000000-0000-0000-0000-000000000000;"
        "IngestionEndpoint=https://australiaeast-0.in.applicationinsights.azure.com/"
    )
    monkeypatch.setenv("AZURE_MONITOR_ENABLED", "true")
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", connection_string)
    monkeypatch.setenv("AZURE_CLIENT_ID", "22222222-2222-2222-2222-222222222222")

    settings = Settings.from_env()

    assert settings.azure_monitor_enabled is True
    assert settings.application_insights_connection_string == connection_string
    assert settings.azure_client_id == "22222222-2222-2222-2222-222222222222"


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"AZURE_MONITOR_ENABLED": "maybe"}, "must be true or false"),
        ({"AZURE_MONITOR_ENABLED": "true"}, "requires"),
        (
            {
                "APPLICATIONINSIGHTS_CONNECTION_STRING": (
                    "InstrumentationKey=00000000-0000-0000-0000-000000000000;"
                    "IngestionEndpoint=https://example.test/"
                )
            },
            "requires AZURE_MONITOR_ENABLED",
        ),
        (
            {
                "AZURE_MONITOR_ENABLED": "true",
                "APPLICATIONINSIGHTS_CONNECTION_STRING": (
                    "InstrumentationKey=00000000-0000-0000-0000-000000000000;"
                    "IngestionEndpoint=https://example.test/"
                ),
                "AZURE_CLIENT_ID": "not-a-uuid",
            },
            "must be a UUID",
        ),
        (
            {
                "AZURE_MONITOR_ENABLED": "true",
                "APPLICATIONINSIGHTS_CONNECTION_STRING": (
                    "InstrumentationKey=00000000-0000-0000-0000-000000000000;"
                    "IngestionEndpoint=https://example.test/"
                ),
                "AZURE_CLIENT_ID": "22222222-2222-2222-2222-222222222222",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector.test:4318",
            },
            "mutually exclusive",
        ),
    ],
)
def test_invalid_azure_monitor_configuration_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    environment: dict[str, str],
    message: str,
) -> None:
    for name in (
        "AZURE_MONITOR_ENABLED",
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
        "AZURE_CLIENT_ID",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    with pytest.raises(RuntimeError, match=message):
        Settings.from_env()
