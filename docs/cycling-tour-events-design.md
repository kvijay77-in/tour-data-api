# Cycling Tour Events Engine Design

This document is the solution design for the generic tour event engine that is shared across the backend (`tour-data-api`), organiser app (`tour-mgmt-app`), and rider app (`tour-rider-app`). It is intentionally written to be implementation-ready for a future engineering handoff while remaining configuration-driven and free of hardcoded event names, activity names, and activity ordering.

## 1. Design goals

The goals of the event engine are:

- support QR-based non-check-in activities during a tour without creating one-off code paths
- keep the event model consistent with the existing Ride / CheckIn pattern already used by the backend
- allow both tour organisers and riders to work from the same event definitions and occurrence metadata
- let the first rollout ship as seed configuration only, without code-level event-specific branching
- support baggage handling, hotel allocation, and rider exit / baggage exit orchestration in a frictionless way

## 2. Scope and system boundaries

The system is bounded by the current tour-data-api conventions and the AppConfig / RBAC patterns already used across the repo:

- platform-level shared config remains in `AppConfig`
- tour-specific operational data remains in per-tour DynamoDB tables
- API responses continue to use the repository standard success/error envelope
- Cognito roles remain mapped to API permissions through RBAC, not by hardcoded group names inside Lambda code
- QR-based ID Code handling remains based on the existing `ID_CODE_FORMAT`, `ID_CODE_TYPE`, and `personalCode` pattern

This design therefore augments the current Tour Data API rather than replacing it.

## 3. Table strategy and provisioning update

### 3.1 Shared and tour-specific tables

The existing hybrid strategy remains unchanged.

| Layer | Table | Purpose |
|---|---|---|
| Shared | `RiderProfile` | Rider master profile data, tour-agnostic |
| Shared | `RiderTours` | Rider participation lifecycle by `profileId + tourId` |
| Shared | `RiderCognitoUser` | Rider Cognito identity mapping |
| Shared | `TourMaster` | Tour registry |
| Shared | `AppConfig` | Shared app configuration |
| Tour-specific | `TourRider-{tourId}` | Tour rider lifecycle and operational state |
| Tour-specific | `Ride-{tourId}` | Ride definitions and ride schedule |
| Tour-specific | `CheckIn-{tourId}` | Ride-level check-in records |
| Tour-specific | `User-{tourId}` | Tour staff and user assignments |
| Tour-specific | `Notification-{tourId}` | Rider notifications |
| Tour-specific | `Artifacts-{tourId}` | S3-backed artifact metadata |
| Tour-specific | `Event-{tourId}` | Event definitions and event occurrences |
| Tour-specific | `EventActivityRecord-{tourId}` | Scan-level event activity records |
| Tour-specific | `Hotel-{tourId}` | Hotel master catalog |
| Tour-specific | `HotelStay-{tourId}` | Per-night rider hotel allocations |

This means the runtime provisioned table count is no longer six. It is now ten table types for each live tour.

### 3.2 Provisioning behaviour

The idempotent repair endpoint remains the authoritative mechanism for adding new tour-specific tables to a live tour:

- `PUT /v1/tours/{tourId}/provision`

This endpoint must create any missing table types for the tour without modifying `TourMaster`, including `provisionedAt`. That is required for live tours already created before the event engine was introduced.

The provisioning design matches the repository's existing conventions:

- create tour tables at tour provisioning time when the tour is first provisioned
- add missing or newly introduced tables through the repair endpoint for already active tours
- maintain the same shared provisioning logic in `src/layers/common/tour_provisioning.py`
- keep tables isolated by tour in a single DynamoDB table per data domain

## 4. Event / Occurrence / Activity model

The event model mirrors the repository's existing Ride / CheckIn pattern:

- `Event` = the definition/template
- `EventOccurrence` = one actual instance on a date
- `EventActivityRecord` = one scan captured against an occurrence and activity

### 4.1 Why `Event-{tourId}` holds both definition and occurrences

The design stores both the event definition and the event occurrences in the same `Event-{tourId}` table with a single partition key:

- `PK = eventId`
- `SK = DEF` for the template row
- `SK = OCC#{date}#{seq}` for occurrence rows

This is the preferred key choice because:

- definition and occurrence data are logically one family of records for a single event
- a single query can fetch the template and the active occurrences in one table and one partition
- it stays consistent with the ride model, where a ride definition and its daily instances are naturally co-located
- it simplifies list queries such as "show all occurrences for event X on this date" without cross-table joins
- it keeps the event engine generic without introducing extra table sharding or specialized indexes for one configuration model

