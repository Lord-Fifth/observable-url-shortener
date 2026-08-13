# Observable URL Shortener

Phase 0-1 of Assessment Part 2 implements a deliberately small two-service URL
shortener. The services communicate only through HTTP and are independently runnable and
containerised. Cloud persistence, deployment, and telemetry exporters are deferred.

## Architecture

| Service | Owns | Public contract | Internal dependency |
| --- | --- | --- | --- |
| `shortener` | URL mappings and short-code allocation | `POST /v1/urls` | None |
| `resolver` | Redirect behaviour and redirect events | `GET /{code}` | `GET /internal/v1/urls/{code}` on `shortener` |

Both services also expose `GET /healthz` and `GET /readyz`. The resolver never reads the
mapping repository directly. A successful resolution is therefore a genuine HTTP service
hop that can become one distributed trace in a later phase.

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

## Docker Compose acceptance path

With Docker Desktop running:

```powershell
docker compose up --detach --build --wait --wait-timeout 60
.\.venv\Scripts\python.exe .\scripts\smoke.py
docker compose down --remove-orphans
```

Compose publishes shortener on `localhost:8080` and resolver on `localhost:8081`. The smoke
test creates a mapping, resolves it without following the redirect, verifies `Location`, and
checks the correlation ID. The resolver's strict echo check proves that the same ID completed
the internal shortener hop.

## Architecture decisions

### ADR-001: Keep mapping ownership in the shortener

The shortener owns mapping lifecycle and storage. The resolver owns the latency-sensitive
redirect path and its event records, but looks mappings up through the internal REST contract.
This adds one network hop and couples redirect availability to the shortener; in exchange it
prevents shared-database coupling, preserves independent deployment, and creates the service
span required by the assessment.

### ADR-002: Use repository protocols with Phase 0-1 in-memory adapters

An atomic `insert_if_absent` contract makes collision handling race-safe and maps to a future
Firestore create/precondition operation. Process-local adapters keep this phase deterministic
and infrastructure-free. The trade-off is non-durable data and exactly one application worker
per service container. Firestore remains the selected deployed datastore and must be justified
and implemented in a later phase.

### ADR-003: Fail closed when redirect-event recording fails

The resolver records the redirect event before returning `302`. If recording fails, it returns
a generic `503` instead of silently losing an event. A future durable asynchronous event path
could justify fail-open behaviour, but adding one now would exceed the assessment scope.

## Phase 0-1 limits

- Each `POST` deliberately creates a new code; URL deduplication is not required.
- In-memory state is lost on restart and must run with one Uvicorn worker.
- The `/internal` route denotes ownership, not an authenticated security boundary in this phase.
- Firestore, Terraform, GCP deployment, CI, structured logging, RED metrics, OpenTelemetry,
  dashboards, alerts, and evidence artifacts are intentionally deferred.

Progress against the full assessment is tracked truthfully in `RUBRIC_CHECKLIST.md`.

