# Observable URL Shortener

This repository is the completed Assessment Part 2 implementation of a deliberately small,
observable two-service URL shortener. The services communicate only through HTTP, are independently
containerised, export portable OpenTelemetry signals, and run in a Terraform-managed Azure
deployment with durable Cosmos DB persistence and Azure-native production observability.
Credential-free CI validates the complete local stack and packages both deployable images without
publishing or deploying.

## Architecture

| Service | Owns | Public contract | Internal dependency |
| --- | --- | --- | --- |
| `shortener` | URL mappings and short-code allocation | `POST /v1/urls` | None |
| `resolver` | Redirect behaviour and redirect events | `GET /{code}` | `GET /internal/v1/urls/{code}` on `shortener` |

Both services also expose `GET /healthz`, `GET /readyz`, and `GET /metrics`. The resolver never
reads the mapping repository directly. A successful resolution is therefore a genuine HTTP
service hop represented by one distributed trace.

Every request accepts or creates an `X-Correlation-ID`, returns it to the caller, and makes
it available in request context. The resolver sends the exact ID to the shortener and
requires it to be echoed before redirecting. Incoming IDs are limited to 1-128 visible ASCII
characters; invalid values are replaced with a UUID.

## HTTP examples

Create a mapping:

```http
POST /v1/urls
Content-Type: application/json

{"url":"https://example.com/some/path"}
```

The shortener returns `201` with `code` and `short_url`. Only HTTP(S) URLs containing a host
are accepted; invalid requests return `422`.

Resolve with `GET /{code}` on the resolver. A known code returns `302`; an unknown code
returns `404`; a failed or contract-violating shortener response returns `503`.

The validated public origins are:

- shortener: `https://ous-shortener-qafji9.happybay-4a23884e.australiaeast.azurecontainerapps.io`;
- resolver: `https://ous-resolver-qafji9.happybay-4a23884e.australiaeast.azurecontainerapps.io`.

The shortener's interactive contract is available at its `/docs` path, and the resolver exposes
its own contract at its `/docs` path. A bare `GET /` returning `404` is normal: there is no landing
page or UI, and redirect codes are required on the resolver route.

For example, create a live mapping with PowerShell and inspect the returned resolver URL:

```powershell
$shortener = "https://ous-shortener-qafji9.happybay-4a23884e.australiaeast.azurecontainerapps.io"
$created = Invoke-RestMethod -Method Post -Uri "$shortener/v1/urls" `
  -ContentType "application/json" -Headers @{ "X-Correlation-ID" = "readme-example" } `
  -Body '{"url":"https://example.com/assessment"}'
$created
curl.exe -i $created.short_url -H "X-Correlation-ID: readme-example"
```

## Local setup

Python 3.12 is required. Keep dependencies isolated in the repository:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Run the services in separate PowerShell terminals:

```powershell
$env:RESOLVER_BASE_URL = "http://localhost:8081"
.\.venv\Scripts\python.exe -m uvicorn shortener.main:app --app-dir services/shortener/app --host 0.0.0.0 --port 8080
```

```powershell
$env:SHORTENER_BASE_URL = "http://localhost:8080"
.\.venv\Scripts\python.exe -m uvicorn resolver.main:app --app-dir services/resolver/app --host 0.0.0.0 --port 8081
```

Safe example configuration is listed in `.env.example`; neither service automatically reads
an `.env` file.

