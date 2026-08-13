# Phase 5 live validation

Validated 14 August 2026 against the Australia East deployment.

- Correlation ID: `azure-smoke-ef8c5d5a-80cb-4a90-bf7b-1290ea79ebfb`
- Resolver distributed trace ID: `aa0c88bbd5e263bc7688bdffdc05ca86`
- Short code: `WBAL5w57`
- Active revisions: `ous-shortener-qafji9--0000002`,
  `ous-resolver-qafji9--0000002`

## Distributed trace result

| Type | Service | Operation | Span ID | Parent span ID | Status |
| --- | --- | --- | --- | --- | --- |
| request | resolver | `GET /{code}` | `7f1d507876d17716` | trace root | 302 |
| dependency | resolver | shortener internal lookup | `ee44e32a578c97fe` | `7f1d507876d17716` | 200 |
| request | shortener | `GET /internal/v1/urls/{code}` | `ff9a1edee4478588` | `ee44e32a578c97fe` | 200 |

All rows have Application Insights operation ID `aa0c88bbd5e263bc7688bdffdc05ca86`.
The resolver and shortener JSON completion logs use the same trace ID and their respective
SERVER span IDs above.

## Representative parsed structured logs

```json
{"timestamp":"2026-08-13T17:46:47.576Z","service":"shortener","event":"http_request_completed","correlation_id":"azure-smoke-ef8c5d5a-80cb-4a90-bf7b-1290ea79ebfb","trace_id":"aa0c88bbd5e263bc7688bdffdc05ca86","span_id":"ff9a1edee4478588","status_code":200,"revision":"ous-shortener-qafji9--0000002"}
{"timestamp":"2026-08-13T17:46:47.672Z","service":"resolver","event":"http_request_completed","correlation_id":"azure-smoke-ef8c5d5a-80cb-4a90-bf7b-1290ea79ebfb","trace_id":"aa0c88bbd5e263bc7688bdffdc05ca86","span_id":"7f1d507876d17716","status_code":302,"revision":"ous-resolver-qafji9--0000002"}
```

These rows came from `ContainerAppConsoleLogs_CL` after parsing `Log_s`. The full validated query
is in `queries/correlated-logs.kql`.

## Azure custom metric representation

The Application Insights `customMetrics` table exposed:

- `valueSum`: request count or total observed duration;
- `valueCount`: exported sample count;
- `valueMin` / `valueMax`: minimum/maximum for the aggregation;
- `customDimensions`: bounded method, route template, and status dimensions;
- `cloud_RoleName`: `shortener` or `resolver` from `service.name`.

Both services produced `url_shortener.http.server.requests` and
`url_shortener.http.server.request.duration`. No `url_shortener.http.server.errors` row existed,
which is the expected lazy-series result because evidence traffic produced no response >=500.
HTTP 404s appeared on the request counter and did not create an error series. Azure flattens the
duration histogram to aggregate fields, so the workbook uses correctly supported average and
maximum seconds rather than claiming p95.

## Infrastructure observations

- Log Analytics: `log-ous-qafji9`, workspace ID
  `b855fb3d-374b-4f60-9bd7-9ea957130801`, PerGB2018, 30-day retention, 1 GB/day cap.
- Application Insights: `appi-ous-qafji9`, app ID
  `fdff7ae5-a823-4e08-addf-49c02f17b0b0`, workspace based, 100% sampling,
  1 GB/day cap, local authentication disabled.
- Workbook: `240e782f-c524-50c4-bb40-8b10d7c0aa4c`, seven items including six query panels.
- Alert: `alert-ous-server-errors-qafji9`, enabled, severity 2, five-minute evaluation/window,
  threshold `TotalErrors > 0`.
- Post-apply Terraform plan: no changes; the 19-resource safety validation passed.

Portal screenshots are intentionally outstanding; see `README.md` in this directory.
