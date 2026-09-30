# Events and hotel logistics
_Last updated: 2026-09-30_

The backend event engine extends ride check-ins to non-ride tour activities. It is configuration-driven: event and activity labels, ordering, scan types, optional variants, prerequisites, and occurrence-specific adjustments are data rather than hard-coded workflow branches.

## Event hierarchy

```mermaid
flowchart TD
    E[Event definition<br/>activities embedded] --> O[Event occurrence<br/>dated instance]
    O --> L[Event activity records<br/>individual scans and outcomes]
```

An event definition is stored in `Event-{tourId}`. Its ordered activities are embedded in the definition item. A dated instance is stored separately in `EventOccurrence-{tourId}`. Individual activity records are stored in `EventActivityLogs-{tourId}`. Keeping definition and occurrence records separate allows their distinct authorization and lifecycle rules to be applied consistently.

## Configuration and behavior

- Event and activity definitions are editable as tour data. Initial event definitions are not required by the backend schema; event content is configured for a tour.
- Scan types are configured through `AppConfig` `ID_CODE_TYPE` values. Event-level defaults may be narrowed by each activity's `allowedTypeCodes`.
- Event registration is optional (`registrationEnabled`, default `false`) and applies per occurrence. If disabled, every non-exited tour rider is treated as registered without a registration row. If enabled, only riders with an `EventRegistration` row for that occurrence may participate. Registration and unregistration are allowed only while the occurrence is `PLANNED`; starting the occurrence closes registration.
- Rider event self-service is an enforced permission. Effective settings resolve from event → activity → occurrence-wide override → per-activity occurrence override, with the most specific non-null setting winning. Rider registration and self-service record/cancel endpoints derive the rider identity from the authenticated Cognito profile.
- Occurrences support a self-service default and per-activity overrides for enabled state, self-service permission, allowed type codes, skip state, and an explanatory note.
- Activity records preserve the event/activity identity and scan-time details for history. Sequence, prerequisite, assignment, and allowed-type rules are enforced by the backend.
- Event dashboards expose `registrationEnabled`, `registeredCount`, and `notRegisteredCount`; rider bootstrap and progress expose the caller's registration status and the effective self-service permission for every activity.
- Event activity records use the existing rider personal-code/ID-code lookup model; a separate baggage identity is not introduced.
- Hotel master records are in `Hotel-{tourId}`. `RoomAllocation-{tourId}` stores one rider allocation per stay date, including room-sharing information.
- Hotel allocation CSV files are uploaded through a presigned S3 URL and processed asynchronously. The processor validates the entire file before applying changes; invalid files are rejected without partial allocation writes. Clients can check processing state through the upload-status API.
- Baggage custody is distinct from rider tour participation. `ACTIVE`, `RETAINED`, and `WITH_RIDER` communicate whether baggage remains with organizers; baggage scans for baggage no longer in organizer custody are rejected.

The `/v1/tours/{tourId}/events/bootstrap` endpoint supplies event-related data for client startup. This is a data-loading API and does not describe an offline capability in either client app.

## Authorization

The backend permissions are `EVENT_MANAGE`, `EVENT_OCCURRENCE_MANAGE`, `EVENT_SCAN`, `EVENT_REGISTRATION_MANAGE`, `SELF_CHECKIN`, and `HOTEL_ALLOC_MANAGE`. The exact permission-to-group mapping and additional assignment checks are defined in [RBAC](rbac.md) and enforced in `src/layers/common/rbac.py`.

## Related contracts

- API methods, request fields, responses, validation, and errors: [API reference](api-reference.md#events) and [Hotels](api-reference.md#hotels)
- Shared and tour-specific table inventory: [Data model](data-model.md)
- Notification triggers for event completion and reminders: [Notifications](notifications.md)
- Event business requirements: [Events requirements](../requirements/events.md)
