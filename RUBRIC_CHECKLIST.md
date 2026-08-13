# Master assessment checklist

An item is checked only after implementation and direct validation. Deferred items remain open.

## Part 1 - Context-window memo (NOT STARTED)

- [ ] <=600 words - NOT STARTED
- [ ] Design-thinking framing - NOT STARTED
- [ ] Mechanics - NOT STARTED
- [ ] Trade-offs - NOT STARTED
- [ ] Recommendation - NOT STARTED
- [ ] Validation approach - NOT STARTED
- [ ] Final one-page deliverable - NOT STARTED

## Part 2 - System

### Architecture

- [x] Two independently deployable services
- [x] Boundary rationale documented
- [x] Clean HTTP contract
- [x] Both container images successfully built

### Persistence

- [x] Local persistence strategy
- [x] Durable deployed persistence

### Cloud

- [x] Managed-cloud deployment
- [x] Live URL OR one-command reproducible deployment
- [x] Infrastructure as code
- [x] No click-ops required for application infrastructure

### Observability

- [x] Structured logs
- [x] Correlation-ID generation
- [x] Correlation-ID propagation
- [x] RED rate metric
- [x] RED error metric
- [x] RED duration metric
- [x] RED metrics exposed
- [x] RED metrics visible/scraped
- [x] OpenTelemetry instrumentation
- [x] Distributed trace spanning services
- [x] Logs correlated with trace
- [x] Metrics correlated operationally with services/traces
- [x] Dashboard
- [x] Alert

### Operability

- [x] Health endpoint
- [x] Readiness endpoint
- [x] Graceful application-resource shutdown
- [x] Safe upstream failure handling

### Engineering

- [x] Tests
- [ ] CI build
- [ ] CI test
- [ ] CI deployable artifact
- [x] Deployed secrets handled correctly
- [x] No hardcoded credentials

### README

- [x] Local-run instructions
- [x] Deployment instructions
- [x] Service-boundary ADR
- [x] Datastore ADR
- [x] Cloud-target ADR
- [x] Observability ADR
- [x] What-I-would-do-differently ADR

### Evidence

- [ ] Trace screenshot
- [ ] Dashboard screenshot
- [x] Structured log evidence with correlation ID

## Phase 0-1 definition of done

- [x] Repository structure exists
- [x] Shortener runs locally
- [x] Resolver runs locally
- [x] Service contracts work in integration test
- [x] Repository abstractions exist
- [x] In-memory implementations work
- [x] Correlation-ID contract works
- [x] Health/readiness work
- [x] Graceful local application lifecycle works
- [x] Focused unit tests pass
- [x] Full repository test suite passes
- [x] Full repository Ruff checks pass
- [x] Both Docker images build
- [x] Docker Compose starts both services
- [x] Real cross-service Compose smoke test passes
- [x] `RUBRIC_CHECKLIST.md` exists
- [x] `AGENTS.md` exists
- [x] README contains minimal Phase 0-1 local instructions

## Phase 2 definition of done

- [x] Both services emit valid single-line JSON application logs
- [x] Application logs are written to stdout
- [x] Request logs automatically include correlation IDs
- [x] Resolver propagates the identical correlation ID to shortener
- [x] Same known correlation ID demonstrated in both real-container logs
- [x] Request logs contain method, path, status, and duration
- [x] Upstream and 5xx failures use ERROR severity
- [x] Request bodies, query strings, and destination URLs are excluded
- [x] Concurrent requests do not leak correlation context
- [x] Existing service contracts and behavior remain passing
- [x] Full test suite passes
- [x] Ruff lint and format checks pass
- [x] Both Phase 2 Docker images build
- [x] Docker Compose starts both services healthy
- [x] Real cross-service smoke and JSON-log validation pass
- [x] Graceful Compose shutdown remains valid
- [x] README documents local structured logging and correlation
- [x] `AGENTS.md` preserves the Phase 2 logging/context decision
- [x] Master rubric status updated truthfully

## Phase 3 definition of done

- [x] Existing behaviour remains green
- [x] Both FastAPI services produce real OpenTelemetry server spans
- [x] Resolver's real HTTPX call produces a client span
- [x] Standard W3C trace context propagates resolver to shortener
- [x] One distributed trace contains resolver and shortener spans
- [x] Existing correlation ID remains separate and preserved
- [x] Structured logs contain real trace and span IDs only when a valid span is active
- [x] Application RED rate, `>=500` error, and duration histogram metrics exist
- [x] `/metrics` exposes RED metrics in Prometheus text format
- [x] Metric labels have bounded cardinality and exclude request-specific IDs, URLs, and codes
- [x] Health, readiness, and metrics endpoints are excluded from application RED metrics
- [x] OTLP traces reach the local Collector
- [x] OTLP metrics reach the local Collector
- [x] Real-container logs prove cross-service trace continuity
- [x] Collector output proves both services participate in the same trace
- [x] Collector failure does not break normal application functionality
- [x] Telemetry flush and shutdown complete cleanly with bounded export timeouts
- [x] Full test suite passes
- [x] Ruff lint and format checks pass
- [x] Both Phase 3 Docker images build
- [x] Docker Compose starts all services healthy
- [x] Extended smoke validation passes
- [x] README documents trace flow, correlation distinction, RED metrics, and local inspection
- [x] `AGENTS.md` preserves Phase 3 telemetry decisions
- [x] Master rubric status updated truthfully

