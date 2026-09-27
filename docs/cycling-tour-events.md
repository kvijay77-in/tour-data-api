# Cycling Tour Events Change Requirement Document

Date: 2026-08-30

[Backend Design](cycling-tour-events-design.md) · [Frontend Design](cycling-tour-events-frontend-design.md)

This is the frozen change requirement implemented by the two design documents above. Where this document and a design document could be read as disagreeing, the design documents are authoritative for implementation detail; this document remains authoritative for the agreed business requirement.

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
- `EventOccurrence-{tourId}`
- `EventActivityLogs-{tourId}`
- `RoomAllocation-{tourId}`
- `Hotel-{tourId}`

These must be included in `PUT /v1/tours/{tourId}/provision` idempotent repair provisioning and must be creatable on existing live tours without altering `provisionedAt`.

The total number of tour-specific tables is no longer six. The existing runtime set remains the current base set (TourRider, Ride, CheckIn, User, Notification, Artifacts), and the new event and hotel tables extend that base to **eleven** table types in total.

### 2. Event / Occurrence / Activity model

The system will support three levels of data:

- `Event`: definition/template, analogous to a ride plan
- `EventOccurrence`: a concrete instance on a date, analogous to a ride
- `EventActivityLogs`: a single scan / event activity record, analogous to a check-in

The event definition and its occurrences are stored in **two separate tables**, `Event-{tourId}` (`PK = eventId`) and `EventOccurrence-{tourId}` (`PK = eventId`, `SK = occurrenceId`). This split is required because definition management (`EVENT_MANAGE`, ADMINISTRATOR only) and occurrence management (`EVENT_OCCURRENCE_MANAGE`, ADMINISTRATOR and SUPER_USER) are separately authorised, and a shared partition would force authorisation logic to inspect the sort key. See the [Backend Design](cycling-tour-events-design.md) design decision register (§2, D1) for the full rationale. `activities` remain an embedded list on the `Event` definition item, exactly as `stages` is embedded on `Ride-{tourId}` (see backend design §5.1/§4.4).

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
- `allowedTypeCodes` (list of `AppConfig` `ID_CODE_TYPE` codes this activity accepts; not a hardcoded RIDER/BAGGAGE flag — see below)
- `allowOptOut`
- `prerequisiteActivityIds`
- `restrictToAssignedUsers`
- variant handling support (for example, Nutri-Pack VEG / NON_VEG)

`sequenceEnforced` is configured at the event level and can be turned off for crowd management. Per-activity prerequisite lists remain supported. `mandatory` activities do not block a single scan, but they do block occurrence completion until all mandatory activities are complete.

The scan type accepted by an activity is not a fixed RIDER-or-BAGGAGE choice. Instead, each activity (and the event as a whole, via a `defaultAllowedTypeCodes` fallback) declares the set of `AppConfig` `ID_CODE_TYPE` codes it accepts, for example `allowedTypeCodes: ["1"]` for a rider-only activity, or a narrowed `["3","4","5"]` for an activity restricted to a subset of baggage types. This keeps the type set entirely configuration-driven, consistent with the rest of this engine's no-hardcoding requirement.

### 4a. Occurrence-level activity adjustments

Individual activities must be adjustable per occurrence, not only at the event-definition level, because some decisions are made on the day and should not require editing the shared definition. For example, baggage loading may need to run in self-service drop-off mode for a single day only, decided at short notice because a hotel is short-staffed. The design must therefore support, per occurrence and per activity: enabling/disabling the activity, overriding self-service mode, and narrowing the allowed type codes, together with an optional note recording the reason for the day-specific decision. Both the data model and the API must expose reading and updating these overrides independently of editing the event definition itself.

### 5. QR / ID Code handling

QR scanning must reuse the existing ID Code mechanism. There is no new baggage ID entity, no baggage allocation process, and no `baggageCount` field.

For baggage QR payloads, the scanned 5-character ID Code uses the rider's existing `personalCode` as the rider key. The leading type code identifies the baggage category. Type codes `3`–`8` are reserved for baggage types while `1` is RIDER and `2` is CYCLE.

