from __future__ import annotations

import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SERVICE_NAMES = ("shortener", "resolver")


def runtime_manifest(service_name: str) -> str:
    return (REPOSITORY_ROOT / "services" / service_name / "requirements.txt").read_text()


def test_async_azure_transport_is_pinned_in_both_runtime_manifests() -> None:
    versions: set[str] = set()
    for service_name in SERVICE_NAMES:
        matches = re.findall(
            r"(?m)^aiohttp==([0-9]+\.[0-9]+\.[0-9]+)$", runtime_manifest(service_name)
        )
        assert len(matches) == 1, service_name
        versions.add(matches[0])

    assert len(versions) == 1


def test_explicit_azure_monitor_exporter_is_pinned_compatibly_in_both_images() -> None:
    manifests = [runtime_manifest(service_name) for service_name in SERVICE_NAMES]
    exporter_pins: set[str] = set()
    sdk_pins: set[str] = set()
    for manifest in manifests:
        assert "azure-monitor-opentelemetry-exporter==1.0.0b56" in manifest
        assert "opentelemetry-sdk==1.43.0" in manifest
        assert "azure-monitor-opentelemetry==" not in manifest
        exporter_pins.update(
            re.findall(r"(?m)^azure-monitor-opentelemetry-exporter==([^\s]+)$", manifest)
        )
        sdk_pins.update(re.findall(r"(?m)^opentelemetry-sdk==([^\s]+)$", manifest))

    assert exporter_pins == {"1.0.0b56"}
    assert sdk_pins == {"1.43.0"}


def test_production_images_install_the_runtime_manifests() -> None:
    for service_name in SERVICE_NAMES:
        dockerfile = (REPOSITORY_ROOT / "services" / service_name / "Dockerfile").read_text()
        assert "COPY requirements.txt ./requirements.txt" in dockerfile
        assert "-r requirements.txt" in dockerfile


def test_each_container_app_explicitly_selects_its_own_managed_identity() -> None:
    container_apps = (REPOSITORY_ROOT / "infra" / "container_apps.tf").read_text()

    for service_name in SERVICE_NAMES:
        identity = f"azurerm_user_assigned_identity.{service_name}"
        assert f"identity_ids = [{identity}.id]" in container_apps
        assert f"value = {identity}.client_id" in container_apps

    assert container_apps.count('name  = "AZURE_CLIENT_ID"') == len(SERVICE_NAMES)
    assert container_apps.count('name  = "AZURE_MONITOR_ENABLED"') == len(SERVICE_NAMES)
    assert container_apps.count('name  = "APPLICATIONINSIGHTS_CONNECTION_STRING"') == len(
        SERVICE_NAMES
    )
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in container_apps
