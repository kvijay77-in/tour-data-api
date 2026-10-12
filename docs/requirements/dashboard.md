# Dashboard API requirements
_Last updated: 2026-10-12_

This document is the source of truth for backend dashboard API requirements.

- Dashboard clients need an initial ride dashboard payload and a lightweight progress payload for frequent refreshes.
- The progress endpoint must avoid returning full ride and rider datasets when only check-in progress and summary values are needed.
- Rider-specific ride details are fetched on demand for the selected rider and ride.
- The ride dashboard, progress, and selected-rider detail endpoints support `ETag` and `If-None-Match`; unchanged representations return `304 Not Modified`.
- Event occurrence dashboards follow the same model as ride dashboards: a full dashboard (event definition, occurrence, riders with profile data, active activity records, cancelled records, summary) and a lightweight progress payload (records, cancelled records, summary, `dataVersion`). Both support `ETag` and `If-None-Match`.
- When an event has `registrationEnabled` set to `true`, the event dashboard lists and counts only riders registered for the occurrence; otherwise all tour riders are listed.
- Dashboard responses must enforce the dashboard permission and return only fields needed by the requested view.
- The backend API remains authoritative for ride and check-in state; client caching must not replace server authorization or validation.

See [Dashboard API design](../design/dashboard-api.md) and the [API reference](../design/api-reference.md#check-ins) and [Events](../design/api-reference.md#events).
