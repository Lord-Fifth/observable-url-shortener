"""Reject Terraform plans that violate the documented cost/scope guardrails."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ALLOWED_TYPES = {
    "random_string",
    "azurerm_resource_group",
    "azurerm_cosmosdb_account",
    "azurerm_cosmosdb_sql_database",
    "azurerm_cosmosdb_sql_container",
    "azurerm_user_assigned_identity",
    "azurerm_cosmosdb_sql_role_assignment",
    "azurerm_container_app_environment",
    "azurerm_container_app",
    "azurerm_log_analytics_workspace",
    "azurerm_application_insights",
    "azurerm_application_insights_workbook",
    "azurerm_monitor_scheduled_query_rules_alert_v2",
    "azurerm_role_assignment",
}


def all_resources(module: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield from module.get("resources", [])
    for child in module.get("child_modules", []):
        yield from all_resources(child)


def one(resources: list[dict[str, Any]], resource_type: str) -> dict[str, Any]:
    matches = [resource for resource in resources if resource["type"] == resource_type]
    assert len(matches) == 1, (resource_type, len(matches))
    return matches[0]["values"]


def change_for(plan: dict[str, Any], address: str) -> dict[str, Any]:
    matches = [
        change for change in plan.get("resource_changes", []) if change["address"] == address
    ]
    assert len(matches) == 1, (address, len(matches))
    return matches[0]["change"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("--infra-directory", type=Path, required=True)
    args = parser.parse_args()
    completed = subprocess.run(  # noqa: S603 - fixed Terraform executable, explicit plan path
        ["terraform", "show", "-json", str(args.plan.resolve())],
        cwd=args.infra_directory,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    plan = json.loads(completed.stdout)
    destructive = [
        change["address"]
        for change in plan.get("resource_changes", [])
        if "delete" in change["change"]["actions"]
    ]
    assert not destructive, f"destructive resource changes are prohibited: {destructive}"
    resources = list(all_resources(plan["planned_values"]["root_module"]))

    unexpected = sorted({resource["type"] for resource in resources} - ALLOWED_TYPES)
    assert not unexpected, f"unexpected resource types: {unexpected}"
    assert len(resources) == 19, f"expected 19 resources, got {len(resources)}"

    for resource in resources:
        location = resource["values"].get("location")
        if location is not None:
            assert location.lower().replace(" ", "") == "australiaeast", (
                resource["address"],
                location,
            )

    cosmos = one(resources, "azurerm_cosmosdb_account")
    assert cosmos["free_tier_enabled"] is True
    assert cosmos["local_authentication_enabled"] is False
    assert cosmos["analytical_storage_enabled"] is False
    assert cosmos["multiple_write_locations_enabled"] is False
    assert cosmos["capacity"][0]["total_throughput_limit"] == 1000
    assert all(
        capability.get("name") != "EnableServerless"
        for capability in cosmos.get("capabilities", [])
    )
    assert len(cosmos["geo_location"]) == 1

    database = one(resources, "azurerm_cosmosdb_sql_database")
    assert database["throughput"] == 1000
    containers = [
        resource["values"]
        for resource in resources
        if resource["type"] == "azurerm_cosmosdb_sql_container"
    ]
    assert len(containers) == 2
    assert {container["name"] for container in containers} == {
        "url_mappings",
        "redirect_events",
    }
    assert all(container.get("throughput") in {None, 0} for container in containers)
    assert all(container["partition_key_paths"] == ["/code"] for container in containers)

    apps = [
        resource["values"] for resource in resources if resource["type"] == "azurerm_container_app"
    ]
    assert len(apps) == 2
    for app in apps:
        template = app["template"][0]
        assert template["min_replicas"] == 0
        assert template["max_replicas"] <= 2
        ingress = app["ingress"][0]
        assert ingress["external_enabled"] is True
        assert ingress["allow_insecure_connections"] is False
        assert ingress["target_port"] == 8080
        env_names = {item["name"] for item in template["container"][0]["env"]}
        assert "AZURE_MONITOR_ENABLED" in env_names
        assert "APPLICATIONINSIGHTS_CONNECTION_STRING" in env_names
        assert "APPLICATIONINSIGHTS_STATSBEAT_DISABLED_ALL" in env_names
        assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in env_names
        assert not any(
            "SECRET" in name or "PASSWORD" in name or "KEY" in name for name in env_names
        )

    container_environment = one(resources, "azurerm_container_app_environment")
    assert container_environment["logs_destination"] == "log-analytics"
    environment_change = change_for(plan, "azurerm_container_app_environment.application")
    assert container_environment.get("log_analytics_workspace_id") is not None or (
        environment_change.get("after_unknown", {}).get("log_analytics_workspace_id") is True
    )

    assignments = [
        resource["values"]
        for resource in resources
        if resource["type"] == "azurerm_cosmosdb_sql_role_assignment"
    ]
    assert len(assignments) == 2
    for assignment in assignments:
        if scope := assignment.get("scope"):
            assert scope != "/"
            assert "/colls/" in scope

    workspace = one(resources, "azurerm_log_analytics_workspace")
    assert workspace["sku"] == "PerGB2018"
    assert workspace["retention_in_days"] == 30
    assert workspace["daily_quota_gb"] == 1

    application_insights = one(resources, "azurerm_application_insights")
    assert application_insights["application_type"] == "web"
    assert application_insights["sampling_percentage"] == 100
    assert application_insights["daily_data_cap_in_gb"] == 1
    assert application_insights["local_authentication_enabled"] is False
    if application_insights.get("workspace_id") is not None:
        assert application_insights["workspace_id"] == workspace["id"]
    else:
        insights_change = change_for(plan, "azurerm_application_insights.observability")
        assert insights_change.get("after_unknown", {}).get("workspace_id") is True

    telemetry_assignments = [
        resource["values"]
        for resource in resources
        if resource["type"] == "azurerm_role_assignment"
    ]
    assert len(telemetry_assignments) == 2
    identities = {
        resource["values"]["principal_id"]
        for resource in resources
        if resource["type"] == "azurerm_user_assigned_identity"
    }
    assert {assignment["principal_id"] for assignment in telemetry_assignments} == identities
    assert all(
        assignment["role_definition_name"] == "Monitoring Metrics Publisher"
        for assignment in telemetry_assignments
    )
    assert all(
        not assignment.get("scope") or assignment["scope"] == application_insights["id"]
        for assignment in telemetry_assignments
    )

    workbook = one(resources, "azurerm_application_insights_workbook")
    assert workbook["display_name"] == "Observable URL Shortener - Production Observability"
    if workbook.get("data_json") is not None:
        assert all(
            metric in workbook["data_json"]
            for metric in {
                "url_shortener.http.server.requests",
                "url_shortener.http.server.errors",
                "url_shortener.http.server.request.duration",
            }
        )
    else:
        workbook_change = change_for(plan, "azurerm_application_insights_workbook.production")
        assert workbook_change.get("after_unknown", {}).get("data_json") is True

    alert = one(resources, "azurerm_monitor_scheduled_query_rules_alert_v2")
    assert alert["enabled"] is True
    assert alert["evaluation_frequency"] == "PT5M"
    assert alert["window_duration"] == "PT5M"
    assert "url_shortener.http.server.errors" in alert["criteria"][0]["query"]
    assert alert["criteria"][0]["operator"] == "GreaterThan"
    assert alert["criteria"][0]["threshold"] == 0

    print("PASS: Terraform plan contains only the 19 expected cost-bounded Azure resources")


if __name__ == "__main__":
    main()
