# Scripts

`smoke.py` is the local Compose acceptance path. `smoke-azure.py` validates the live public
services and supports a second existing-code request for durability proof.

`deploy-azure.ps1` is the phase-neutral, one-command Azure orchestrator. It validates locally,
publishes immutable public GHCR images, safety-validates and applies the Terraform plan, runs the
live and post-restart smoke checks, then requires a safety-validated no-drift plan. Run it only
from a reviewed workspace with Docker, Azure CLI, Terraform, the repository virtual environment,
and GHCR authentication ready:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-azure.ps1
```

`validate-terraform-plan.py` enforces the assessment's resource, region, identity, Cosmos cost,
Container Apps, and Azure observability guardrails for both saved plans.