The backend API and frontend apps must therefore resolve a baggage scan to the rider via the existing `personalCode → riderId` mapping, with `typeCode` used to identify the bag type.

The `tour-mgmt-app` change is required in `resolveScannedRiderId()` so that callers can supply a set of allowed ID Code types and receive `{ riderId, typeCode, bagLabel }` while existing check-in callers continue to pass only `[RIDER]` and preserve the exact current behaviour and error messages. The wrong-bag-type error message must explicitly call out that the scanned type is not allowed for this event.

### 6. Rider exit vs. baggage exit

A rider may exit the tour while their baggage remains with the organisers and is returned later. These are separate lifecycles.

`TourRider-{tourId}` must continue to use the existing `status=EXITED` flow, including `prevStatus`, `exitedAt`, and `exitedBy`.

A separate `baggageStatus` must be added with a clear, distinct status set:

- `ACTIVE` — baggage is in normal organiser custody, tour in progress
- `RETAINED` — rider has exited the tour, but baggage stays in organiser custody (for example, delivered on the final day)
- `WITH_RIDER` — baggage is with the rider and is no longer in organiser custody, whether the rider took it on exit or collected it early (for example, at final checkout)

The prior candidate name `RELEASED` is rejected as ambiguous, since it does not state *who* holds the bag next; `WITH_RIDER` states the custody transfer explicitly. While `baggageStatus=WITH_RIDER`, no other baggage-lifecycle metadata is meaningful for that rider — loading/unloading records, hotel assignment, and further audit fields do not apply once the bag has left organiser custody, so the API must not require or expect the app to populate any additional baggage field in that state.

The following baggage exit audit fields apply only while baggage remains in organiser custody (`ACTIVE`→`RETAINED`, and `RETAINED`→`WITH_RIDER` on eventual release):

- `baggageExitedAt`
- `baggageExitedBy`
- `baggageReleasedAt`
- `baggageReleasedBy`
- `baggageExitNote`

When a rider is exited, the organiser must explicitly choose baggage disposition (`RETAINED` or `WITH_RIDER`). The exit API must return a validation error if no choice is supplied. The enforcement matrix — the fraud-prevention rule required for this change — is:

| Rider status | baggageStatus | Baggage scan outcome |
|---|---|---|
| Active | ACTIVE | Allowed |
| EXITED | RETAINED | Allowed (bags legitimately still in transit) |
| EXITED | WITH_RIDER | Blocked — `BAGGAGE_NOT_IN_TOUR` |
| Any | WITH_RIDER | Blocked — `BAGGAGE_NOT_IN_TOUR` |

The `EXITED + WITH_RIDER` row is explicit for operator clarity; it is functionally the same rule as the general `Any + WITH_RIDER` row but is intentionally listed so the staff workflow remains obvious during rider-exit processing. The rule applies whenever baggage is no longer in organiser custody, not only at rider-exit time: a tag that has been handed back cannot subsequently be re-presented and scanned as if it were still in transit.

The block message must include the rider name and release date so staff understand the reason and escalate rather than retry. The block must work offline from the post-sign-in bootstrap payload and, on sync, a scan for a `WITH_RIDER` rider is accepted-but-flagged when the client timestamp is before `baggageReleasedAt`; otherwise it is rejected.

Final-day handover of retained bags is recorded as a normal Baggage Unloading occurrence. After the organiser confirms the handover, `baggageStatus` is set to `WITH_RIDER` and the loop closes. Cancelling a rider exit must return `baggageStatus` to a coherent previous value.

### 7. Hotel model

Hotel data must be stored in `Hotel-{tourId}` and not in AppConfig because it is tour data rather than shared app configuration.

`Hotel-{tourId}` attributes:

- `hotelId`
- `name`
- `city`
- `address`
- `contact`
- `notes`

`RoomAllocation-{tourId}` is keyed as:

- `PK = stayDate` (`YYYY-MM-DD`)
- `SK = riderId`

Attributes include:

- `hotelId`
- `roomNo`
- `roomCapacity` (defaults to `2`; may be `3` to support triple sharing)
- `sharingWith` (list of rider IDs, e.g. `["R2","R3"]`; must support both twin (2-person) and triple (3-person) room sharing, not only a single co-occupant)
- `checkInDate`
- `checkOutDate`
- `source` (`UPLOAD` | `MANUAL`)
- audit fields

