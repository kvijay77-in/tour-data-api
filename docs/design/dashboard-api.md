# Dashboard API design
_Last updated: 2026-09-29_

The dashboard API separates initial dashboard loading from frequent progress refreshes and on-demand rider detail retrieval.

## Ride dashboard

- `GET /v1/tours/{tourId}/rides/{rideId}/dashboard` returns the initial dashboard data.
- `GET /v1/tours/{tourId}/rides/{rideId}/dashboard/progress` returns the lightweight check-in progress and summary needed to refresh dashboard state without reloading the full ride and rider datasets.
- `GET /v1/tours/{tourId}/rides/{rideId}/riders/{riderId}/details` returns selected-rider details for the selected ride.

All three endpoints require the `DASHBOARD` permission. Their response fields, authorization behavior, and error contracts are defined in the [API reference](api-reference.md#check-ins); that document is authoritative for wire-level details.

The progress endpoint is deliberately separate from full dashboard loading to reduce repeated payload transfer and avoid coupling each refresh to rider profile data. Rider details are fetched only when a user requests them. The backend does not require or define persistent client-side caching of rider details.

All three ride-dashboard GET endpoints return an `ETag` and accept `If-None-Match`; a matching tag returns `304 Not Modified` with an empty body. Clients can use this conditional-request behavior to reduce repeated response transfer without treating cached data as authoritative.

## Event dashboard

Event occurrence dashboards have their own full and progress endpoints. They use the same separation between initial data and lightweight progress refresh. Their contracts are documented under [Events in the API reference](api-reference.md#events).

## Requirements

See [Dashboard API requirements](../requirements/dashboard.md). The former optimization proposal is retained as historical context in [`misc/Dashboard-API-Optimization-Proposal.md`](../misc/Dashboard-API-Optimization-Proposal.md).