### 4.2 Event definition contract

The `DEF` row holds the stable template for an event type and is configuration-driven.

| Field | Type | Meaning |
|---|---|---|
| `eventId` | String | Stable event identifier |
| `eventName` | String | User-facing label such as "Day 0 Registration" |
| `eventType` | String | `SINGLE` or `REPEATING` |
| `location` | String | Where the event takes place |
| `sequenceEnforced` | Boolean | Whether activities must be completed in order |
| `defaultScanType` | String | Default ID Code type for the event |
| `allowSelfService` | Boolean | Whether riders can self-mark activity progress |
| `activities` | List | Ordered list of activity definitions |
| `createdAt` | String | ISO UTC timestamp |
| `updatedAt` | String | ISO UTC timestamp |

### 4.3 Event occurrence contract

Each `OCC` row describes one actual event instance on a date.

| Field | Type | Meaning |
|---|---|---|
| `eventId` | String | Parent event definition |
| `occurrenceId` | String | Logical occurrence key derived from eventId + date + seq |
| `date` | String | Event date in `YYYY-MM-DD` |
| `seq` | Number | Same-day repeat number, used like `rideNo` + `date` |
| `status` | String | `PLANNED`, `ACTIVE`, `COMPLETED` |
| `startedAt` | String | Optional ISO timestamp |
| `completedAt` | String | Optional ISO timestamp |
| `disabledActivityIds` | List | Per-occurrence activity disable overrides |
| `allowSelfService` | Boolean | Default self-service permission inherited from the event definition |
| `selfServiceEnabled` | Boolean | Live per-occurrence flag that overrides the inherited definition setting for this occurrence |
| `linkedOccurrenceRef` | String | Optional match to paired loading/unloading occurrence |
| `createdAt` | String | ISO UTC timestamp |
| `updatedAt` | String | ISO UTC timestamp |

The `seq` attribute is important for same-day repeats: it distinguishes multiple occurrences on the same date exactly the same way `rideNo` + `date` works in the existing ride model.

### 4.4 Event activity definition contract

Each event activity is configuration-driven and must support generic sequencing and variant handling.

| Field | Type | Meaning |
|---|---|---|
| `activityId` | String | Stable activity ID |
| `name` | String | User-visible name |
| `sequenceNo` | Number | Order within the event |
| `enabled` | Boolean | Availability for this event |
| `mandatory` | Boolean | Must be completed before occurrence close |
| `scanType` | String | Allowed ID Code type(s) for the activity |
| `allowOptOut` | Boolean | Rider may opt out of the activity |
| `prerequisiteActivityIds` | List | Activities that must be completed first |
| `restrictToAssignedUsers` | Boolean | Defaults to `true` when not explicitly `false` |
| `variantOptions` | List | Optional variant definitions such as VEG / NON_VEG |
| `notes` | String | User or staff instructions |

There is no `activityGroup` attribute. The event identity already implies origin vs destination and therefore the activity grouping is derived from event configuration instead of a separate field.

## 5. Seed events and business rules

### 5.1 Seed configuration only

The first rollout ships with seed configuration only. No event or activity names are hardcoded anywhere in code.

The three seeded event definitions are:

| Event | Type | Activities | Location |
|---|---|---|---|
| Day 0 Registration | Single occurrence | ID Card collection → Indemnity Agreement signing → Jersey collection → Nutri-Pack collection → Goodies Bag collection | Tour start venue |
| Baggage Loading | Repeating | Room pickup → Handover for loading → Loaded to truck | Origin hotel |
| Baggage Unloading | Repeating | Unloaded from truck → Sent to room → Dropped at room | Destination hotel |

The split between baggage loading and baggage unloading is intentional because they are independent operational flows with different staffing and lifecycle controls. They share a common baggage identity but are distinct event definitions.

### 5.2 Sequence enforcement and mandatory handling

The event-level `sequenceEnforced` flag determines whether a rider must complete activities in order or can use a random-order queue across counters.

Mandatory activities never block a single scan; they block occurrence completion. That means the dashboard can list riders with outstanding mandatory activities without preventing individual scans from being recorded.

For crowd management scenarios, sequence enforcement may be disabled while `prerequisiteActivityIds` can still be configured on a per-activity basis to control logically required ordering where needed.

## 6. Event scan and QR handling

### 6.1 QR / ID Code re-use

The event engine must reuse the existing QR ID Code resolution model rather than creating a new baggage ID entity.

The accepted baggage ID Code pattern is:

- position 1 is the type code
- positions 2–5 are the rider's own `personalCode`

