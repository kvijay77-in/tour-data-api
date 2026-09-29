# Dashboard Backend API Change Request

Date: 2026-07-28

## Status

Obsolete. This change request is no longer applicable.

The previous proposal to enrich dashboard check-ins with Cognito display names has been withdrawn due to payload repetition and repeated Cognito lookups on frequent dashboard refresh calls.

Replacement approach:
- Keep dashboard progress payload lean without server-side name enrichment.
- Use a dedicated read-only API from frontend to fetch user mapping once and cache it:
  - `GET /v1/users/cognito`
  - Response includes only `sub` and `name` attributes.