## Test and lint

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
```

The integration test starts both ASGI applications and crosses the same HTTP adapter used in
production. Resolver unit tests mock only the HTTP boundary and never import shortener code.

## Continuous integration and deployable artifacts

`.github/workflows/ci.yml` runs on pushes and pull requests to `main`, plus manual dispatch. It
uses Python 3.12.10 and Terraform 1.15.8 to run the full pytest and Ruff gates, validate Compose
and Terraform without cloud credentials, build and inspect both Linux/amd64 production images,
and run the real Compose smoke/OTel validation. Cleanup runs even after a failed smoke test.

CI deliberately receives read-only repository permission and has no Azure login, package-write
permission, or repository secrets. It does not push images or deploy infrastructure. Instead it
uploads two separate Docker image archives, `SHA256SUMS.txt`, and safe `BUILD_INFO.txt` metadata as
one seven-day workflow artifact. After downloading and verifying the artifact, load the images
without rebuilding:

```powershell
Get-Content .\SHA256SUMS.txt
docker load --input .\shortener-image.tar
docker load --input .\resolver-image.tar
Get-Content .\BUILD_INFO.txt
```

The archive checksums are generated and verified during CI. GitHub Actions run `31765838762`
succeeded for commit `e888cba9c1f0d29bce6182602cf848828ef53821`; its deployable artifact was
independently downloaded and inspected, and independently recalculated checksums matched
`SHA256SUMS.txt`. The later documentation commit
`380f2975fb3d7ab85702bcd9ab7f90120114c264` also produced a successful CI run.

## Local observability

Both services emit application logs as single-line JSON to stdout, so containers need no logging
SDK or local log files. Stable fields include `timestamp`, `severity`, `service`, `event`,
`message`, and `correlation_id`; HTTP completion events also contain method, path, status, and
duration. Request bodies, query strings, and destination URLs are deliberately excluded.

Every request preserves a valid incoming `X-Correlation-ID` or creates a UUID and returns it. The
resolver propagates the same ID to the shortener. OpenTelemetry independently creates and
propagates W3C Trace Context. A correlation ID is an application-visible identifier; it is not a
trace ID and is never copied into one. Logs emitted in an active span add the real `trace_id`,
`span_id`, and `trace_sampled` values and omit those fields outside a valid span.

The resolver instruments only its lifespan-owned HTTPX client. The expected trace is:

```text
client -> resolver GET /{code} SERVER
              -> shortener lookup HTTP CLIENT
                    -> shortener GET /internal/v1/urls/{code} SERVER
