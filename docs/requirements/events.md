# Events and hotel logistics requirements
_Last updated: 2026-09-29_

This document is the source of truth for backend requirements for non-ride event activities, baggage handling, and hotel allocations.

## Event activities

- The backend must support configurable events, dated occurrences, ordered activities, and activity records without requiring code changes for new event or activity names and sequences.
- The initial use cases are tour-day registration and baggage loading/unloading.
- Each activity must be able to declare whether it is enabled, mandatory, sequence constrained, eligible for opt-out, and restricted to assigned users. It may define the accepted configured ID-code types and any variant choices or prerequisites.
- Organizers must be able to adjust applicable activity settings for an individual occurrence without changing the shared event definition.
- Event scans must resolve to the existing rider identity using configured ID-code types; the backend must not introduce a separate baggage ID or allocation identity.
- Event definition, occurrence, and scan operations must be independently authorized. See the authoritative [RBAC design](../design/rbac.md).

## Baggage custody

- Rider participation status and baggage custody status are separate lifecycles.
- Baggage is either in normal organizer custody (`ACTIVE`), retained by organizers after a rider exits (`RETAINED`), or returned to the rider (`WITH_RIDER`).
- Exiting a rider requires an explicit baggage disposition. Once baggage is `WITH_RIDER`, subsequent baggage scans are rejected.
- Retained baggage may be processed through the normal unloading flow and then marked as returned.

## Hotels and room allocation

- Hotel records are tour-specific. Room allocations are recorded per rider and stay date.
- The model must support twin and triple room sharing, with reciprocal sharing records and room-capacity validation.
- Organizers may create or adjust a single-night allocation manually or upload a CSV.
- A CSV upload must be retained for audit, validated as a complete batch, and applied only when all rows pass validation. A rejected upload must not leave partial allocation changes.
- Upload status and row-level validation errors must be available to the client.

See [Events and hotel logistics design](../design/events.md) for the data flow and [API reference](../design/api-reference.md) for the endpoint contracts.
