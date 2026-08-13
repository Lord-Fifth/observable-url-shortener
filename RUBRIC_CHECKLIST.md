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
- [ ] Durable deployed persistence

### Cloud

- [ ] Managed-cloud deployment
- [ ] Live URL OR one-command reproducible deployment
- [x] Infrastructure as code
- [ ] No click-ops required for application infrastructure

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
- [ ] Metrics correlated operationally with services/traces
- [ ] Dashboard
- [ ] Alert

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
- [ ] Deployed secrets handled correctly
- [x] No hardcoded credentials

### README

- [x] Local-run instructions
- [x] Deployment instructions
- [x] Service-boundary ADR
- [x] Datastore ADR
- [x] Cloud-target ADR
- [x] Observability ADR
- [ ] What-I-would-do-differently ADR

### Evidence

- [ ] Trace screenshot
- [ ] Dashboard screenshot
- [ ] Structured log evidence with correlation ID

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
- [ ] Resource providers registered through Terraform/provider mechanism
- [ ] Resource group created via IaC
- [ ] Cosmos account created via IaC
- [ ] Cosmos free tier directly verified in Azure
- [ ] Cosmos directly verified as non-serverless with throughput <=1000 RU/s
- [ ] Both Cosmos containers directly verified in Azure
- [ ] Shortener identity scope directly verified on `url_mappings`
- [ ] Resolver identity scope directly verified on `redirect_events`
- [x] Both images build locally
- [ ] Images pushed to GHCR
- [ ] Images anonymously pullable from GHCR
- [ ] Container Apps environment created
- [ ] Shortener Container App created
- [ ] Resolver Container App created
- [ ] Deployed minimum replicas directly verified as zero
- [ ] Both live HTTPS FQDNs exist
- [ ] Resolver cloud call directly verified through service discovery
- [ ] Shortener directly verified returning the public resolver URL
- [ ] Live health and readiness checks pass
- [ ] Live create/resolve flow passes
- [ ] Live correlation ID remains correct
- [ ] Mapping survives a deployed process lifecycle
- [ ] Redirect-event persistence directly demonstrated
- [x] Local Docker and Compose workflow remains green
- [x] Existing local OpenTelemetry workflow remains green
- [ ] Deployment script works end to end
- [x] README includes Azure architecture and deployment instructions
- [x] Azure/Cosmos/identity/GHCR ADR trade-offs are documented
- [x] Rubric is updated truthfully

Current external blocker: Docker is not authenticated to `ghcr.io`. No Azure application resources
have been applied. Terraform validation passes and the reviewed plan is 13 to add, 0 to change, 0
to destroy; cloud-only items remain unchecked until image publication and live validation succeed.