Type code mapping:

- `1` = RIDER
- `2` = CYCLE
- `3`–`8` = BAGGAGE types

This means a baggage scan resolves to a rider by looking up the rider's `personalCode` in the existing rider profile / tour rider mapping. The bag type is carried in the leading type code and does not require an additional baggage allocation table.

### 6.2 Frontend contract change

In `tour-mgmt-app`, `resolveScannedRiderId()` currently hard-blocks every non-RIDER type. The generalised implementation accepts a caller-supplied set of allowed ID Code types and returns:

```ts
{ riderId, typeCode, bagLabel }
```

Existing check-in callers must continue passing only `[RIDER]` so the current behaviour and the exact existing error messages remain unchanged. The wrong-bag-type error message for an event using a baggage scan must now be explicit about the disallowed type and the allowed types for the event.

This keeps all existing ride check-in flows stable while enabling event-driven baggage scanning without a new QR parsing subsystem.

### 6.3 Baggage reconciliation model

The rider's expected bag set is derived from bags scanned at the first loading activity of the tour. This means reconciliation works without a pre-registration or baggage assignment step. The system compares the bag set expected from the first loading occurrence against the bag set observed at unloading and can surface missing baggage records as a reconciled exception list.

This design is exactly aligned with the operational requirement that the dashboard can answer: "96 loaded vs 94 unloaded — here are the 2 missing bags." It is implemented as a two-query comparison on the dashboard using the `linkedOccurrenceRef` pair between a day-N loading occurrence and the matching day-N unloading occurrence.

## 7. Rider exit vs baggage exit

A rider can exit the tour while their baggage remains with the organisers and is returned later. This is a distinct lifecycle and must stay separate from rider participation status.

### 7.1 Rider status model

The existing `TourRider-{tourId}` lifecycle remains unchanged:

- `status` continues to capture rider participation
- `EXITED` remains implemented with `prevStatus`, `exitedAt`, `exitedBy`
- cancellation of exit still restores `status` from `prevStatus`

### 7.2 Baggage status model

A separate `baggageStatus` field is added to the rider row with values:

- `ACTIVE`
- `RETAINED`
- `RELEASED`

The following audit fields are used for baggage lifecycle tracking:

- `baggageExitedAt`
- `baggageExitedBy`
- `baggageReleasedAt`
- `baggageReleasedBy`
- `baggageExitNote`

### 7.3 Enforcement matrix

| Rider status | baggageStatus | Baggage scan outcome |
|---|---|---|
| Active | ACTIVE | Allowed |
| EXITED | RETAINED | Allowed |
| EXITED | RELEASED | Blocked — `BAGGAGE_NOT_IN_TOUR` |
| Any | RELEASED | Blocked — `BAGGAGE_NOT_IN_TOUR` |

The `EXITED + RELEASED` row is intentionally shown explicitly for operator clarity, even though it is functionally the same as the general `Any + RELEASED` row. This makes the rider-exit workflow obvious to staff while still enforcing the same anti-fraud rule at all times.

This is a fraud-prevention rule. Once baggage has been released, it cannot be re-presented as additional baggage under the same rider identity. The block message must identify the rider name and the release date so counter staff understand why the bag is being rejected and can escalate rather than retrying.

### 7.4 Offline and sync behaviour

The baggage status is included in the app's post-sign-in bootstrap payload so the block works offline. When the client later syncs, a scan for a `RELEASED` rider is accepted but flagged when the client `timestamp` is earlier than `baggageReleasedAt` (matching the existing late-sync rule). If the timestamp is not earlier, the scan is rejected. Flagged records surface on the dashboard as exceptions.

### 7.5 Final-day handover

Final-day handover of retained bags is a normal Baggage Unloading occurrence. Once the organiser confirms the handover, `baggageStatus` is set to `RELEASED` and the loop closes. Cancelling a rider exit must restore the previous baggage state in a coherent and auditable way.

## 8. Hotel model and hotel allocation flow

### 8.1 Hotel master

`Hotel-{tourId}` is a tour-specific table and is deliberately not stored in AppConfig because it is operational tour data and not shared app configuration.

`Hotel-{tourId}` schema:

| Field | Type | Meaning |
|---|---|---|
| `hotelId` | String | Stable hotel identifier |
| `name` | String | Hotel name |
| `city` | String | City |
| `address` | String | Full address |
| `contact` | String | Contact information |
| `notes` | String | Notes / operational information |

### 8.2 HotelStay model

`HotelStay-{tourId}` is keyed by stay date and rider, not by a rider/date range model.

