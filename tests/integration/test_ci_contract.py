from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml"


def workflow() -> str:
    return WORKFLOW_PATH.read_text()


def test_ci_has_required_triggers_permissions_and_pinned_tools() -> None:
    content = workflow()

    assert "push:" in content
    assert "pull_request:" in content
    assert content.count("branches: [main]") == 2
    assert "workflow_dispatch:" in content
    assert "permissions:\n  contents: read" in content
    assert "actions/checkout@v7" in content
    assert "actions/setup-python@v6" in content
    assert "hashicorp/setup-terraform@v4" in content
    assert "actions/upload-artifact@v7" in content
    assert "python-version: 3.12.10" in content
    assert "terraform_version: 1.15.8" in content


def test_ci_validates_code_terraform_images_and_real_compose_flow() -> None:
    content = workflow()

    for command in (
        "python -m pytest",
        "python -m ruff check .",
        "python -m ruff format --check .",
        "docker compose config --quiet",
        "terraform -chdir=infra init -backend=false -input=false",
        "terraform -chdir=infra validate",
        "docker build --tag",
        "docker compose up --detach --build --wait --wait-timeout 60",
        "python scripts/smoke.py",
        "docker compose down --remove-orphans",
    ):
        assert command in content

    assert "if: always()" in content
    assert "linux/amd64" in content
    assert "shortener.main:app" in content
    assert "resolver.main:app" in content


def test_ci_packages_two_verifiable_images_without_secrets_or_deployment() -> None:
    content = workflow()

    assert "docker save --output artifacts/shortener-image.tar" in content
    assert "docker save --output artifacts/resolver-image.tar" in content
    assert "sha256sum --check SHA256SUMS.txt" in content
    assert "artifacts/BUILD_INFO.txt" in content
    assert "if-no-files-found: error" in content
    assert "retention-days: 7" in content
    assert "secrets." not in content
    assert "docker push" not in content
    assert "terraform apply" not in content
    assert "az login" not in content
    assert "id-token:" not in content
    assert "packages:" not in content
