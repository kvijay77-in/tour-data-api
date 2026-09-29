# Dashboard Backend API Change Request
_Last updated: 2026-09-29_

> Historical / Implemented – kept for reference. Current source of truth: [Dashboard API design](../design/dashboard-api.md) and the [API reference](../design/api-reference.md#check-ins).

## Status

Obsolete. This change request is no longer applicable.

The previous proposal to enrich dashboard check-ins with Cognito display names has been withdrawn due to payload repetition and repeated Cognito lookups on frequent dashboard refresh calls.

Replacement approach:
- Keep dashboard progress payload lean without server-side name enrichment.
- Use a dedicated read-only API from frontend to fetch user mapping once and cache it:
  - `GET /v1/users/cognito`
  - Response includes only `sub` and `name` attributes.
