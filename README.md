# Observable URL Shortener

Phase 4 of Assessment Part 2 implements a deliberately small, observable two-service URL
shortener. The services communicate only through HTTP, are independently containerised, export
portable OpenTelemetry signals locally, and have a Terraform-managed Azure deployment path with
durable Cosmos DB persistence.

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

## Architecture decisions

### ADR-001: Keep mapping ownership in the shortener

The shortener owns mapping lifecycle and storage. The resolver owns the latency-sensitive
redirect path and its event records, but looks mappings up through the internal REST contract.
This adds one network hop and couples redirect availability to the shortener; in exchange it
prevents shared-database coupling, preserves independent deployment, and creates the service
span required by the assessment.

### ADR-002: Use repository protocols with memory and Cosmos adapters

An atomic `insert_if_absent` contract makes collision handling race-safe. Local memory adapters
keep tests and development credential-free. Azure uses Cosmos `create_item` with code as both
document ID and `/code` partition key; a 409 maps to the existing bounded retry. Cosmos suits the
key/document access pattern and free tier without relational joins. Compared with PostgreSQL it
avoids schema and server operations, at the cost of Cosmos-specific partitioning and consistency
decisions. Redirect events omit destination URLs and use their own `/code` container.

### ADR-003: Fail closed when redirect-event recording fails

The resolver records the redirect event before returning `302`. If recording fails, it returns
a generic `503` instead of silently losing an event. A future durable asynchronous event path
could justify fail-open behaviour, but adding one now would exceed the assessment scope.

### ADR-004: Keep portable telemetry explicit and lifecycle-owned

Official FastAPI and instance-scoped HTTPX instrumentation create spans and propagate standard W3C
context. Each service owns its providers and exporters in FastAPI lifespan, uses explicit RED
instruments with low-cardinality labels, and exposes a custom Prometheus registry. FastAPI's
automatic meter provider is no-op to avoid duplicate HTTP metric families. Compose exports OTLP
HTTP to a minimal pinned Collector; later cloud work can replace the backend without rewriting
business instrumentation. The cost is a small intentional telemetry-module duplication so each
service remains independently buildable.

### ADR-005: Deploy to Azure Container Apps with secretless, narrow data access

Azure Container Apps runs the existing Docker images directly, provides HTTPS ingress,
scale-to-zero Consumption compute, and app-name service discovery with little platform operation.
Public GHCR avoids the cost and identity plumbing of ACR, but image packages must be explicitly
public. Terraform creates separate user-assigned identities: shortener is a Cosmos data contributor
only on `url_mappings`, while resolver is scoped only to `redirect_events`. Applications use
`DefaultAzureCredential`; database keys and connection strings are disabled. Both public ingresses
are an assessment usability trade-off: `/internal` is not an authenticated production boundary,
and production would restrict it with identity/network policy. Auth is deliberately out of scope.

## Azure architecture

All regional resources are colocated in Australia East inside one Terraform-owned resource group:

```text
Internet -> shortener Container App -> managed identity -> Cosmos url_mappings
Internet -> resolver Container App  -> managed identity -> Cosmos redirect_events
                    |
                    +-> http://<shortener-app-name> -> shortener internal API
```

One free-tier Cosmos DB for NoSQL account contains one database with 1000 RU/s provisioned shared
throughput, capped at 1000 RU/s account-wide. Neither container has dedicated throughput. It is
single-region, non-serverless, has no analytical store or dedicated gateway, and disables local
key authentication. Container Apps use 0.25 CPU/0.5 GiB, `min_replicas=0`, `max_replicas=2`, and
separate identities. Azure telemetry export stays disabled until Phase 5; JSON stdout and portable
instrumentation remain intact.

Local runs default to `REPOSITORY_BACKEND=memory`. Terraform sets `cosmos` plus non-secret Cosmos
resource names and service-specific `AZURE_CLIENT_ID` values in Azure.

## Azure deployment

Prerequisites are an Enabled Azure CLI subscription, Terraform, Docker, the repository `.venv`,
and Docker authentication to GHCR. Authenticate without storing a token in the repository:

```powershell
$env:CR_PAT | docker login ghcr.io -u lord-fifth --password-stdin
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy-azure.ps1
```

The two GitHub Packages must be Public so Container Apps can pull them without registry secrets.
The orchestrator validates locally, derives an immutable source-snapshot tag, builds and pushes
both images, initializes/plans/validates/applies Terraform, prints HTTPS outputs, runs live smoke,
restarts the shortener revision, and resolves the same mapping again as a durability proof. Local
Terraform state is deliberately accepted for the assessment and excluded from Git.

## Current local limits

- Each `POST` deliberately creates a new code; URL deduplication is not required.
- In-memory state is lost on restart and must run with one Uvicorn worker.
- The `/internal` route denotes ownership, not an authenticated security boundary in this phase.
- CI, Azure-native telemetry plumbing, cloud dashboards, alerts, and final evidence artifacts are
  intentionally deferred to later phases.

Progress against the full assessment is tracked truthfully in `RUBRIC_CHECKLIST.md`.
