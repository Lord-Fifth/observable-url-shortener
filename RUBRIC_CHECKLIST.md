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
- [ ] Infrastructure as code
- [ ] No click-ops required for application infrastructure

### Observability

- [x] Structured logs
- [x] Correlation-ID generation
- [x] Correlation-ID propagation
- [ ] RED rate metric
- [ ] RED error metric
- [ ] RED duration metric
- [ ] RED metrics exposed
- [ ] RED metrics visible/scraped
- [ ] OpenTelemetry instrumentation
- [ ] Distributed trace spanning services
- [ ] Logs correlated with trace
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
- [ ] Deployment instructions
- [x] Service-boundary ADR
- [x] Datastore ADR
- [ ] Cloud-target ADR
- [ ] Observability ADR
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