```

Both services record the following explicit OpenTelemetry metrics; the Prometheus endpoint
converts dots to underscores and adds the usual counter/histogram suffixes:

| RED signal | OpenTelemetry metric | Definition |
| --- | --- | --- |
| Rate | `url_shortener.http.server.requests` | Incoming application requests |
| Errors | `url_shortener.http.server.errors` | Responses with status `>=500` |
| Duration | `url_shortener.http.server.request.duration` | Request latency histogram in seconds |

A normal `404` is visible on the request metric but is not an availability error. `/healthz`,
`/readyz`, and `/metrics` are excluded from tracing and RED metrics so probes and scrapes do not
dominate application signals. Labels are limited to method, route template, and response status;
request paths, codes, URLs, correlation IDs, trace IDs, and span IDs are never labels. The error
counter is created lazily, so it is absent from `/metrics` until the first `>=500` response.

## Docker Compose acceptance path

With Docker Desktop running:

```powershell
docker compose up --detach --build --wait --wait-timeout 60
.\.venv\Scripts\python.exe .\scripts\smoke.py
Invoke-WebRequest -UseBasicParsing http://localhost:8080/metrics | Select-Object -Expand Content
Invoke-WebRequest -UseBasicParsing http://localhost:8081/metrics | Select-Object -Expand Content
docker compose logs --no-color shortener resolver
docker compose logs --no-color otel-collector
docker compose down --remove-orphans
```

Compose publishes shortener on `localhost:8080` and resolver on `localhost:8081`; the pinned local
Collector stays on the Compose network. The smoke test creates and resolves a mapping without
following the redirect, validates bounded Prometheus output, parses both services' JSON logs, and
proves one real trace's SERVER -> CLIENT -> SERVER parent chain in Collector debug output. It also
waits for OTLP metrics from both services. The resolver's strict correlation-ID echo remains a
separate application contract.

Trace and metric export are deliberately outside the business critical path. If the Collector is
unavailable, export errors may be logged, but URL creation and resolution continue normally.
Azure and local remote exporters are mutually exclusive: Compose selects OTLP, Azure selects the
explicit Azure Monitor exporters, and `/metrics` remains available in either mode. Merely
installing the Azure packages does not cause local authentication attempts.

## Architecture decisions

### ADR-001: Preserve the HTTP service boundary and event ownership

The shortener owns mapping lifecycle and storage. The resolver owns the latency-sensitive
redirect path and its event records, but looks mappings up through the internal REST contract.
This adds one network hop and couples redirect availability to the shortener; in exchange it
prevents shared-database coupling, preserves independent deployment, and creates the service
span required by the assessment.

The resolver records its redirect event before returning `302`; a failed write returns a generic
`503` rather than silently losing an event. A future durable asynchronous event path could justify
fail-open behaviour, but adding one here would weaken the small, explicit ownership boundary.

### ADR-002: Use repository protocols with memory and Cosmos adapters

An atomic `insert_if_absent` contract makes collision handling race-safe. Local memory adapters
keep tests and development credential-free. Azure uses Cosmos `create_item` with code as both
document ID and `/code` partition key; a 409 maps to the existing bounded retry. Cosmos suits the
key/document access pattern and free tier without relational joins. Compared with PostgreSQL it
avoids schema and server operations, at the cost of Cosmos-specific partitioning and consistency
decisions. Redirect events omit destination URLs and use their own `/code` container.

### ADR-003: Deploy to Azure Container Apps with secretless, narrow data access

Azure Container Apps runs the existing Docker images directly, provides HTTPS ingress,
scale-to-zero Consumption compute, and app-name service discovery with little platform operation.
Public GHCR avoids the cost and identity plumbing of ACR, but image packages must be explicitly
public. Terraform creates separate user-assigned identities: shortener is a Cosmos data contributor
only on `url_mappings`, while resolver is scoped only to `redirect_events`. Applications use
`DefaultAzureCredential`; database keys and connection strings are disabled. Both public ingresses
are an assessment usability trade-off: `/internal` is not an authenticated production boundary,
and production would restrict it with identity/network policy. Auth is deliberately out of scope.

### ADR-004: Keep portable telemetry explicit and lifecycle-owned

Official FastAPI and instance-scoped HTTPX instrumentation create spans and propagate standard W3C
context. Each service owns its providers and exporters in FastAPI lifespan, uses explicit RED
instruments with low-cardinality labels, and exposes a custom Prometheus registry. FastAPI's
automatic meter provider is no-op to avoid duplicate HTTP metric families. Compose exports OTLP
HTTP to a minimal pinned Collector. Azure selects explicit Azure Monitor trace and metric exporters
on those same providers, authenticated with the service's existing managed identity. This avoids
auto-configuration replacing providers or duplicating instrumentation. The cost is a small
intentional telemetry-module duplication so each service remains independently buildable.

### ADR-005: Prioritise production hardening after measured need

With more time I would move Terraform state to a locked remote backend, restrict the shortener's
internal endpoint using service identity/network policy, add sampling and retention budgets from
observed traffic, route alerts through an environment-owned action group, and validate dashboard
and alert queries in CI. I would separate evidence traffic from user traffic with a bounded
non-identifying deployment annotation, never request IDs as metric dimensions. These are conscious
next steps, not omissions to hide inside this time-boxed implementation.

## Azure architecture

All regional resources are colocated in Australia East inside one Terraform-owned resource group:

```text
Internet -> shortener Container App -> managed identity -> Cosmos url_mappings
Internet -> resolver Container App  -> managed identity -> Cosmos redirect_events
                    |
                    +-> http://<shortener-app-name> -> shortener internal API

Container stdout/stderr -> Container Apps Environment -> Log Analytics
OTel traces + RED metrics -> managed identity -> shared Application Insights
                                              -> Terraform workbook + error alert
