# Agent guidance

## Assessment priorities

This repository is the 4-5 hour Part 2 implementation from an Advanced Software Engineering
Lead assessment. Optimise for judgment, explicit trade-offs, production sensibility,
observability, and ability to ship. Prefer depth over breadth and do not gold-plate. Assessment
Part 1 is a separate context-window memo and must remain tracked but must not be implemented as
part of the service phases.

## Architecture that must be preserved

- Maintain at least two independently deployable Python 3.12/FastAPI services using REST.
- `shortener` owns URL mappings, short-code allocation, persistence, and its internal lookup.
- `resolver` owns redirect behaviour and redirect events. It must use the shortener's HTTP API
  and must never read the mapping datastore directly.
- Preserve the resolver-to-shortener hop and its distributed OpenTelemetry trace.
- Use repository protocols. Local persistence is memory; deployed persistence is Azure Cosmos DB
  for NoSQL.
- Azure Container Apps, Cosmos DB, Terraform, public GHCR, OpenTelemetry, and Azure-native
  observability are selected architectural decisions. Do not silently change one; document a
  technical reason first.
- Production JSON stdout flows through the Container Apps Environment to one Log Analytics
  workspace. Production OTel traces and explicit RED metrics use direct Azure Monitor exporters
  to one workspace-based Application Insights resource; do not add a second cloud backend.
- Both existing user-assigned identities have `Monitoring Metrics Publisher` at Application
  Insights scope and authenticate telemetry with `AZURE_CLIENT_ID`. Keep local authentication
  disabled and never add telemetry API keys or client secrets.
- Propagate one exact `X-Correlation-ID` across the full HTTP path and expose it to later logging
  and tracing through request context.
- Keep correlation IDs and OpenTelemetry trace IDs distinct. Enrich logs only from real current
  trace context; never fabricate or manually propagate trace/span IDs.
- Use standard W3C propagation and instance-scoped instrumentation on the resolver's shared HTTPX
  client. Do not globally instrument unrelated clients.
- RED labels must remain low-cardinality. Request-specific IDs, raw paths, short codes, URLs, and
  query strings must never become metric labels.
- Telemetry backend failure must never fail user requests. Later cloud work should reuse the OTLP
  application instrumentation and change the backend rather than replacing it.

## Complete Part 2 acceptance criteria

The final system needs two containerised services with a clear contract and documented boundary;
a real managed-cloud deployment with a live URL or one-command reproduction; IaC with no
application click-ops; structured correlated logs; visible/scraped RED rate, error, and duration
metrics; an OpenTelemetry trace spanning both services; demonstrated correlation across logs,
metrics, and traces; a dashboard; an alert; health/readiness; graceful shutdown; CI that builds,
tests, and produces deployable images; safe secret handling; local and deployment instructions;
3-5 ADR-style decisions covering boundary, datastore, cloud, observability, and what would be done
differently; and trace, dashboard, and correlated structured-log evidence.

The master source of status is `RUBRIC_CHECKLIST.md`. Mark an item complete only after it has
actually been demonstrated.

## Current phase and deferred work

Phase 0-1 includes the two local services, in-memory repositories, correlation semantics,
health/readiness, lifespan ownership and shutdown, unit/integration tests, Ruff, real Dockerfiles,
Docker Compose, and the cross-service smoke test.

Phase 2 added standard-library structured JSON application logs to stdout. The application logging
API automatically reads correlation context and deliberately excludes request bodies, query
strings, and destination URLs.

Phase 3 adds programmatic OpenTelemetry FastAPI/HTTPX tracing, portable log enrichment, explicit
application RED metrics, `/metrics`, and a minimal local OTLP Collector. Telemetry providers,
exporters, the Prometheus registry, and HTTPX instrumentation are lifespan-owned and shut down with
bounded export timeouts. Operational endpoints are excluded. FastAPI tracing uses a no-op meter
provider so only the explicit RED instruments represent server HTTP metrics.

