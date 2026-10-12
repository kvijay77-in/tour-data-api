# Dashboard API design
_Last updated: 2026-10-12_

The dashboard API separates initial dashboard loading from frequent progress refreshes and on-demand rider detail retrieval.

## Ride dashboard

- `GET /v1/tours/{tourId}/rides/{rideId}/dashboard` returns the initial dashboard data.
- `GET /v1/tours/{tourId}/rides/{rideId}/dashboard/progress` returns the lightweight check-in progress and summary needed to refresh dashboard state without reloading the full ride and rider datasets.
- `GET /v1/tours/{tourId}/rides/{rideId}/riders/{riderId}/details` returns selected-rider details for the selected ride.

All three endpoints require the `DASHBOARD` permission. Their response fields, authorization behavior, and error contracts are defined in the [API reference](api-reference.md#check-ins); that document is authoritative for wire-level details.

The progress endpoint is deliberately separate from full dashboard loading to reduce repeated payload transfer and avoid coupling each refresh to rider profile data. Rider details are fetched only when a user requests them. The backend does not require or define persistent client-side caching of rider details.

All three ride-dashboard GET endpoints return an `ETag` and accept `If-None-Match`; a matching tag returns `304 Not Modified` with an empty body. Clients can use this conditional-request behavior to reduce repeated response transfer without treating cached data as authoritative.

## Event dashboard

Event occurrence dashboards mirror the ride dashboard split:

- `GET /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/dashboard` returns the event definition, occurrence, riders (with profile data and per-activity status), active `records`, `cancelled` records, and `summary`.
- `GET /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/dashboard/progress` returns `records`, `cancelled`, `summary`, and `dataVersion` only, without the event definition, occurrence, or rider profiles.

Both require `DASHBOARD`, return an `ETag`, and accept `If-None-Match` (`304 Not Modified` on a match). Rider scope follows the event definition: when `registrationEnabled` is `true` only riders registered for the occurrence are listed and counted; otherwise all tour riders are. Both endpoints share one data loader and summary builder in `event_engine.py`, so the `summary` objects are identical. Wire-level contracts are in [Events in the API reference](api-reference.md#events).

## Requirements

See [Dashboard API requirements](../requirements/dashboard.md). The former optimization proposal is retained as historical context in [`misc/Dashboard-API-Optimization-Proposal.md`](../misc/Dashboard-API-Optimization-Proposal.md).