```

One free-tier Cosmos DB for NoSQL account contains one database with 1000 RU/s provisioned shared
throughput, capped at 1000 RU/s account-wide. Neither container has dedicated throughput. It is
single-region, non-serverless, has no analytical store or dedicated gateway, and disables local
key authentication. Container Apps use 0.25 CPU/0.5 GiB, `min_replicas=0`, `max_replicas=2`, and
separate identities. The same identities have `Monitoring Metrics Publisher` only at the shared
Application Insights resource. Application Insights local ingestion authentication is disabled;
its connection string is non-secret routing metadata, while Entra managed identity authenticates
publication.

Local runs default to `REPOSITORY_BACKEND=memory`. Terraform sets `cosmos` plus non-secret Cosmos
resource names and service-specific `AZURE_CLIENT_ID` values in Azure.

## Azure deployment

The AzureRM provider explicitly registers only `Microsoft.App`, `Microsoft.DocumentDB`,
`Microsoft.Insights`, and `Microsoft.OperationalInsights`; provider registration is therefore
reproducible without portal or Azure CLI registration. The Consumption workload profile is also
explicit in Terraform so a refresh does not propose removing Azure-normalised defaults.

Both production manifests pin `aiohttp`, which is required by the asynchronous Azure Identity and
Cosmos clients. Production-image validation imports `aiohttp`, constructs the async credential and
Cosmos client, and closes both inside the Linux container rather than relying on the developer
virtual environment.

Prerequisites are an Enabled Azure CLI subscription, Terraform, Docker, the repository `.venv`,
and Docker authentication to GHCR. Authenticate without storing a token in the repository:

```powershell
$env:CR_PAT | docker login ghcr.io -u lord-fifth --password-stdin
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-azure.ps1
```

The two GitHub Packages must be Public so Container Apps can pull them without registry secrets.
The orchestrator validates locally, derives a phase-neutral immutable `deploy-<content-hash>` tag,
builds and pushes both images, initializes/plans/safety-validates/applies Terraform, prints HTTPS
outputs, runs live smoke, restarts the shortener revision, and resolves the same mapping again as
a durability proof. It finishes with a second safety-validated detailed-exit-code plan, requires
zero drift, and removes only its exact saved plan files; it never applies that second plan. Local
Terraform state is deliberately accepted for the assessment and excluded from Git.

### Validated Phase 4 deployment

The Australia East deployment was validated on 14 August 2026 using immutable public images tagged
`phase4-9350f17348ab`:

| Service | Live HTTPS origin |
| --- | --- |
| Shortener | `https://ous-shortener-qafji9.happybay-4a23884e.australiaeast.azurecontainerapps.io` |
| Resolver | `https://ous-resolver-qafji9.happybay-4a23884e.australiaeast.azurecontainerapps.io` |

The recovery apply changed only the two Container App images (`0 added, 2 changed, 0 destroyed`),
and a subsequent Terraform plan reported no drift. Live validation demonstrated health/readiness,
`POST` creation, the public resolver URL in the response, a `302` through the configured internal
`http://ous-shortener-qafji9` hop, exact `Location` and correlation-ID behaviour, and an unknown-code
`404`. Code `qXJLudH2` resolved after restarting the shortener revision. Managed-identity queries
then read that mapping and three matching redirect-event documents from their separately scoped
Cosmos containers after both application revisions had been restarted.

## Production observability

Terraform provisions one `PerGB2018` Log Analytics workspace and links it to the existing
Container Apps Environment. The applications keep their vendor-neutral JSON stdout contract;
Azure stores that stream in `ContainerAppConsoleLogs_CL`, where `Log_s` is parsed as JSON for
correlation queries. No Azure logging SDK or duplicate log export path is used.

