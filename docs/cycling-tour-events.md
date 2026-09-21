# Cycling Tour Events Change Requirement Document

Date: 2026-08-30

## Summary

This change adds a generic, configuration-driven Events engine for non-check-in activities that also use QR scanning. The scope is intentionally generic so that multiple event types can be configured without code changes, while the first release seeds only the required tour flows for registration, baggage loading, and baggage unloading.

This is a documentation-only change for the backend API, management app, and rider app design. It does not introduce any new code, table implementation, or runtime behaviour beyond the agreed design and configuration contract.

## Background

A non-competitive cycling tour already supports daily ride check-in for riders at Start, Pit Stops, and Finish. This change extends the same QR-based operational model to broader tour activities such as on-site registration, baggage handling, and hotel logistics.

The product owner has agreed that the events engine must be generic and configuration-driven, with no hardcoded event names, activity names, or activity sequences in code. The initial deployment of the engine will ship as seed configuration only; the two in-scope use cases are:

- Day 0 Registration at the tour start venue
- Baggage Loading / Unloading at origin and destination hotels

## Scope

This CR covers the shared design across three repo teams:

- `tour-data-api` (backend)
- `tour-mgmt-app` (organiser frontend)
- `tour-rider-app` (rider frontend)

The design must remain consistent with the existing API conventions, AppConfig patterns, RBAC model, and QR ID Code resolution logic already used by the tour platform.

## Change Requirement Document

### 1. New tour-specific tables

Add the following tour-specific tables to the runtime provisioning model:

- `Event-{tourId}`
- `EventActivityRecord-{tourId}`
- `HotelStay-{tourId}`
- `Hotel-{tourId}`

These must be included in `PUT /v1/tours/{tourId}/provision` idempotent repair provisioning and must be creatable on existing live tours without altering `provisionedAt`.

The total number of tour-specific tables is no longer six. The existing runtime set remains the current base set (TourRider, Ride, CheckIn, User, Notification, Artifacts), and the new event and hotel tables extend that base to ten table types in total.

### 2. Event / Occurrence / Activity model

The system will support three levels of data:

- `Event`: definition/template, analogous to a ride plan
- `EventOccurrence`: a concrete instance on a date, analogous to a ride
- `EventActivityRecord`: a single scan / event activity record, analogous to a check-in

The event template and its occurrences are stored in the same `Event-{tourId}` table, with `PK = eventId` and `SK` values discriminating the definition and each occurrence. This keeps definition and instance data together for the same event while still supporting date-based queries.

### 3. Seed events and activity sequences

The initial configuration includes three event definitions, with baggage handling split into two independent flows:

| Event | Type | Activities (in sequence) | Location |
|---|---|---|---|
| Day 0 Registration | Single occurrence | ID Card collection → Indemnity Agreement signing → Jersey collection → Nutri-Pack collection → Goodies Bag collection | Tour start venue |
| Baggage Loading | Repeating (per day) | Room pickup → Handover for loading → Loaded to truck | Origin hotel |
| Baggage Unloading | Repeating (per day) | Unloaded from truck → Sent to room → Dropped at room | Destination hotel |

The event identity implies origin vs destination and therefore there is no `activityGroup` attribute in the model.

### 4. Activity definition attributes

Activity definitions are configuration-driven and must include at minimum:

- `activityId`
- `name`
- `sequenceNo`
- `enabled`
- `mandatory`
- `scanType`
- `allowOptOut`
- `prerequisiteActivityIds`
- `restrictToAssignedUsers`
- variant handling support (for example, Nutri-Pack VEG / NON_VEG)

`sequenceEnforced` is configured at the event level and can be turned off for crowd management. Per-activity prerequisite lists remain supported. `mandatory` activities do not block a single scan, but they do block occurrence completion until all mandatory activities are complete.

### 5. QR / ID Code handling

QR scanning must reuse the existing ID Code mechanism. There is no new baggage ID entity, no baggage allocation process, and no `baggageCount` field.

For baggage QR payloads, the scanned 5-character ID Code uses the rider's existing `personalCode` as the rider key. The leading type code identifies the baggage category. Type codes `3`–`8` are reserved for baggage types while `1` is RIDER and `2` is CYCLE.

The backend API and frontend apps must therefore resolve a baggage scan to the rider via the existing `personalCode → riderId` mapping, with `typeCode` used to identify the bag type.

The `tour-mgmt-app` change is required in `resolveScannedRiderId()` so that callers can supply a set of allowed ID Code types and receive `{ riderId, typeCode, bagLabel }` while existing check-in callers continue to pass only `[RIDER]` and preserve the exact current behaviour and error messages. The wrong-bag-type error message must explicitly call out that the scanned type is not allowed for this event.

### 6. Rider exit vs. baggage exit

