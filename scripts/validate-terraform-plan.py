"""Reject Phase 4 Terraform plans that violate the documented cost/scope guardrails."""

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
}


def all_resources(module: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield from module.get("resources", [])
    for child in module.get("child_modules", []):
        yield from all_resources(child)


def one(resources: list[dict[str, Any]], resource_type: str) -> dict[str, Any]:
    matches = [resource for resource in resources if resource["type"] == resource_type]
    assert len(matches) == 1, (resource_type, len(matches))
    return matches[0]["values"]


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
    resources = list(all_resources(plan["planned_values"]["root_module"]))

    unexpected = sorted({resource["type"] for resource in resources} - ALLOWED_TYPES)
    assert not unexpected, f"unexpected resource types: {unexpected}"
    assert len(resources) == 13, f"expected 13 resources, got {len(resources)}"

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
        assert not any(
            "SECRET" in name or "PASSWORD" in name or "KEY" in name for name in env_names
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

    print("PASS: Terraform plan contains only the 13 expected cost-bounded Azure resources")


if __name__ == "__main__":
    main()
