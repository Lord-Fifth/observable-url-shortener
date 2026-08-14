# Phase 6 delivery validation

Validated 14 August 2026 from local baseline commit
`8f67b7ec70e8ae494544131b3b9374d175fe848d` and successful GitHub Actions commit
`e888cba9c1f0d29bce6182602cf848828ef53821`.

## Local and CI-equivalent validation

- Python 3.12.10 and Terraform 1.15.8 matched the CI pins.
- The final suite passed: 156 tests.
- `ruff check .` and `ruff format --check .` passed across 46 files.
- Docker Compose configuration and Terraform format, credential-free initialization, and
  validation passed.
- Both production Dockerfiles built as Linux/amd64 images. Their expected Uvicorn commands and
  `aiohttp`, asynchronous Azure Identity/Cosmos, and application imports succeeded inside the
  images.
- The real Compose smoke passed health/readiness, URL creation, 302 resolution, correlation,
  structured JSON logs, explicit RED metrics, and the resolver CLIENT span between both SERVER
  spans. Compose then shut down cleanly.

The GitHub Actions workflow implements the same gates with `contents: read`, no secrets, no Azure
login, no registry publication, and no Terraform apply. It creates separate Docker archives,
checksums, and safe build metadata as a seven-day artifact.

## Real GitHub Actions validation

GitHub Actions run `31765838762`, job `94661424809` (`validate-build-artifacts`), completed
successfully for commit `e888cba9c1f0d29bce6182602cf848828ef53821`. The successful job covered
the tests, Ruff, Docker Compose configuration, credential-free Terraform validation, production
image builds and inspection, the real Compose smoke/distributed-trace validation, deployable image
packaging, and artifact upload.

The uploaded artifact was
`observable-url-shortener-images-e888cba9c1f0d29bce6182602cf848828ef53821` and contained:

- `shortener-image.tar`
- `resolver-image.tar`
- `SHA256SUMS.txt`
- `BUILD_INFO.txt`

The artifact was independently downloaded and inspected. Independently recalculated SHA256
checksums for both image archives matched `SHA256SUMS.txt`. `BUILD_INFO.txt` had an empty
`terraform_version` metadata field; this cosmetic observation does not affect the validated
Terraform gate, deployable image archives, or their verified checksums.

## Uninterrupted Azure deployment proof

The exact command completed successfully:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-azure.ps1
```

The selected subscription was Enabled and the region was `australiaeast`. The script derived and
published public immutable tag `deploy-54aec4300f56`:

| Service | GHCR manifest digest |
| --- | --- |
| shortener | `sha256:5f0257ac69308bb35a6a6c69dec9d592cb8ddcc9188ee40a011724d94c301827` |
| resolver | `sha256:c98efd20cefa9a1c1397ba2e079ebd7bec921801a209dea68c105cbc3d390e63` |

The safety-validated plan changed only the two Container App images in place: zero additions, two
changes, and zero destroys. No stateful resource, identity, RBAC assignment, or observability
resource was replaced. Both latest-ready revisions were `0000005`, with provisioning Succeeded
and runtime status Running.

The script's cloud smoke created and resolved `eovnxtAq`, restarted the shortener revision, then
resolved the same Cosmos-backed mapping with correlation ID
`azure-durability-a3971548-b6e5-4881-9343-10ebb6a6688b`. This proves the mapping was not process
memory. Resolver redirects are fail-closed on event-write failure, so the successful pre- and
post-restart 302 responses also exercised Cosmos redirect-event persistence.

An independent post-script smoke created `GBRrBkfg` for
`https://example.com/azure-smoke/08089ec0-a0d3-4bc7-900c-ef6b0e95f5c7` and preserved correlation
ID `azure-smoke-ffc6b862-5a9e-43e9-be4f-354319cab4c4`. That check covered both health/readiness
endpoints, POST 201, the public resolver URL, resolver-to-shortener lookup, exact 302 Location,
unknown-code 404, and a later successful lookup.

The final detailed-exit-code Terraform plan reported no changes, the 19-resource safety validator
passed, and the script removed its exact saved plans without touching Terraform state.

## Live endpoints

- Shortener: `https://ous-shortener-qafji9.happybay-4a23884e.australiaeast.azurecontainerapps.io`
- Resolver: `https://ous-resolver-qafji9.happybay-4a23884e.australiaeast.azurecontainerapps.io`