A rider may exit the tour while their baggage remains with the organisers and is returned later. These are separate lifecycles.

`TourRider-{tourId}` must continue to use the existing `status=EXITED` flow, including `prevStatus`, `exitedAt`, and `exitedBy`.

A separate `baggageStatus` must be added with the values:

- `ACTIVE`
- `RETAINED`
- `RELEASED`

And the following baggage exit audit fields:

- `baggageExitedAt`
- `baggageExitedBy`
- `baggageReleasedAt`
- `baggageReleasedBy`
- `baggageExitNote`

When a rider is exited, the organiser must explicitly choose baggage disposition. The exit API must return a validation error if no choice is supplied. The enforcement matrix is:

| Rider status | baggageStatus | Baggage scan outcome |
|---|---|---|
| Active | ACTIVE | Allowed |
| EXITED | RETAINED | Allowed (bags legitimately still in transit) |
| EXITED | RELEASED | Blocked — `BAGGAGE_NOT_IN_TOUR` |
| Any | RELEASED | Blocked — `BAGGAGE_NOT_IN_TOUR` |

The `EXITED + RELEASED` row is explicit for operator clarity; it is functionally the same rule as the general `Any + RELEASED` row but is intentionally listed so the staff workflow remains obvious during rider-exit processing.

The block message must include the rider name and release date so staff understand the reason and escalate rather than retry. The block must work offline from the post-sign-in bootstrap payload and, on sync, a scan for a `RELEASED` rider is accepted-but-flagged when the client timestamp is before `baggageReleasedAt`; otherwise it is rejected.

Final-day handover of retained bags is recorded as a normal Baggage Unloading occurrence. After the organiser confirms the handover, `baggageStatus` is set to `RELEASED` and the loop closes. Cancelling a rider exit must return `baggageStatus` to a coherent previous value.

### 7. Hotel model

Hotel data must be stored in `Hotel-{tourId}` and not in AppConfig because it is tour data rather than shared app configuration.

`Hotel-{tourId}` attributes:

- `hotelId`
- `name`
- `city`
- `address`
- `contact`
- `notes`

`HotelStay-{tourId}` is keyed as:

- `PK = stayDate` (`YYYY-MM-DD`)
- `SK = riderId`

Attributes include:

- `hotelId`
- `roomNo`
- `sharingWith` (single rider ID; this design supports a two-person room pairing only; multi-occupancy rooms beyond two are out of scope)
- `checkInDate`
- `checkOutDate`
- `source` (`UPLOAD` | `MANUAL`)
- audit fields

This design is intentionally one item per rider per night because it supports fast queries for "who is where tonight", room-wise delivery, and mid-stay room changes without the pain of a date-range model. Multi-night stays in the same city are represented as multiple items.

### 8. Hotel allocation CSV upload (S3 + async)

Hotel allocation uploads use the same presigned URL approach as the existing artifact workflows:

- Presigned PUT to `tours/{tourId}/uploads/hotel-allocation/{uploadId}.csv`
- S3 event triggers a processing Lambda
- Row-level validation results are stored on an upload-status record
- Clients poll for upload status until completion
- Files are retained for audit and verification

The CSV format must not require the user to repeat rows per day. Instead, the file carries the allocation once and the processor expands it. Header comment lines provide stay dates and an optional default hotel:

```csv
# stayDates=2026-02-11,2026-02-12,2026-02-13
# hotelId=HTL-MDU-01
riderId,hotelId,roomNo,sharingWith
R1,HTL-MDU-01,204,R2
R2,HTL-MDU-01,204,R1
R57,HTL-MDU-02,311,
```

The processor must also support `startDate + nights` as an alternative to an explicit `stayDates` list. With a default `hotelId`, a row can omit the hotel and only provide `riderId,roomNo` for single-hotel days. One source row expands into N `HotelStay` records. Re-upload for a date must replace that date's rows idempotently.

Row-level errors (unknown riderId, unknown hotelId, room clash, non-reciprocal `sharingWith`, duplicate rider for a date) must be reported against the source row number so users can map comments back to the original file. Manual adjustment edits a single night only.

The manual allocation screen must show rider profile read-only fields only; rider profile fields must never be editable there.

### 9. RBAC

The following permissions are added to the existing RBAC model in the same style as `rbac.py`:

- `EVENT_MANAGE` — `ADMINISTRATOR` only
- `EVENT_SCAN` — `ADMINISTRATOR`, `SUPER_USER`, `PS_<n>_USER`

These permissions are API-level and independent of frontend groups so that Cognito group names can change without code changes.

## Acceptance Summary

This CR is considered agreed and frozen. The implementation shall be generic, configuration-driven, and non-hardcoded. The release seed configuration covers the agreed three event types and their associated baggage and hotel flows, while the shared data model remains extensible for future events without requiring code changes.
