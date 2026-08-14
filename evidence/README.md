# Phase 5 evidence

Terraform has provisioned the production Log Analytics, Application Insights, workbook, and
alert resources. The KQL in `queries/` was validated against the live deployment on 14 August
2026. Machine-readable observations for the known request are recorded in
`phase5-validation.md`.

The authenticated Azure Portal evidence was captured on 14 August 2026 and is stored here using
the normalized filenames below:

- `phase5-distributed-trace.png` shows Application Insights end-to-end transaction details with
  the resolver request, resolver-to-shortener dependency, and shortener request in one topology.
- `phase5-distributed-trace-kql.png` shows the deployed trace KQL and its three matching rows,
  including service roles, span IDs, parent IDs, status codes, and one trace ID.
- `phase5-structured-logs.png` shows Log Analytics parsing deployed Container Apps JSON logs for
  one known correlation ID across both services, with trace/span IDs, statuses, and revisions.
- `phase5-observability-workbook-rate-errors.png` shows the Terraform-managed production workbook
  request-rate panel for both services and the expected empty server-error panel for traffic with
  no responses >=500.
- `phase5-observability-workbook-latency.png` shows the workbook's average/maximum latency panel
  and request totals split by service.

Together these files provide the required distributed-trace, dashboard/workbook, and structured
deployed-log screenshot evidence. The KQL source files remain under `queries/` for reproduction.

`phase6-validation.md` records the credential-free CI gates and uninterrupted Azure
deployment-script proof, including immutable image digests, image-only apply scope, live
smoke/durability identifiers, final zero drift, successful GitHub Actions run `31765838762`, and
independent verification of the deployable artifact and its SHA256 checksums.