Reciprocity and room-capacity validation are enforced at write time, identically for manual adjustment and CSV apply: every rider named in a `sharingWith` list must name the other sharers back on their own record, all sharers for a given room/date must agree on `hotelId`/`roomNo`/`roomCapacity`, and the sharing-group size must never exceed `roomCapacity`.

This design is intentionally one item per rider per night because it supports fast queries for "who is where tonight", room-wise delivery, and mid-stay room changes without the pain of a date-range model. Multi-night stays in the same city are represented as multiple items.

### 8. Hotel allocation CSV upload (S3 + async)

Hotel allocation uploads use the same presigned URL approach as the existing artifact workflows:

- Presigned PUT to `tours/{tourId}/uploads/hotel-allocation/{uploadId}.csv`
- S3 event triggers a processing Lambda
- Row-level validation results are stored on an upload-status record
- Clients poll for upload status until completion
- Files are retained for audit and verification

The CSV format must not require the user to repeat rows per day. Instead, the file carries the allocation once and the processor expands it. Header comment lines provide stay dates and an optional default hotel. The `sharingWith` column supports twin or triple sharing by separating multiple rider IDs with a semicolon within the cell (commas remain the CSV field delimiter):

```csv
# stayDates=2026-02-11,2026-02-12,2026-02-13
# hotelId=HTL-MDU-01
riderId,hotelId,roomNo,roomCapacity,sharingWith
R1,HTL-MDU-01,204,2,R2
R2,HTL-MDU-01,204,2,R1
R58,HTL-MDU-01,207,3,R59;R60
R59,HTL-MDU-01,207,3,R58;R60
R60,HTL-MDU-01,207,3,R58;R59
R57,HTL-MDU-02,311,2,
```

The processor must also support `startDate + nights` as an alternative to an explicit `stayDates` list. With a default `hotelId`, a row can omit the hotel and only provide `riderId,roomNo` for single-hotel days. One source row expands into N `RoomAllocation` records. Re-upload for a date must replace that date's rows idempotently. This works per rider: each rider in the file gets their allocation for that date replaced, and riders not in the file keep theirs.

The upload apply is **strict all-or-nothing**: the entire file is validated in full before anything is written, and if any row has an issue (unknown riderId, unknown hotelId, room-capacity overflow, room clash, non-reciprocal `sharingWith`, duplicate rider for a date), the entire batch is rejected and **no partial write occurs** — including rows that individually passed validation. There is no partial-success outcome to report. Row-level errors must be reported against the source row number so users can map comments back to the original file and re-upload a corrected file. Manual adjustment edits a single night only.

The manual allocation screen must show rider profile read-only fields only; rider profile fields must never be editable there.

### 9. RBAC

The following permissions are added to the existing RBAC model in the same style as `rbac.py`:

- `EVENT_MANAGE` — `ADMINISTRATOR` only (event definition create/update, reflecting the table split in §1/§2)
- `EVENT_OCCURRENCE_MANAGE` — `ADMINISTRATOR`, `SUPER_USER` (occurrence create/update/start/complete/cancel)
- `EVENT_SCAN` — `ADMINISTRATOR`, `SUPER_USER`, `PS_<n>_USER`, `HOTEL_STAFF` (the existing Cognito group, already present for check-in scanning)
- `HOTEL_ALLOC_MANAGE` — `ADMINISTRATOR`, `SUPER_USER` (hotel master data, hotel-stay adjustments, CSV upload)

These permissions are API-level and independent of frontend groups so that Cognito group names can change without code changes. No new Cognito groups are introduced. The full matrix, including the `eventAssignments` + hotel-match second authorisation layer for `EVENT_SCAN`, is defined in the [Backend Design](cycling-tour-events-design.md) §9.

## Acceptance Summary

This CR is considered agreed and frozen. The implementation shall be generic, configuration-driven, and non-hardcoded. The release seed configuration covers the agreed three event types and their associated baggage and hotel flows, while the shared data model remains extensible for future events without requiring code changes.