Both applications use the same workspace-based Application Insights component while remaining
distinct through `service.name` / cloud role. The existing providers export traces and explicit
RED metrics directly through `AzureMonitorTraceExporter` and `AzureMonitorMetricExporter` with
the app's own `AZURE_CLIENT_ID`. The Prometheus reader remains active. Azure and OTLP export are
configuration-exclusive, and exporter initialization/delivery failures do not fail business
requests.

The production workbook **Observable URL Shortener - Production Observability** contains six
query panels: request rate, server errors, duration average/max, signals by service, recent 5xx,
and trace investigation. Azure represents custom duration histograms using `valueSum`,
`valueCount`, `valueMin`, and `valueMax`; because this does not provide a defensible p95, the
workbook clearly uses aggregate average and maximum seconds. The scheduled-query alert evaluates
the explicit error counter every five minutes and raises at `TotalErrors > 0`; 404 remains outside
that metric by application definition.

The intended incident workflow is:

```text
workbook RED signal -> affected service/route/status
                    -> representative distributed trace
                    -> trace ID and application correlation ID
                    -> parsed JSON logs in Log Analytics
```

Managed Grafana and the Container Apps managed OTel agent were intentionally not added. Azure's
native workspace, Application Insights, workbook, and alert meet the assessment scope without a
second hosted backend, while direct exporters preserve the explicitly lifecycle-owned providers,
HTTPX client instrumentation, RED instruments, and local Collector workflow.

The reproducible KQL, text evidence, and real authenticated Portal screenshots live in
`evidence/`; `evidence/README.md` maps each normalized file to the criterion it proves.

### Validated Phase 5 deployment

The Australia East deployment was validated on 14 August 2026 using public immutable
`linux/amd64` images tagged `phase5-7b3b526275b4`. Terraform added six observability resources
and updated the environment and both apps in place with zero destroys. After correcting a
provider-required lowercase workbook source ID, the isolated recovery apply added the workbook;
the final plan reported no changes.

The known correlation ID
`azure-smoke-ef8c5d5a-80cb-4a90-bf7b-1290ea79ebfb` produced resolver trace
`aa0c88bbd5e263bc7688bdffdc05ca86`. Application Insights showed resolver SERVER span
`7f1d507876d17716` -> resolver HTTP dependency `ee44e32a578c97fe` -> shortener SERVER span
`ff9a1edee4478588`. Parsed Log Analytics rows for both services contained that same correlation
and trace ID. Both services produced request and duration custom metrics. The server-error series
was correctly absent because no >=500 validation response occurred; real 404 traffic appeared
only in the request counter.

### Validated Phase 6 delivery

The phase-neutral deployment orchestrator completed uninterrupted on 14 August 2026 and deployed
public immutable Linux/amd64 images tagged `deploy-54aec4300f56`. Its safety-validated plan changed
only the two Container App image fields in place (`0 added, 2 changed, 0 destroyed`). Both new
revisions reached Running/Succeeded, the complete cloud smoke passed, code `eovnxtAq` survived a
shortener revision restart, and the final safety-validated detailed plan reported no changes.

An independent post-script smoke created and resolved `GBRrBkfg`, preserved correlation ID
`azure-smoke-ffc6b862-5a9e-43e9-be4f-354319cab4c4`, returned the exact target Location, and
confirmed unknown-code `404`. The full safe command/output summary is in
`evidence/phase6-validation.md`. GitHub Actions run `31765838762` then passed every CI gate and
produced the independently verified deployable image artifact; the subsequent documentation
commit `380f2975fb3d7ab85702bcd9ab7f90120114c264` also passed CI.

## Known limits and trade-offs

- Each `POST` deliberately creates a new code; URL deduplication is not required.
- In-memory state is lost on restart and must run with one Uvicorn worker.
- The `/internal` route denotes ownership, not an authenticated security boundary in the assessment
  deployment.
- Azure Portal screenshots and reproducible KQL/text evidence are present under `evidence/`.

Final Part 2 status is tracked in `RUBRIC_CHECKLIST.md`; Part 1 is an external submission
deliverable and is not validated from this repository.