| Field | Type | Meaning |
|---|---|---|
| `stayDate` | String | `YYYY-MM-DD` (PK) |
| `riderId` | String | Rider ID (SK) |
| `hotelId` | String | Hotel reference |
| `roomNo` | String | Room number |
| `sharingWith` | String | Co-occupant rider ID for a two-person room pairing (single rider ID only) |
| `checkInDate` | String | Optional check-in date |
| `checkOutDate` | String | Optional check-out date |
| `source` | String | `UPLOAD` or `MANUAL` |
| audit fields | String | Creation / update metadata |

This shape is chosen because it is the fastest solution for a very common operational query: "who is staying where tonight?" It also supports room-wise delivery queries and correctly handles mid-stay room changes, which are awkward in a date-range model that is keyed by rider or hotel over an interval. The current design assumes a two-person room pairing (`sharingWith` is a single rider ID); room sharing validation therefore checks reciprocal pairing and does not model larger shared rooms in this scope.

### 8.3 CSV upload pattern

Hotel allocation upload uses the same S3 presigned upload pattern as other artifact workflows.

- presigned PUT to `tours/{tourId}/uploads/hotel-allocation/{uploadId}.csv`
- S3 event triggers a processing Lambda
- validation results are stored to upload-status metadata
- list clients poll for status until processing completes
- files remain stored for audit and verification

The file is expanded by the processor instead of requiring users to repeat rows per day. Header comments describe the stay dates and optional default hotel:

```csv
# stayDates=2026-02-11,2026-02-12,2026-02-13
# hotelId=HTL-MDU-01
riderId,hotelId,roomNo,sharingWith
R1,HTL-MDU-01,204,R2
R2,HTL-MDU-01,204,R1
R57,HTL-MDU-02,311,
```

Alternative input format:

```csv
# startDate=2026-02-11
# nights=3
# hotelId=HTL-MDU-01
riderId,roomNo
R1,204
R2,204
```

When a default hotel is provided, single-hotel days only require the rider and room number. Re-uploading for a day must replace the previous rows for that date idempotently.

Row-level errors must be reported against the original source row number so the organiser can map the issue directly back to the CSV. Manual adjustments are only single-night edits and do not modify the broader allocation set.

Manual allocation screens must show rider profile data as read-only only. The rider profile must never be editable from the hotel allocation screen.

## 9. RBAC and permission model

The RBAC model remains API-level and group-agnostic. The new permissions are:

- `EVENT_MANAGE` — `ADMINISTRATOR` only
- `EVENT_SCAN` — `ADMINISTRATOR`, `SUPER_USER`, `PS_<n>_USER`

This follows the existing pattern in `src/layers/common/rbac.py` and ensures Cognito group names can change without requiring Lambda code changes.

The design intent is deliberate:

- event definitions and occurrence management are administrator-only
- event scanning is allowed to staff and pit stop operators serving the flow
- no permission should be coupled to an event-specific hardcoded name or list in backend code

## 10. Operational implications by team

### 10.1 `tour-data-api`

The backend owns:

- event definition and occurrence storage in `Event-{tourId}`
- scan-level records in `EventActivityRecord-{tourId}`
- rider baggage status updates in `TourRider-{tourId}`
- hotel and hotel-stay tables and item updates
- generic event-query and reconciliation endpoints
- provisioning logic extension for the new tables

### 10.2 `tour-mgmt-app`

The organiser app owns:

- event definition screens and occurrence creation / start / completion flows
- baggage reconciliation dashboards and exception reporting
- hotel allocation upload, validation, and manual adjustment screens
- rider exit + baggage exit controls and confirmation workflows
- QR ID Code resolution via the generalised `resolveScannedRiderId()` contract

### 10.3 `tour-rider-app`

The rider app remains focused on rider self-service where appropriate:

- rider self-service toggles for activities
- event status visibility from their own perspective
- offline-safe behaviour for baggage and event activity state
- the ability to surface the rider's own baggage and event status without requiring a new baggage identity model

## 11. Design summary

This is a general-purpose events engine built on the same patterns already used by the tour platform:

- generic definitions and activity configuration
- event and occurrence data stored in the same table family
- QR scanning reusing the existing ID Code and `personalCode` mechanism
- baggage lifecycle separate from rider lifecycle
- hotel allocation keyed by stay date and rider for operational simplicity
- RBAC permission model kept abstract and future-proof

The initial release is intentionally seed-config-driven and includes only the agreed event flows: Day 0 Registration, Baggage Loading, and Baggage Unloading.
