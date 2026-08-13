# Phase 5 evidence

Terraform has provisioned the production Log Analytics, Application Insights, workbook, and
alert resources. The KQL in `queries/` was validated against the live deployment on 14 August
2026. Machine-readable observations for the known request are recorded in
`phase5-validation.md`.

The three assessment screenshots still require a human authenticated Azure Portal session and
are deliberately not claimed as complete:

1. **Distributed trace:** open `appi-ous-qafji9` -> Logs, run
   `queries/distributed-trace.kql`, and use the matching request's transaction details to capture
   the resolver SERVER -> resolver dependency -> shortener SERVER topology.
2. **Dashboard:** open `appi-ous-qafji9` -> Workbooks ->
   **Observable URL Shortener - Production Observability**, select a 24-hour range, and capture
   the RED and investigation panels.
3. **Structured log:** open `log-ous-qafji9` -> Logs, run
   `queries/correlated-logs.kql`, and capture the projected service, event, correlation, trace,
   span, status, and timestamp columns.

Save real captures here only after checking that no destination URL or other sensitive value is
visible. Do not manufacture or substitute screenshots.