## Phase 4 definition of done

- [x] Baseline tests were established
- [x] Cosmos adapters implemented
- [x] Local memory backend remains default
- [x] `DefaultAzureCredential` is used
- [x] No Cosmos keys exist in application configuration
- [x] Atomic mapping creation is implemented
- [x] Cosmos repository tests pass
- [x] Terraform is implemented
- [x] Terraform state is ignored and the provider lock file exists
- [x] AzureRM providers initialize
- [x] Resource providers registered through Terraform/provider mechanism
- [x] Resource group created via IaC
- [x] Cosmos account created via IaC
- [x] Cosmos free tier directly verified in Azure
- [x] Cosmos directly verified as non-serverless with throughput <=1000 RU/s
- [x] Both Cosmos containers directly verified in Azure
- [x] Shortener identity scope directly verified on `url_mappings`
- [x] Resolver identity scope directly verified on `redirect_events`
- [x] Both images build locally
- [x] Images pushed to GHCR
- [x] Images anonymously pullable from GHCR
- [x] Container Apps environment created
- [x] Shortener Container App created
- [x] Resolver Container App created
- [x] Deployed minimum replicas directly verified as zero
- [x] Both live HTTPS FQDNs exist
- [x] Resolver cloud call directly verified through service discovery
- [x] Shortener directly verified returning the public resolver URL
- [x] Live health and readiness checks pass
- [x] Live create/resolve flow passes
- [x] Live correlation ID remains correct
- [x] Mapping survives a deployed process lifecycle
- [x] Redirect-event persistence directly demonstrated
- [x] Local Docker and Compose workflow remains green
- [x] Existing local OpenTelemetry workflow remains green
- [ ] Deployment script works end to end
- [x] README includes Azure architecture and deployment instructions
- [x] Azure/Cosmos/identity/GHCR ADR trade-offs are documented
- [x] Rubric is updated truthfully

Phase 4 live evidence: public Linux/amd64 images use immutable tag `phase4-9350f17348ab`; the
recovery plan and apply changed only the two Container Apps (`0 added, 2 changed, 0 destroyed`),
and the post-apply plan had zero drift. Both HTTPS applications became healthy. The cloud smoke
created and resolved code `qXJLudH2`, preserved correlation IDs, and returned the expected `404`.
The mapping survived a shortener revision restart, and managed-identity reads after resolver and
shortener restarts directly showed the mapping plus three redirect events in their separately
scoped Cosmos containers. The deployment-script item remains open because recovery was performed
as reviewed staged commands rather than one uninterrupted script run.

## Phase 5 definition of done

- [x] Log Analytics workspace exists via Terraform
- [x] Container Apps stdout logs reach Log Analytics
- [x] Application Insights exists via Terraform and is workspace based
- [x] Application Insights local authentication is disabled
- [x] Both service identities have Application Insights-scoped telemetry publication RBAC
- [x] No telemetry client secret or API key exists in application configuration
- [x] Azure and local OTLP backends are explicit and mutually exclusive
- [x] Prometheus remains available with every telemetry backend
- [x] Deployed shortener and resolver traces reach Azure
- [x] One real distributed trace contains resolver SERVER, resolver CLIENT, and shortener SERVER spans
- [x] Production JSON logs retain the same correlation and trace IDs
- [x] RED request and duration metrics are visible from both deployed services
- [x] RED error metric semantics and lazy-series behaviour are directly validated
- [x] Azure custom metric aggregation fields and bounded dimensions are documented
- [x] Terraform-managed production workbook exists with six validated query panels
- [x] Terraform-managed server-error alert exists and is enabled
- [x] Local OTel Collector, Prometheus, structured logs, and trace workflow remain green
- [x] New immutable public Linux/amd64 GHCR images are deployed
- [x] Live Azure health, readiness, create, resolve, correlation, and unknown-code smoke passes
- [x] Terraform safety validation passes and post-apply plan has no drift
- [x] README, AGENTS guidance, rubric, KQL, and text evidence are updated
- [ ] Real trace screenshot saved
- [ ] Real workbook/dashboard screenshot saved
- [ ] Real structured-log screenshot saved

Phase 5 live evidence: public Linux/amd64 images use immutable tag `phase5-7b3b526275b4`.
Terraform's complete change set was six additions and three in-place updates with zero destroys;
the workbook-only recovery added one resource after lowercasing the provider-required source ID,
and the final plan reported no changes across 19 resources. Correlation ID
`azure-smoke-ef8c5d5a-80cb-4a90-bf7b-1290ea79ebfb` maps from parsed logs to Application Insights
operation ID `aa0c88bbd5e263bc7688bdffdc05ca86`. Queryable text evidence is stored in `evidence/`.
All three screenshot items remain open until a human saves authenticated portal captures.