Phase 4 adds the first managed deployment: Azure Container Apps in Australia East, public GHCR
images, and one free-tier Cosmos DB for NoSQL account. Cosmos uses provisioned database-level
shared throughput capped at 1000 RU/s, never serverless or container-dedicated throughput. Local
repositories remain memory by default; cloud repositories are selected with
`REPOSITORY_BACKEND=cosmos`.

Each Container App uses its own user-assigned managed identity and `DefaultAzureCredential`; no
Cosmos keys, connection strings, client secrets, or registry credentials belong in application
configuration. Shortener Cosmos data-plane access is scoped only to `url_mappings`; resolver
access is scoped only to `redirect_events`. Resolver still reads mappings exclusively through
`http://<shortener-app-name>` Container Apps service discovery. Both apps scale to zero with
`min_replicas=0`.

Phase 5 adds one 30-day `PerGB2018` Log Analytics workspace, one workspace-based Application
Insights resource with a 1 GB/day cap and 100% assessment sampling, explicit Azure Monitor trace
and metric exporters, a six-query production workbook, and an enabled scheduled error query.
Container Apps stdout remains the only production log export path. Prometheus stays active in all
modes; local Docker remains on the OTLP Collector, while Azure and OTLP remote exporters are
mutually exclusive. Azure's custom histogram representation supports aggregate average/max, not a
defensible p95. Preserve the dashboard -> service/operation -> distributed trace -> correlated
JSON log investigation workflow. Managed Grafana and the Container Apps managed OTel agent are
not part of this architecture.

The AzureRM provider must keep explicit narrow registration for `Microsoft.App`,
`Microsoft.DocumentDB`, `Microsoft.Insights`, and `Microsoft.OperationalInsights`; do not replace
it with broad provider registration or portal/CLI click-ops. Both runtime manifests must retain a
pinned `aiohttp` because the asynchronous Azure Identity and Cosmos clients require that transport,
plus the explicit Azure Monitor exporter compatible with the pinned OTel SDK. Production-image
checks must exercise those imports inside Linux images. Keep each app's `AZURE_CLIENT_ID` wired to
the same user-assigned identity attached to that app, and keep the Consumption workload profile
explicit so provider refreshes do not introduce unrelated drift.

Until a later explicit phase, do not add another telemetry backend, managed Grafana, an Azure
hosted OTel Collector, GitHub Actions, Redis, Service Bus, Kubernetes, authentication, a UI, or
Assessment Part 1. Do not introduce GCP, Cloud Run, Firestore, ACR, AKS, App Service, VNet, private
endpoints, API Management, Front Door, or other resources outside the existing Terraform root.
Authenticated portal screenshots remain human work and must never be claimed without real files.

Do not commit, push, create a repository, store credentials, or modify global Python installations
unless the user explicitly changes scope.

## Engineering rules

- Use an isolated `.venv`, environment configuration, safe `.env.example` values, meaningful type
  hints, deterministic tests, and minimal dependencies.
- Keep mapping insertion atomic; never implement collision handling as a separate existence check
  followed by a write.
- Use one shared resolver `httpx.AsyncClient`, owned and closed by FastAPI lifespan.
- Keep trace and metric export optional and environment-configured. OTLP exporter errors are never
  allowed to alter HTTP responses.
- Keep Cosmos clients and credentials lifespan-owned. Mapping writes must use atomic create and
  treat conflict as collision; never implement read-then-upsert.
- Never make health/readiness perform a per-request external dependency probe.
- Preserve safe error mapping: unknown code is `404`; failed or invalid upstream is `503`; never
  expose stack traces or internal exception text.
- Use a single worker while repositories are in memory.
- After every substantive phase, run relevant tests and Ruff. Before calling Phase 0-1 complete,
  run all tests, both Ruff checks, both image builds, Compose startup, and the real smoke script.
- Preserve unrelated user work and update `RUBRIC_CHECKLIST.md` truthfully after validation.
