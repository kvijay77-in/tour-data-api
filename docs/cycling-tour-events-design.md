# Cycling Tour Events Engine Design

[← Back to Solution Design](SolutionDesign.md) · [Change Requirement](cycling-tour-events.md) · [Frontend Design](cycling-tour-events-frontend-design.md)

## 0. Document map

This design is split across two documents to keep each engineering team's contract unambiguous:

| Document | Owns | Audience |
|---|---|---|
| `docs/cycling-tour-events-design.md` (this document) | Data model, DynamoDB keys/GSIs, **all API contracts** (paths, request/response fields, enums, error codes), RBAC permissions and role mapping, provisioning, backend task list, backend test strategy | `tour-data-api` |
| `docs/cycling-tour-events-frontend-design.md` | `tour-mgmt-app` and `tour-rider-app` screens, navigation, state management, SQLite offline stores, scan resolution, frontend task lists | `tour-mgmt-app`, `tour-rider-app` |
| `docs/cycling-tour-events.md` | The frozen change requirement that both designs implement | All three teams |

**Consistency rule:** endpoint paths, request/response field names, enum values, error codes, and permission names are defined **once**, in §8 and §9 of this document. The frontend document references them by section number (for example "see backend §8.4") and never restates or redefines a value. If a value is required in a frontend screen description, it is quoted verbatim from this document, not re-invented.

This document supersedes the first-draft `cycling-tour-events-design.md` reviewed under PR #14, which was rejected for keeping the event definition and its occurrences in one table, omitting API contracts, and omitting the `tour-mgmt-app` design entirely. §1 (design decision register) records every reversal from that draft.

## 1. Introduction

### 1.1 Purpose

This is the solution design for the generic tour event engine shared across `tour-data-api` (backend), `tour-mgmt-app` (organiser app), and `tour-rider-app` (rider app). It extends the existing Ride / CheckIn QR-scanning model to non-ride activities: Day 0 registration, hotel baggage loading/unloading, and hotel room allocation logistics. It is written to be implementation-ready without further clarification.

### 1.2 Scope

In scope:

- `Event` definitions, `EventOccurrence` instances, and `EventActivityRecord` scans, as a generic, configuration-driven engine (no hardcoded event or activity names anywhere in code)
- Hotel master data and per-night rider hotel allocation, including CSV bulk upload
- Rider baggage lifecycle (`baggageStatus`) as distinct from rider participation lifecycle (`status`)
- RBAC additions: `EVENT_MANAGE`, `EVENT_OCCURRENCE_MANAGE`, `EVENT_SCAN`, `HOTEL_ALLOC_MANAGE`
- Provisioning of five new tour-specific tables
- Seeding the three agreed event definitions (Day 0 Registration, Baggage Loading, Baggage Unloading) as configuration

Out of scope:

- New Cognito groups (the existing `ADMINISTRATOR`, `SUPER_USER`, `PS_<n>_USER`, `HOTEL_STAFF`, `GUEST`, `RIDER` groups are reused)
- Multi-occupancy hotel rooms beyond a two-person pairing
- A general-purpose CSV import framework beyond the hotel allocation use case
- Any code, `template.yaml`, or test changes — this is a documentation-only change

### 1.3 Glossary additions

| Term | Meaning |
|---|---|
| Event | A definition/template for a repeatable or single-occurrence organiser activity (for example "Day 0 Registration"). Stored in `Event-{tourId}`. |
| Occurrence | One concrete, dated instance of an Event (for example "Baggage Loading, 2026-02-12"). Stored in `EventOccurrence-{tourId}`. |
| Activity | One step within an Event's definition (for example "Jersey collection"). Embedded on the `Event` item — never a standalone table. |
| Activity Record | One scan/completion of one Activity for one rider against one Occurrence. Stored in `EventActivityRecord-{tourId}`. |
| Hotel | A tour lodging location. Stored in `Hotel-{tourId}`. |
| HotelStay | One rider's room allocation for one night. Stored in `HotelStay-{tourId}`. |
| `linkedOccurrenceRef` | The pairing between a Baggage Loading occurrence and its matching Baggage Unloading occurrence, used for reconciliation. |
| `eventAssignments` | The list of Event/Occurrence assignments for a `User-{tourId}` staff member, used as a second authorisation layer beyond permissions (§9.3). |
| "Stage" is not used for events. "Activity" is the single term for a step within an Event. "Stage" continues to refer only to `Ride-{tourId}` ride stages. |

## 2. Design decision register

Every material decision is recorded here, including reversals from the rejected first draft (PR #14). Where a decision was reversed, the superseded option and the reason for reversal are given.

| # | Decision | Rationale | Superseded option (if reversed) |
|---|---|---|---|
| D1 | Split `Event` (definition) and `EventOccurrence` (instance) into **two separate tables** | Definition create/update is `EVENT_MANAGE` (ADMINISTRATOR only); occurrence management is `EVENT_OCCURRENCE_MANAGE` (ADMINISTRATOR **and** SUPER_USER). A shared partition would force every authorisation check to inspect the sort key discriminator instead of checking table identity, and the two item shapes complicate API serialisation and validation schemas. | First draft: single `Event-{tourId}` table with `SK=DEF` / `SK=OCC#{date}#{seq}` |
| D2 | `activities` is an **embedded list** on the `Event` definition item, exactly as `stages` is embedded on `Ride-{tourId}` | Matches the existing, proven pattern; activities are configuration, not independently queried entities; keeps activity ordering atomic with the definition update. | — (not previously decided; first draft left activity storage unstated, reviewer finding 2) |
| D3 | Occurrences hold only `disabledActivityIds` overrides and self-service flags, **never a copy of the activity list** | Avoids drift between the definition and stale per-occurrence copies; keeps occurrence items small. | — |
| D4 | `EventActivityRecord` denormalises `activityName` and `activityId` at scan time | Once occurrences exist, changing a definition (renaming/reordering/disabling an activity) must not retroactively alter completed records. Denormalising the name at write time preserves historical accuracy even if the definition is edited or an activity is later disabled. | — |
| D5 | Baggage is split into **two independent event definitions** (Baggage Loading, Baggage Unloading) rather than one event with an `activityGroup` field | Loading and unloading have different staffing, locations (origin vs destination hotel), and lifecycle controls (start/complete independently). The event identity itself implies direction. | Considered: one `Event` with `activityGroup=LOADING|UNLOADING` |
| D6 | **No `activityGroup` attribute** anywhere in the model | Direct consequence of D5 — grouping is derived from which `Event` an activity belongs to, not a separate field. | Considered and rejected alongside D5 |
| D7 | **No `baggageId` entity** and no baggage allocation process | The existing QR ID Code mechanism already encodes a type code (`3`–`8` = BAGGAGE) plus the rider's `personalCode`; a baggage scan resolves directly to a rider. Introducing a `baggageId` would duplicate a mechanism the app already implements (see `docs/idcode-backend-api-change-request.md`). | First conversation draft considered a derived `{riderId}-B{n}` baggage ID with a `baggageCount` field |
| D8 | `HotelStay-{tourId}` is **keyed by night** (`PK=stayDate`, `SK=riderId`), one item per rider per night | Answers "who is staying where tonight" with a single query, supports room-wise delivery queries, and handles mid-stay room or city changes (including staying multiple nights in the same city) without a date-range model. A tour that stays in the same city for 2+ nights is naturally represented as multiple `HotelStay` items with different `stayDate` values and the same `hotelId`/`roomNo`. | Considered: date-range item per rider per hotel stay |
| D9 | `Hotel-{tourId}` is a **tour-specific table**, not an `AppConfig` entry | Hotels are tour operational data (change per tour, per city, per day) rather than shared, rarely-changing app configuration. `AppConfig` is reserved for cross-tour, cross-app settings such as `ID_CODE_FORMAT`. | First draft §7.3 (superseded) had proposed storing the hotel list inside the Baggage `Event` item as configuration |
| D10 | Baggage lifecycle (`baggageStatus`) is **separate from rider exit lifecycle** (`status`) | A rider can exit the tour (`status=EXITED`) while baggage is still in organiser custody and released later. Coupling the two would block legitimate in-transit baggage handling. | — |
| D11 | Hotel allocation upload uses **S3 presigned upload + async processing**, not client-side CSV parsing with a synchronous JSON POST | Product owner requested files be retained for audit/verification, and async processing is an established pattern for row-level validation feedback. This mirrors the existing artifact upload pattern (`docs/tour-artifacts-handling-design.md`). | Considered: client parses CSV, POSTs JSON array (~100 rows) synchronously |
| D12 | `HOTEL_STAFF` is a **pre-existing Cognito group**, reused as-is | Confirmed already present in `template.yaml` Cognito groups and in `src/layers/common/rbac.py` `GROUP_PERMISSIONS`. No new group is created. | — |
| D13 | Baggage scans by hotel staff require a **second authorisation layer**: `eventAssignments` + `HotelStay` hotel-match, in addition to the `EVENT_SCAN` permission | Hotel staff at the origin hotel must not be able to scan for riders staying at a different hotel; conversely a rider's hotel differs for loading (previous night) vs unloading (current night). Permission alone cannot express this per-rider, per-night constraint. | — |
| D14 | `dietaryPreference` is added to the shared `RiderProfile` table, with self-service editing surfaced in **`tour-rider-app`** even though the CR designated it out of scope for the app | Product owner directed this be treated as an in-scope dev task for `tour-data-api`; the profile field and its API surface belong to the backend regardless of which app edits it first. | CR draft listed this as app-side "out of scope" |
| D15 | `restrictToAssignedUsers` on an activity **defaults to `true`** unless explicitly set to `false` | Product owner instruction: safer default is to require an explicit assignment; activities that are open to any authorised scanner must opt out explicitly. | First draft left the default ambiguous |
| D16 | Provisioning list grows from 6 → **11** tour-specific table types | Base 6 (`TourRider`, `Ride`, `CheckIn`, `User`, `Notification`, `Artifacts`) + 5 new (`Event`, `EventOccurrence`, `EventActivityRecord`, `Hotel`, `HotelStay`), consistent with D1's table split. | First draft (single `Event` table) totalled 10 |

## 3. Domain model and vocabulary

The event model mirrors the existing Ride / CheckIn pattern, but with definition and occurrence in separate tables per D1:

- **Event** — the definition/template, analogous to a ride plan. Stored in `Event-{tourId}`. Managed by `EVENT_MANAGE`.
- **EventOccurrence** — one concrete instance of an Event on a date (and, for same-day repeats, a sequence number), analogous to a ride. Stored in `EventOccurrence-{tourId}`. Managed by `EVENT_OCCURRENCE_MANAGE`.
- **Activity** — one step within an Event's definition, analogous to a ride stage but embedded rather than a separate table (D2). "Stage" is not used for events; "Activity" is the single term throughout both apps and the backend.
- **EventActivityRecord** — one scan/completion of one Activity for one rider within one Occurrence, analogous to a check-in. Stored in `EventActivityRecord-{tourId}`.

```
Event (definition, N activities embedded)
  └── EventOccurrence (dated instance)
        └── EventActivityRecord (one per rider per activity per occurrence)
```

## 4. Table strategy and provisioning

### 4.1 Shared and tour-specific tables

| Layer | Table | Purpose |
|---|---|---|
| Shared | `RiderProfile` | Rider master profile data, tour-agnostic (adds `dietaryPreference`, §5.6) |
| Shared | `RiderTours` | Rider participation lifecycle by `profileId + tourId` |
| Shared | `RiderCognitoUser` | Rider Cognito identity mapping |
| Shared | `TourMaster` | Tour registry |
| Shared | `AppConfig` | Shared app configuration |
| Tour-specific | `TourRider-{tourId}` | Rider lifecycle (adds `baggageStatus` + audit fields, §5.5) |
| Tour-specific | `Ride-{tourId}` | Ride definitions and schedule |
| Tour-specific | `CheckIn-{tourId}` | Ride-level check-in records |
| Tour-specific | `User-{tourId}` | Tour staff and assignments (adds `eventAssignments`, `assignedActivityIds`, `hotelId`, §5.7) |
| Tour-specific | `Notification-{tourId}` | Rider notifications |
| Tour-specific | `Artifacts-{tourId}` | S3-backed artifact metadata |
| Tour-specific | `Event-{tourId}` | Event definitions, activities embedded (§5.1) |
| Tour-specific | `EventOccurrence-{tourId}` | Event occurrences (§5.2) |
| Tour-specific | `EventActivityRecord-{tourId}` | Scan-level activity records (§5.3) |
| Tour-specific | `Hotel-{tourId}` | Hotel master catalogue (§5.4) |
| Tour-specific | `HotelStay-{tourId}` | Per-night rider hotel allocation (§5.4) |

Per D16, the tour-specific table count is now **11** (previously 6, then 10 in the rejected draft). All 5 new tables use the same naming convention as existing tour tables: `{AWS::StackName}-{TableType}-{tourId}`.

### 4.2 Provisioning behaviour

Unchanged mechanism from the existing model, extended to the 5 new table types:

- Full provisioning at tour creation time creates all 11 tour-specific tables.
- `PUT /v1/tours/{tourId}/provision` (the idempotent repair endpoint) creates any of the 5 new table types missing on an already-live tour, without modifying `TourMaster.provisionedAt`.
- Provisioning logic remains centralised in `src/layers/common/tour_provisioning.py`, adding the 5 new table definitions to the existing table-spec list.
- `scripts/provision_tour.py` (CLI/deployment method) and `POST /v1/tours` / `PUT /v1/tours` (API methods) all resolve to the same shared table-spec list, so no provisioning path can create a partial table set.

## 5. Full data model

### 5.1 `Event-{tourId}` (definition, includes embedded activities)

**Purpose:** Event definitions. One item per event type. `activities` is an embedded, ordered list — never a separate table (D2).

| Attribute | Type | Description |
|---|---|---|
| `eventId` | String | Stable event identifier (partition key). See §6 for format. |
| `eventName` | String | User-facing label, e.g. "Day 0 Registration" |
| `eventType` | String | `SINGLE` or `REPEATING` |
| `location` | String | Where the event takes place |
| `sequenceEnforced` | Boolean | Whether activities must be completed in order for a given rider |
| `defaultScanType` | String | Default ID Code type (`RIDER`, `BAGGAGE`) for activities that do not override it |
| `allowSelfService` | Boolean | Whether occurrences of this event default to self-service mode |
| `activities` | List\<Map\> | Ordered list of activity definitions (schema below) |
| `createdAt` | String | ISO 8601 UTC timestamp |
| `updatedAt` | String | ISO 8601 UTC timestamp |
| `updatedBy` | String | Cognito `sub` of the ADMINISTRATOR who last updated the definition |

**Activity object** (embedded in `activities`):

| Field | Type | Meaning |
|---|---|---|
| `activityId` | String | Stable activity ID within the event (§6) |
| `name` | String | User-visible name |
| `sequenceNo` | Number | Order within the event, 0-based |
| `enabled` | Boolean | Whether the activity is currently offered |
| `mandatory` | Boolean | Must be completed before occurrence completion; never blocks an individual scan |
| `scanType` | String | Allowed ID Code type for this activity: `RIDER` or `BAGGAGE` |
| `allowOptOut` | Boolean | Whether a rider may opt out (recorded as `outcome=OPTED_OUT`) |
| `prerequisiteActivityIds` | List\<String\> | Activities that must be completed first (used regardless of `sequenceEnforced`) |
| `restrictToAssignedUsers` | Boolean | Defaults to `true` unless explicitly `false` (D15) |
| `variantOptions` | List\<String\> | Optional variant labels, e.g. `["VEG", "NON_VEG"]` |
| `notes` | String | Staff-facing instructions |

**Indexes:** Primary Key `eventId` (partition key only). No GSI required — the event count per tour is small (3 seeded, expected to stay in single digits) and is always read by ID or via a full table scan-equivalent `Query`-free `Scan` for the definition list screen, which is acceptable given the item count.

**Item-count estimate:** 3–10 items per tour.

**Access patterns served:** "get one event definition" (direct key get); "list all event definitions" (table scan — acceptable at this volume, see §7).

**Example item:**

```json
{
  "eventId": "EVT-BAGLOAD",
  "eventName": "Baggage Loading",
  "eventType": "REPEATING",
  "location": "Origin hotel",
  "sequenceEnforced": true,
  "defaultScanType": "BAGGAGE",
  "allowSelfService": true,
  "activities": [
    {
      "activityId": "ACT-001",
      "name": "Room pickup",
      "sequenceNo": 0,
      "enabled": true,
      "mandatory": false,
      "scanType": "BAGGAGE",
      "allowOptOut": false,
      "prerequisiteActivityIds": [],
      "restrictToAssignedUsers": true,
      "variantOptions": [],
      "notes": "Bell staff collects bag from room"
    },
    {
      "activityId": "ACT-002",
      "name": "Handover for loading",
      "sequenceNo": 1,
      "enabled": true,
      "mandatory": true,
      "scanType": "BAGGAGE",
      "allowOptOut": false,
      "prerequisiteActivityIds": ["ACT-001"],
      "restrictToAssignedUsers": true,
      "variantOptions": [],
      "notes": ""
    },
    {
      "activityId": "ACT-003",
      "name": "Loaded to truck",
      "sequenceNo": 2,
      "enabled": true,
      "mandatory": true,
      "scanType": "BAGGAGE",
      "allowOptOut": false,
      "prerequisiteActivityIds": ["ACT-002"],
      "restrictToAssignedUsers": true,
      "variantOptions": [],
      "notes": ""
    }
  ],
  "createdAt": "2026-01-05T09:00:00Z",
  "updatedAt": "2026-01-05T09:00:00Z",
  "updatedBy": "admin-sub-123"
}
```

### 5.2 `EventOccurrence-{tourId}`

**Purpose:** One dated instance of an Event. Holds only overrides, never a copy of the activity list (D3).

| Attribute | Type | Description |
|---|---|---|
| `eventId` | String | Parent event definition (partition key) |
| `dateSeq` | String | `{date}#{seq}` (sort key) — deliberately `date`-first so `SK begins_with date` serves "today's occurrences for this event" directly |
| `occurrenceId` | String | `{eventId}#{date}#{seq}` — the globally-unique, cross-table reference value used as the foreign key in `EventActivityRecord.occurrenceId` and in `linkedOccurrenceRef`. See §6. Derivable from `eventId` + `dateSeq`, but stored so other tables never need to reconstruct it. |
| `date` | String | `YYYY-MM-DD` |
| `seq` | Number | Same-day repeat number (mirrors `rideNo` + `date` in `Ride-{tourId}`) |
| `status` | String | `PLANNED`, `ACTIVE`, `COMPLETED`, `CANCELLED` |
| `startedAt` | String | ISO timestamp, set on start |
| `completedAt` | String | ISO timestamp, set on completion |
| `cancelledAt` | String | ISO timestamp, set on cancellation |
| `cancelledBy` | String | Cognito `sub` who cancelled |
| `cancelReason` | String | Optional free-text reason |
| `disabledActivityIds` | List\<String\> | Per-occurrence activity disable overrides (union with `enabled=false` on the definition) |
| `selfServiceEnabled` | Boolean | Live per-occurrence flag; defaults from `Event.allowSelfService` at creation and can be toggled independently thereafter |
| `linkedOccurrenceRef` | String | Optional `occurrenceId` (fully-qualified, `{eventId}#{date}#{seq}`) of the paired Baggage Unloading/Loading occurrence for reconciliation (D5) |
| `restrictToAssignedUsers` | Boolean | Occurrence-level default inherited from activities unless a caller overrides per-activity; informational only, enforcement is always per-activity |
| `createdAt` | String | ISO 8601 timestamp |
| `updatedAt` | String | ISO 8601 timestamp |
| `updatedBy` | String | Cognito `sub` of last updater |

**Indexes:**
- Primary Key: `eventId` (partition key), `dateSeq` (sort key) — the `date`-first sort key supports `SK begins_with date` within the partition
- GSI1: `date` (partition key), `eventId` (sort key) — for "all occurrences on this date across all events" (dashboard/home-screen queries), mirroring `Ride-{tourId}` GSI1 on `date`
- GSI2: `status` (partition key), `date` (sort key) — for "all ACTIVE occurrences" across events, mirroring the `Ride-{tourId}` status GSI

**Item-count estimate:** For a 15-day tour: 1 (Day 0 Registration) + up to 14 × 2 (loading/unloading, one pair per hotel night) ≈ 30 items per tour.

**Access patterns served:** "get today's occurrences for event X" (primary key query, `PK=eventId`, `SK` `begins_with` date via `dateSeq`); "get all occurrences today across events" (GSI1); "get all currently ACTIVE occurrences" (GSI2); "find the paired occurrence for reconciliation" (`linkedOccurrenceRef` direct lookup by fully-qualified `occurrenceId`).

**Example item:**

```json
{
  "eventId": "EVT-BAGLOAD",
  "dateSeq": "2026-02-12#1",
  "occurrenceId": "EVT-BAGLOAD#2026-02-12#1",
  "date": "2026-02-12",
  "seq": 1,
  "status": "ACTIVE",
  "startedAt": "2026-02-12T05:30:00Z",
  "completedAt": null,
  "cancelledAt": null,
  "cancelledBy": null,
  "cancelReason": null,
  "disabledActivityIds": ["ACT-001"],
  "selfServiceEnabled": true,
  "linkedOccurrenceRef": "EVT-BAGUNLOAD#2026-02-12#1",
  "restrictToAssignedUsers": true,
  "createdAt": "2026-02-11T18:00:00Z",
  "updatedAt": "2026-02-12T05:30:00Z",
  "updatedBy": "super-user-sub-456"
}
```

### 5.3 `EventActivityRecord-{tourId}`

**Purpose:** One scan/completion record. The highest-volume of the new tables (one item per rider per activity per occurrence).

| Attribute | Type | Description |
|---|---|---|
| `occurrenceId` | String | Parent occurrence (partition key) |
| `recordId` | String | `{riderId}#{activityId}#{timestamp}` (sort key). See §6. |
| `eventId` | String | Denormalised parent event, avoids a join to resolve which event an occurrence belongs to |
| `activityId` | String | Activity scanned |
| `activityName` | String | **Denormalised** activity name at scan time (D4) — never re-derived from the current definition |
| `riderId` | String | Rider identified from the scan |
| `typeCode` | String | ID Code type code scanned (`1`=RIDER, `3`–`8`=BAGGAGE); present for baggage scans |
| `bagLabel` | String | Human-readable bag label resolved from `typeCode` (e.g. "Backpack"); present for baggage scans |
| `outcome` | String | `COMPLETED`, `OPTED_OUT`, or `FLAGGED` |
| `variantSelected` | String | Selected variant, e.g. `VEG`/`NON_VEG`, when the activity has `variantOptions` |
| `scannedBy` | String | Cognito `sub` of the user who performed/recorded the scan |
| `hotelId` | String | Hotel where the scan was taken, when applicable (baggage activities) |
| `method` | String | `QR_SCAN` or `MANUAL` |
| `timestamp` | String | ISO 8601 timestamp supplied by the client (honoured for offline/late-sync, §7.9) |
| `syncedAt` | String | ISO 8601 timestamp the record was actually persisted server-side |
| `isFlagged` | Boolean | True when accepted-but-flagged (e.g. late sync past a boundary, §7.9) |
| `flagReason` | String | Reason code when `isFlagged=true` |
| `cancelledAt` | String | ISO timestamp when the scan was cancelled |
| `cancelledBy` | String | Cognito `sub` who cancelled the scan |
| `cancelReason` | String | Optional free-text reason |
| `createdAt` | String | ISO 8601 timestamp of record creation |

**Indexes:**
- Primary Key: `occurrenceId` (partition key), `recordId` (sort key) — serves "all records for an occurrence" directly
- GSI1: `riderId` (partition key), `timestamp` (sort key) — serves "all records for a rider" across occurrences/events, mirroring the `CheckIn-{tourId}` GSI1 pattern

**Item-count estimate:** ~100 riders × up to 8 activities (5 registration + 3 per baggage direction) × up to 14 baggage days ≈ several thousand items per tour over the tour lifetime; this is the highest-volume new table, consistent with check-in volumes today.

**Access patterns served:** "all records for occurrence X" (primary key query); "all records for rider R" (GSI1 query); "reconciliation: bags loaded vs unloaded" (two occurrence-scoped queries compared via `linkedOccurrenceRef`, §7.10).

**Example item (baggage scan):**

```json
{
  "occurrenceId": "EVT-BAGLOAD#2026-02-12#1",
  "recordId": "R57#ACT-003#2026-02-12T05:42:10Z",
  "eventId": "EVT-BAGLOAD",
  "activityId": "ACT-003",
  "activityName": "Loaded to truck",
  "riderId": "R57",
  "typeCode": "3",
  "bagLabel": "Baggage 1",
  "outcome": "COMPLETED",
  "variantSelected": null,
  "scannedBy": "hotel-staff-sub-789",
  "hotelId": "HTL-MDU-01",
  "method": "QR_SCAN",
  "timestamp": "2026-02-12T05:42:10Z",
  "syncedAt": "2026-02-12T05:42:15Z",
  "isFlagged": false,
  "flagReason": null,
  "cancelledAt": null,
  "cancelledBy": null,
  "cancelReason": null,
  "createdAt": "2026-02-12T05:42:15Z"
}
```

### 5.4 `Hotel-{tourId}` and `HotelStay-{tourId}`

**`Hotel-{tourId}`** (D9 — tour table, not `AppConfig`):

| Attribute | Type | Description |
|---|---|---|
| `hotelId` | String | Stable hotel identifier (partition key). See §6. |
| `name` | String | Hotel name |
| `city` | String | City |
| `address` | String | Full address |
| `contact` | String | Contact information |
| `notes` | String | Operational notes |
| `createdAt` | String | ISO 8601 timestamp |
| `updatedAt` | String | ISO 8601 timestamp |

**Indexes:** Primary Key `hotelId` (partition key only). No GSI — hotel count per tour is small (one per city visited, typically 10–15).

**Item-count estimate:** 10–15 per tour.

**`HotelStay-{tourId}`** (D8 — keyed by night):

| Attribute | Type | Description |
|---|---|---|
| `stayDate` | String | `YYYY-MM-DD` (partition key) |
| `riderId` | String | Rider ID (sort key) |
| `hotelId` | String | Hotel reference |
| `roomNo` | String | Room number |
| `sharingWith` | String | Co-occupant rider ID for a two-person pairing; single rider ID only, larger shared rooms out of scope |
| `checkInDate` | String | Optional check-in date, informational |
| `checkOutDate` | String | Optional check-out date, informational |
| `source` | String | `UPLOAD` or `MANUAL` |
| `uploadId` | String | Source upload ID when `source=UPLOAD` (§6, §8.15) |
| `createdAt` | String | ISO 8601 timestamp |
| `updatedAt` | String | ISO 8601 timestamp |
| `updatedBy` | String | Cognito `sub` of last updater |

**Indexes:**
- Primary Key: `stayDate` (partition key), `riderId` (sort key) — serves "who is staying where tonight" directly
- GSI1: `riderId` (partition key), `stayDate` (sort key) — serves "all stays for a rider" (rider's own itinerary, manual-adjustment screen lookup)
- GSI2: `hotelId` (partition key), `stayDate` (sort key), projecting `roomNo` — serves "room-wise delivery list for a hotel on a date" and room-clash detection during upload/manual edit

**Item-count estimate:** ~100 riders × up to 14 nights ≈ 1,400 items per tour.

**Access patterns served:** "who is staying where tonight" (primary key query on `stayDate`); "all stays for rider R" (GSI1); "room clash check for hotel H on date D" (GSI2); "by room" (GSI2 filtered client-side by `roomNo` — room count per hotel is small enough that this is efficient without a third index).

**Example items:**

```json
{
  "hotelId": "HTL-MDU-01",
  "name": "Hotel Grand Madurai",
  "city": "Madurai",
  "address": "12 Temple Road, Madurai",
  "contact": "+91-452-1234567",
  "notes": "Group check-in via side entrance",
  "createdAt": "2026-01-10T09:00:00Z",
  "updatedAt": "2026-01-10T09:00:00Z"
}
```

```json
{
  "stayDate": "2026-02-12",
  "riderId": "R57",
  "hotelId": "HTL-MDU-01",
  "roomNo": "204",
  "sharingWith": "R58",
  "checkInDate": "2026-02-11",
  "checkOutDate": "2026-02-13",
  "source": "UPLOAD",
  "uploadId": "UPL-000042",
  "createdAt": "2026-02-01T10:00:00Z",
  "updatedAt": "2026-02-01T10:00:00Z",
  "updatedBy": "admin-sub-123"
}
```

### 5.5 Deltas to `TourRider-{tourId}`

New attributes added to the existing table (all other existing attributes unchanged):

| Attribute | Type | Description |
|---|---|---|
| `baggageStatus` | String | `ACTIVE`, `RETAINED`, `RELEASED` (D10) |
| `baggageExitedAt` | String | ISO timestamp when baggage entered organiser custody at rider exit |
| `baggageExitedBy` | String | Cognito `sub` |
| `baggageReleasedAt` | String | ISO timestamp when baggage was returned/released |
| `baggageReleasedBy` | String | Cognito `sub` |
| `baggageExitNote` | String | Optional free-text note |

### 5.6 Delta to `RiderProfile` (shared table)

| Attribute | Type | Description |
|---|---|---|
| `dietaryPreference` | String | Optional. `VEG` or `NON_VEG`. Self-service editable by the rider via `tour-rider-app` (D14) and by an administrator via `tour-mgmt-app`. Drives the `variantSelected` default when scanning a Nutri-Pack-style activity. |

### 5.7 Deltas to `User-{tourId}`

| Attribute | Type | Description |
|---|---|---|
| `hotelId` | String | Optional. Hotel a `HOTEL_STAFF` user is assigned to, for the origin/destination hotel-match rule (§9.3). |
| `eventAssignments` | List\<Map\> | Optional. Each entry: `{ "eventId": String, "dates": List<String> or "ALL" }`. Used by the second authorisation layer (§9.3) to confirm a user is assigned to the event for the scan date. |
| `assignedActivityIds` | List\<String\> | Optional. When an activity sets `restrictToAssignedUsers=true` (the default, D15), the scanning user must have the activity's ID in this list. |

**Origin/destination hotel-match rule:** a `HOTEL_STAFF` user's `hotelId` must match the rider's `HotelStay.hotelId` for the applicable night — **the previous night's stay for a loading scan, the current night's stay for an unloading scan** — because the rider physically leaves the origin hotel each morning and arrives at the destination hotel each evening. This is detailed in §9.3.

## 6. Identifier formats

| Entity | Format | Example | Validation regex |
|---|---|---|---|
| Event ID | `EVT-` + uppercase slug | `EVT-BAGLOAD`, `EVT-REG` | `^EVT-[A-Z0-9]{2,20}$` |
| Activity ID | `ACT-` + 3-digit padded, unique within an event | `ACT-001` | `^ACT-\d{3}$` |
| Occurrence ID | `{eventId}#{date}#{seq}` | `EVT-BAGLOAD#2026-02-12#1` | `^EVT-[A-Z0-9]{2,20}#\d{4}-\d{2}-\d{2}#[1-9]\d*$` |
| Activity Record ID | `{riderId}#{activityId}#{timestamp}` | `R57#ACT-003#2026-02-12T05:42:10Z` | `^R([1-9]\d{0,2})#ACT-\d{3}#\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` |
| Hotel ID | `HTL-` + 3-letter city code + 2-digit padded | `HTL-MDU-01` | `^HTL-[A-Z]{3}-\d{2}$` |
| Upload ID | `UPL-` + 6-digit padded | `UPL-000042` | `^UPL-\d{6}$` |

These follow the existing padded-ID conventions in `validation.py` (`RIDE\d{3}`, `S\d{3}`) and would be implemented as `validate_event_id`, `validate_activity_id`, `validate_occurrence_id`, `validate_hotel_id`, `validate_upload_id` functions alongside the existing `validate_rider_id` / `validate_ride_id` / `validate_stage_id` in `src/layers/common/validation.py`, following the same `ValidationError` raise pattern.

## 7. Access patterns

In the style of the existing "Access Patterns" section in `SolutionDesign.md`:

1. **Event definition management**
   - Get one event definition by `eventId`
   - List all event definitions for a tour
   - Create/update an event definition, including its embedded `activities` list
2. **Occurrence management**
   - Get all occurrences for an event on/after a date (`Query` on `EventOccurrence` primary key, `SK begins_with` date)
   - Get all occurrences across events on a given date (GSI1)
   - Get all currently `ACTIVE` occurrences (GSI2)
   - Create an occurrence for a date + sequence number
   - Start / complete / cancel an occurrence
   - Toggle `disabledActivityIds` and `selfServiceEnabled` on an occurrence
3. **Activity scanning**
   - Create an activity record (QR scan or manual) against an occurrence
   - Get all records for an occurrence (dashboard/progress)
   - Get all records for a rider (rider progress stepper, rider-app self view)
   - Cancel an activity record
4. **Reconciliation**
   - Get the loading occurrence's records and the paired unloading occurrence's records (via `linkedOccurrenceRef`) and diff by `riderId` + `typeCode`
5. **Hotel management**
   - Get/list hotels for a tour
   - Create/update a hotel
   - Get stays for a date (who is where tonight)
   - Get stays for a rider (rider's own itinerary)
   - Get stays for a hotel/room on a date (room-wise delivery, clash detection)
   - Manual single-night stay adjustment
6. **Hotel allocation upload**
   - Request a presigned CSV upload URL
   - Poll upload processing status
7. **Rider exit / baggage**
   - Exit a rider with a mandatory baggage disposition choice
   - Cancel a rider exit
   - Release retained baggage
8. **Bootstrap**
   - Bulk-read endpoints for offline priming: event definitions, active occurrences, the rider's own baggage status, and the rider's own hotel stays

## 8. Full API design

All endpoints use the repository's standard response envelope (`docs/api-guide.md` §Response Format) and are versioned under `/v1`. Every endpoint requires a valid Cognito JWT; the "Permission" column states the RBAC permission additionally required (§9).

### 8.1 Endpoint summary

| Domain | Method | Path | Permission |
|---|---|---|---|
| Events | GET | `/v1/tours/{tourId}/events` | READ |
| Events | GET | `/v1/tours/{tourId}/events/{eventId}` | READ |
| Events | POST | `/v1/tours/{tourId}/events` | EVENT_MANAGE |
| Events | PUT | `/v1/tours/{tourId}/events/{eventId}` | EVENT_MANAGE |
| Occurrences | GET | `/v1/tours/{tourId}/events/{eventId}/occurrences` | READ |
| Occurrences | GET | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}` | READ |
| Occurrences | POST | `/v1/tours/{tourId}/events/{eventId}/occurrences` | EVENT_OCCURRENCE_MANAGE |
| Occurrences | PUT | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}` | EVENT_OCCURRENCE_MANAGE |
| Occurrences | POST | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/start` | EVENT_OCCURRENCE_MANAGE |
| Occurrences | POST | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/complete` | EVENT_OCCURRENCE_MANAGE |
| Occurrences | POST | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/cancel` | EVENT_OCCURRENCE_MANAGE |
| Activity scans | POST | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/records` | EVENT_SCAN |
| Activity scans | POST | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/records/{recordId}/cancel` | EVENT_SCAN |
| Progress | GET | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/dashboard` | DASHBOARD |
| Progress | GET | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/dashboard/progress` | DASHBOARD |
| Progress | GET | `/v1/tours/{tourId}/riders/{riderId}/events/progress` | READ |
| Reconciliation | GET | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/reconciliation` | DASHBOARD |
| Hotels | GET | `/v1/tours/{tourId}/hotels` | READ |
| Hotels | POST | `/v1/tours/{tourId}/hotels` | HOTEL_ALLOC_MANAGE |
| Hotels | PUT | `/v1/tours/{tourId}/hotels/{hotelId}` | HOTEL_ALLOC_MANAGE |
| Hotel stays | GET | `/v1/tours/{tourId}/hotelstays?date={date}` | READ |
| Hotel stays | GET | `/v1/tours/{tourId}/riders/{riderId}/hotelstays` | READ |
| Hotel stays | GET | `/v1/tours/{tourId}/hotels/{hotelId}/hotelstays?date={date}` | READ |
| Hotel stays | PUT | `/v1/tours/{tourId}/hotelstays/{stayDate}/{riderId}` | HOTEL_ALLOC_MANAGE |
| Hotel upload | POST | `/v1/tours/{tourId}/hotelstays/uploads/presign` | HOTEL_ALLOC_MANAGE |
| Hotel upload | GET | `/v1/tours/{tourId}/hotelstays/uploads/{uploadId}` | HOTEL_ALLOC_MANAGE |
| Rider exit | POST | `/v1/tours/{tourId}/riders/{riderId}/exit` (existing, extended) | RIDER_EXIT |
| Rider exit | POST | `/v1/tours/{tourId}/riders/{riderId}/exit/cancel` (existing, extended) | RIDER_EXIT |
| Baggage | POST | `/v1/tours/{tourId}/riders/{riderId}/baggage/release` | RIDER_EXIT |
| Bootstrap | GET | `/v1/tours/{tourId}/events/bootstrap` | READ |

### 8.2 Events — GET /v1/tours/{tourId}/events

Lists all event definitions for the tour.

- Query params: none
- Success (200): `{ "success": true, "data": { "items": [ <Event item, §5.1> ] } }`
- Errors: `401`, `403`

### 8.3 Events — GET /v1/tours/{tourId}/events/{eventId}

- Success (200): `{ "success": true, "data": <Event item> }`
- Errors: `401`, `403`, `404 EVENT_NOT_FOUND`

### 8.4 Events — POST /v1/tours/{tourId}/events

Creates an event definition.

- Required permission: `EVENT_MANAGE`
- Request body: `eventId`, `eventName`, `eventType` (`SINGLE`|`REPEATING`), `location`, `sequenceEnforced`, `defaultScanType`, `allowSelfService`, `activities` (array, schema §5.1; each activity requires `activityId`, `name`, `sequenceNo`, `scanType`; `restrictToAssignedUsers` defaults to `true` when omitted per D15)
- Success (201): `{ "success": true, "data": <created Event item> }`
- Errors: `400 VALIDATION_ERROR` (missing/invalid fields, duplicate `activityId` within `activities`, invalid `sequenceNo` ordering), `401`, `403`, `409 EVENT_ALREADY_EXISTS` (duplicate `eventId`)

### 8.5 Events — PUT /v1/tours/{tourId}/events/{eventId}

Updates an event definition, including replacing the `activities` list. Per D4, existing `EventActivityRecord` items are never rewritten by this call.

- Required permission: `EVENT_MANAGE`
- Request body: any subset of the creatable fields
- Success (200): `{ "success": true, "data": <updated Event item> }`
- Errors: `400 VALIDATION_ERROR`, `401`, `403`, `404 EVENT_NOT_FOUND`

### 8.6 Occurrences — GET /v1/tours/{tourId}/events/{eventId}/occurrences

- Query params: `date` (optional, `YYYY-MM-DD`), `status` (optional, one of `PLANNED|ACTIVE|COMPLETED|CANCELLED`)
- Success (200): `{ "success": true, "data": { "items": [ <EventOccurrence item, §5.2> ] } }`
- Errors: `401`, `403`, `404 EVENT_NOT_FOUND`

### 8.7 Occurrences — GET .../occurrences/{occurrenceId}

- Success (200): `{ "success": true, "data": <EventOccurrence item> }`
- Errors: `401`, `403`, `404 OCCURRENCE_NOT_FOUND`

### 8.8 Occurrences — POST .../occurrences

Creates an occurrence for a date + sequence number.

- Required permission: `EVENT_OCCURRENCE_MANAGE`
- Request body: `date` (required), `seq` (required, positive integer), `disabledActivityIds` (optional), `selfServiceEnabled` (optional, defaults to `Event.allowSelfService`), `linkedOccurrenceRef` (optional)
- Success (201): `{ "success": true, "data": <created EventOccurrence item> }` with `status=PLANNED`
- Errors: `400 VALIDATION_ERROR`, `401`, `403`, `404 EVENT_NOT_FOUND`, `409 OCCURRENCE_ALREADY_EXISTS` (duplicate `date`+`seq`)

### 8.9 Occurrences — PUT .../occurrences/{occurrenceId}

Updates `disabledActivityIds`, `selfServiceEnabled`, or `linkedOccurrenceRef` on a non-`COMPLETED`, non-`CANCELLED` occurrence.

- Required permission: `EVENT_OCCURRENCE_MANAGE`
- Errors: `400 VALIDATION_ERROR`, `401`, `403`, `404 OCCURRENCE_NOT_FOUND`, `409 OCCURRENCE_CLOSED` (occurrence is `COMPLETED` or `CANCELLED`)

### 8.10 Occurrences — POST .../occurrences/{occurrenceId}/start

Transitions `PLANNED → ACTIVE`.

- Required permission: `EVENT_OCCURRENCE_MANAGE`
- Success (200): updated item with `status=ACTIVE`, `startedAt` set
- Errors: `401`, `403`, `404 OCCURRENCE_NOT_FOUND`, `409 INVALID_OCCURRENCE_TRANSITION` (not currently `PLANNED`)

### 8.11 Occurrences — POST .../occurrences/{occurrenceId}/complete

Transitions `ACTIVE → COMPLETED`. Does **not** require all mandatory activities to be complete for every rider (organiser override), but the response surfaces outstanding mandatory activity counts (§7.2).

- Required permission: `EVENT_OCCURRENCE_MANAGE`
- Success (200): updated item with `status=COMPLETED`, `completedAt` set, plus `data.outstandingMandatoryCount`
- Errors: `401`, `403`, `404 OCCURRENCE_NOT_FOUND`, `409 INVALID_OCCURRENCE_TRANSITION` (not currently `ACTIVE`)

### 8.12 Occurrences — POST .../occurrences/{occurrenceId}/cancel

- Required permission: `EVENT_OCCURRENCE_MANAGE`
- Request body: `cancelReason` (optional)
- Success (200): updated item with `status=CANCELLED`, `cancelledAt`, `cancelledBy` set
- Errors: `401`, `403`, `404 OCCURRENCE_NOT_FOUND`, `409 INVALID_OCCURRENCE_TRANSITION` (already `COMPLETED` or `CANCELLED`)

### 8.13 Activity scans — POST .../occurrences/{occurrenceId}/records

Creates one `EventActivityRecord`.

- Required permission: `EVENT_SCAN`, plus the second authorisation layer (§9.3) when the activity has `restrictToAssignedUsers=true` (default) or the event is a baggage event
- Request body: `activityId` (required), `riderId` (required — resolved client-side from the scanned ID Code, see frontend §8), `typeCode` (required for `scanType=BAGGAGE` activities), `outcome` (optional, default `COMPLETED`; `OPTED_OUT` only when the activity has `allowOptOut=true`), `variantSelected` (required when the activity has `variantOptions`), `method` (`QR_SCAN`|`MANUAL`), `timestamp` (required — client-supplied for offline support, §7.9)
- Success (201): `{ "success": true, "data": <created EventActivityRecord, §5.3> }`
- Errors:
  - `400 VALIDATION_ERROR` — missing required field, or `variantSelected` missing/invalid for a variant activity
  - `400 SCAN_TYPE_NOT_ALLOWED` — scanned `typeCode` is not the activity's allowed `scanType`
  - `401`, `403`
  - `403 RIDER_NOT_ASSIGNED` — caller's `eventAssignments` does not cover this event/date (§9.3)
  - `403 HOTEL_MISMATCH` — caller's `hotelId` does not match the rider's applicable `HotelStay.hotelId` (§9.3)
  - `404 RIDER_NOT_FOUND`, `404 OCCURRENCE_NOT_FOUND`, `404 ACTIVITY_NOT_FOUND`
  - `409 DUPLICATE_ACTIVITY_RECORD` — rider already has a non-cancelled record for this activity+occurrence
  - `409 PREREQUISITE_NOT_MET` — `sequenceEnforced=true` or the activity's `prerequisiteActivityIds` are not all `COMPLETED` for this rider+occurrence
  - `409 OCCURRENCE_NOT_ACTIVE` — occurrence is not `ACTIVE` and the client `timestamp` does not predate closure (§7.9)
  - `409 BAGGAGE_NOT_IN_TOUR` — rider's `baggageStatus=RELEASED` and the client `timestamp` is not before `baggageReleasedAt` (§7.10)

### 8.14 Activity scans — POST .../records/{recordId}/cancel

- Required permission: `EVENT_SCAN`
- Request body: `cancelReason` (optional)
- Success (200): updated record with `cancelledAt`, `cancelledBy` set; excluded from progress totals thereafter
- Errors: `401`, `403`, `404 RECORD_NOT_FOUND`, `409 RECORD_ALREADY_CANCELLED`

### 8.15 Progress — GET .../occurrences/{occurrenceId}/dashboard and /dashboard/progress

Mirrors the existing ride dashboard pair. `/dashboard` returns full per-rider detail; `/dashboard/progress` returns aggregate counts only (lighter payload for frequent polling), supporting ETag/`304` per the existing convention.

- Required permission: `DASHBOARD`
- Success (200) `/dashboard`: `{ "success": true, "data": { "occurrence": <EventOccurrence>, "riders": [ { "riderId", "activities": [ { "activityId", "status": "PENDING"|"COMPLETED"|"OPTED_OUT"|"FLAGGED" } ] } ], "cancelled": [ <cancelled records> ] } }`
- Success (200) `/dashboard/progress`: `{ "success": true, "data": { "totalRiders", "completedCount", "outstandingMandatoryCount", "optedOutCount", "flaggedCount" } }`
- Errors: `401`, `403`, `404 OCCURRENCE_NOT_FOUND`

### 8.16 Progress — GET /v1/tours/{tourId}/riders/{riderId}/events/progress

Per-rider progress across all events (used by the rider progress stepper and `tour-rider-app` self-view).

- Query params: `eventId` (optional filter)
- Success (200): `{ "success": true, "data": { "items": [ { "eventId", "occurrenceId", "activityId", "status" } ] } }`
- Errors: `401`, `403`, `404 RIDER_NOT_FOUND`

### 8.17 Reconciliation — GET .../occurrences/{occurrenceId}/reconciliation

Only valid for an occurrence whose own `linkedOccurrenceRef` (§5.2) is set.

- Required permission: `DASHBOARD`
- Success (200): `{ "success": true, "data": { "loadedCount", "unloadedCount", "missingRiderIds": [ "R12", "R57" ] } }`
- Errors: `401`, `403`, `404 OCCURRENCE_NOT_FOUND`, `400 NO_LINKED_OCCURRENCE`

### 8.18 Hotels — GET/POST/PUT

- `GET /v1/tours/{tourId}/hotels` — `READ`; success `{ "data": { "items": [ <Hotel item> ] } }`
- `POST /v1/tours/{tourId}/hotels` — `HOTEL_ALLOC_MANAGE`; body = creatable Hotel fields; `201`; errors `400 VALIDATION_ERROR`, `409 HOTEL_ALREADY_EXISTS`
- `PUT /v1/tours/{tourId}/hotels/{hotelId}` — `HOTEL_ALLOC_MANAGE`; `200`; errors `400 VALIDATION_ERROR`, `404 HOTEL_NOT_FOUND`

### 8.19 Hotel stays — GET by date / by rider / by hotel

- `GET /v1/tours/{tourId}/hotelstays?date={date}` — `READ`; success `{ "data": { "items": [ <HotelStay item> ] } }`; errors `400 VALIDATION_ERROR` (missing/invalid `date`)
- `GET /v1/tours/{tourId}/riders/{riderId}/hotelstays` — `READ`; success `{ "data": { "items": [ ... ] } }`; errors `404 RIDER_NOT_FOUND`
- `GET /v1/tours/{tourId}/hotels/{hotelId}/hotelstays?date={date}` — `READ`; success `{ "data": { "items": [ ... ] } }` sorted by `roomNo` for room-wise delivery; errors `404 HOTEL_NOT_FOUND`, `400 VALIDATION_ERROR`

### 8.20 Hotel stays — PUT manual adjustment

- `PUT /v1/tours/{tourId}/hotelstays/{stayDate}/{riderId}` — `HOTEL_ALLOC_MANAGE`; body: `hotelId`, `roomNo`, `sharingWith` (optional); sets `source=MANUAL`
- Success (200): updated `HotelStay` item
- Errors: `400 VALIDATION_ERROR`, `404 RIDER_NOT_FOUND`, `404 HOTEL_NOT_FOUND`, `409 ROOM_CLASH` (another rider already in `roomNo` at this hotel/date, unless it is the reciprocal `sharingWith` pairing), `409 NON_RECIPROCAL_SHARING` (`sharingWith` rider's own record does not name this rider back)

### 8.21 Hotel upload — POST presign

- `POST /v1/tours/{tourId}/hotelstays/uploads/presign` — `HOTEL_ALLOC_MANAGE`
- Request body: none (server allocates `uploadId`)
- Success (200): `{ "data": { "uploadId": "UPL-000042", "uploadUrl": "https://s3...", "s3Key": "tours/{tourId}/uploads/hotel-allocation/UPL-000042.csv", "expiresIn": 900 } }`
- Errors: `401`, `403`

### 8.22 Hotel upload — GET status

- `GET /v1/tours/{tourId}/hotelstays/uploads/{uploadId}` — `HOTEL_ALLOC_MANAGE`
- Success (200): `{ "data": { "uploadId", "status": "PENDING"|"PROCESSING"|"COMPLETED"|"FAILED", "rowCount", "successCount", "errorCount", "errors": [ { "row": 3, "code": "UNKNOWN_HOTEL_ID", "message": "..." } ], "processedAt" } }`
- Errors: `404 UPLOAD_NOT_FOUND`

### 8.23 Rider exit (extended) and baggage release

- `POST /v1/tours/{tourId}/riders/{riderId}/exit` (existing endpoint, extended request body) — `RIDER_EXIT`; new required field `baggageDisposition` (`RETAINED`|`RELEASED`); missing value now returns `400 BAGGAGE_DISPOSITION_REQUIRED`
- `POST /v1/tours/{tourId}/riders/{riderId}/exit/cancel` (existing, extended) — `RIDER_EXIT`; restores `baggageStatus` to `ACTIVE` alongside the existing `status` restore
- `POST /v1/tours/{tourId}/riders/{riderId}/baggage/release` — `RIDER_EXIT`; sets `baggageStatus=RELEASED`, `baggageReleasedAt`, `baggageReleasedBy`; body: `note` (optional, maps to `baggageExitNote`); errors `404 RIDER_NOT_FOUND`, `409 BAGGAGE_NOT_RETAINED` (only valid from `RETAINED`)

### 8.24 Bootstrap — GET /v1/tours/{tourId}/events/bootstrap

Bulk-read endpoint for offline priming after sign-in, mirroring the existing `GET /v1/config` and rider-names bootstrap pattern.

- Required permission: `READ`
- Success (200): `{ "data": { "events": [ <Event items with embedded activities> ], "activeOccurrences": [ <EventOccurrence items with status ACTIVE or PLANNED for today/tomorrow> ], "riderBaggageStatus": [ { "riderId", "baggageStatus", "baggageReleasedAt" } ], "hotelStaysToday": [ <HotelStay items for today's date> ] } }`
- Supports ETag / `304 Not Modified` per the existing config/dashboard convention
- Errors: `401`, `403`

### 8.25 Error code reference

New error codes introduced by this design, in addition to the standard `400`/`401`/`403`/`404`/`409`/`500` HTTP statuses already documented in `docs/api-guide.md`:

| Code | HTTP | Trigger | User-facing message |
|---|---|---|---|
| `EVENT_NOT_FOUND` | 404 | `eventId` does not exist for the tour | "Event not found." |
| `EVENT_ALREADY_EXISTS` | 409 | Duplicate `eventId` on create | "An event with this ID already exists." |
| `OCCURRENCE_NOT_FOUND` | 404 | `occurrenceId` does not exist | "Occurrence not found." |
| `OCCURRENCE_ALREADY_EXISTS` | 409 | Duplicate `date`+`seq` on create | "An occurrence already exists for this date and sequence." |
| `OCCURRENCE_CLOSED` | 409 | Update attempted on `COMPLETED`/`CANCELLED` occurrence | "This occurrence is closed and cannot be edited." |
| `INVALID_OCCURRENCE_TRANSITION` | 409 | Start/complete/cancel called from an invalid state | "This occurrence cannot be transitioned from its current status." |
| `NO_LINKED_OCCURRENCE` | 400 | Reconciliation requested with no `linkedOccurrenceRef` | "This occurrence has no linked occurrence to reconcile against." |
| `ACTIVITY_NOT_FOUND` | 404 | `activityId` not present (or disabled) on the event/occurrence | "Activity not found or disabled for this occurrence." |
| `SCAN_TYPE_NOT_ALLOWED` | 400 | Scanned type code not allowed for the activity | "This ID Code type is not allowed for this activity." |
| `DUPLICATE_ACTIVITY_RECORD` | 409 | Rider already has a non-cancelled record for this activity+occurrence | "This activity has already been recorded for this rider." |
| `PREREQUISITE_NOT_MET` | 409 | Sequence/prerequisite violated | "Complete the required prior activity before this one." |
| `OCCURRENCE_NOT_ACTIVE` | 409 | Scan against a non-`ACTIVE` occurrence, not covered by late-sync grace | "This occurrence is not currently open for scanning." |
| `BAGGAGE_NOT_IN_TOUR` | 409 | Rider's baggage is `RELEASED` | "{riderName}'s baggage was released on {baggageReleasedAt} and can no longer be scanned." |
| `RIDER_NOT_ASSIGNED` | 403 | Caller not in `eventAssignments` for this event/date | "You are not assigned to this event today." |
| `HOTEL_MISMATCH` | 403 | Caller's `hotelId` does not match rider's applicable stay | "This rider is not staying at your assigned hotel tonight." |
| `HOTEL_NOT_FOUND` | 404 | `hotelId` does not exist | "Hotel not found." |
| `HOTEL_ALREADY_EXISTS` | 409 | Duplicate `hotelId` on create | "A hotel with this ID already exists." |
| `ROOM_CLASH` | 409 | Room already occupied by a non-reciprocal rider | "Room {roomNo} is already allocated to another rider on this date." |
| `NON_RECIPROCAL_SHARING` | 409 | `sharingWith` rider does not name this rider back | "The paired rider's record does not confirm this room sharing." |
| `UPLOAD_NOT_FOUND` | 404 | `uploadId` unknown | "Upload not found." |
| `BAGGAGE_DISPOSITION_REQUIRED` | 400 | Rider exit called without `baggageDisposition` | "Choose whether baggage is retained or released before exiting this rider." |
| `BAGGAGE_NOT_RETAINED` | 409 | Release attempted when `baggageStatus != RETAINED` | "Baggage is not currently retained for this rider." |
| `RECORD_NOT_FOUND` | 404 | `recordId` unknown | "Activity record not found." |
| `RECORD_ALREADY_CANCELLED` | 409 | Cancel called twice | "This activity record has already been cancelled." |

## 9. RBAC and permission model

### 9.1 New permissions

Added to `Permission` in `src/layers/common/rbac.py`, following the existing enum style:

```python
class Permission(str, Enum):
    ...
    EVENT_MANAGE = "EVENT_MANAGE"
    """Create or update an event definition, including its embedded activities."""

    EVENT_OCCURRENCE_MANAGE = "EVENT_OCCURRENCE_MANAGE"
    """Create, update, start, complete, or cancel an event occurrence."""

    EVENT_SCAN = "EVENT_SCAN"
    """Create or cancel an event activity scan record."""

    HOTEL_ALLOC_MANAGE = "HOTEL_ALLOC_MANAGE"
    """Manage hotels, hotel stays, and hotel allocation CSV uploads."""
```

### 9.2 Full RBAC matrix

Reproducing every existing permission plus the four additions, in the same style as the docstring table already in `rbac.py`:

| Permission | ADMINISTRATOR | SUPER_USER | PS_\<n\>_USER | HOTEL_STAFF | GUEST | RIDER |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| READ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| CHECKIN | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| CHECKIN_MANUAL | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| RIDE_MANAGE | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| PIT_STOP_MANAGE | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| TOUR_MANAGE | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| USER_LIST | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| DASHBOARD | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |
| NOTIFICATION_MANAGE | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| RIDER_EXIT | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| ARTIFACT_MANAGE | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| RIDER_SELF_UPDATE | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **EVENT_MANAGE** | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| **EVENT_OCCURRENCE_MANAGE** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **EVENT_SCAN** | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| **HOTEL_ALLOC_MANAGE** | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |

No new Cognito groups are introduced (D12). `GROUP_PERMISSIONS["HOTEL_STAFF"]` gains `EVENT_SCAN`; `GROUP_PERMISSIONS["ADMINISTRATOR"]` and `["SUPER_USER"]` gain `EVENT_OCCURRENCE_MANAGE` and `HOTEL_ALLOC_MANAGE`; `GROUP_PERMISSIONS["ADMINISTRATOR"]` alone gains `EVENT_MANAGE`; `PIT_STOP_GROUP_PERMISSIONS` gains `EVENT_SCAN`.

### 9.3 Second authorisation layer: `eventAssignments` and hotel match

Permission checks (§9.2) establish *what* an action a role may perform. A second, independent layer establishes *which* rider/event/hotel combination a specific user may act on for `EVENT_SCAN` calls against an activity where `restrictToAssignedUsers=true` (the default, D15):

1. **Assignment check.** The caller's `User-{tourId}.eventAssignments` must contain an entry for the occurrence's `eventId` whose `dates` is `"ALL"` or includes the occurrence's `date`. If not, the request is rejected with `403 RIDER_NOT_ASSIGNED`.
2. **Hotel-match check** (baggage events only). The caller's `User-{tourId}.hotelId` must equal the rider's applicable `HotelStay.hotelId`:
   - For a **Baggage Loading** activity, "applicable" means the rider's `HotelStay` for the **previous night** (the rider is leaving that hotel this morning).
   - For a **Baggage Unloading** activity, "applicable" means the rider's `HotelStay` for the **current night** (the rider is arriving at that hotel this evening).
   - If the caller's `hotelId` does not match, the request is rejected with `403 HOTEL_MISMATCH`.
3. Both checks are enforced only when the activity's `restrictToAssignedUsers` resolves to `true`; an activity explicitly set to `false` skips both checks and relies on permission alone.
4. If `assignedActivityIds` is also populated on the user, the caller's activity access is further narrowed to that list (mirroring the existing `PS_<n>_USER` stage-restriction pattern), independent of the `eventAssignments` check.

This mirrors the existing `require_pit_stop_stage_access()` helper pattern in `rbac.py` and would be implemented as a new `require_event_assignment_access()` helper in the same module.

## 10. Provisioning and migration impact

### 10.1 Table provisioning

`src/layers/common/tour_provisioning.py` gains 5 new table specs (`Event`, `EventOccurrence`, `EventActivityRecord`, `Hotel`, `HotelStay`), each following the existing spec shape (table name suffix, key schema, GSIs, billing mode). `PUT /v1/tours/{tourId}/provision` creates any missing table types for tours provisioned before this change, without touching `TourMaster.provisionedAt`.

### 10.2 Seeding the three events as configuration

The three seed event definitions are created via a tour-scoped seed script (in the style of `scripts/seed_app_config.py`, which seeds the shared `AppConfig` table) that writes directly to the newly-provisioned `Event-{tourId}` table for a given tour:

```python
EVENT_SEEDS = [
    {
        'eventId': 'EVT-REG',
        'eventName': 'Day 0 Registration',
        'eventType': 'SINGLE',
        'location': 'Tour start venue',
        'sequenceEnforced': True,
        'defaultScanType': 'RIDER',
        'allowSelfService': False,
        'activities': [
            {'activityId': 'ACT-001', 'name': 'ID Card collection', 'sequenceNo': 0,
             'enabled': True, 'mandatory': True, 'scanType': 'RIDER',
             'allowOptOut': False, 'prerequisiteActivityIds': [],
             'restrictToAssignedUsers': True, 'variantOptions': [], 'notes': ''},
            {'activityId': 'ACT-002', 'name': 'Indemnity Agreement signing', 'sequenceNo': 1,
             'enabled': True, 'mandatory': True, 'scanType': 'RIDER',
             'allowOptOut': False, 'prerequisiteActivityIds': ['ACT-001'],
             'restrictToAssignedUsers': True, 'variantOptions': [], 'notes': ''},
            {'activityId': 'ACT-003', 'name': 'Jersey collection', 'sequenceNo': 2,
             'enabled': True, 'mandatory': True, 'scanType': 'RIDER',
             'allowOptOut': False, 'prerequisiteActivityIds': ['ACT-002'],
             'restrictToAssignedUsers': True, 'variantOptions': [], 'notes': ''},
            {'activityId': 'ACT-004', 'name': 'Nutri-Pack collection', 'sequenceNo': 3,
             'enabled': True, 'mandatory': False, 'scanType': 'RIDER',
             'allowOptOut': True, 'prerequisiteActivityIds': ['ACT-003'],
             'restrictToAssignedUsers': True, 'variantOptions': ['VEG', 'NON_VEG'], 'notes': ''},
            {'activityId': 'ACT-005', 'name': 'Goodies Bag collection', 'sequenceNo': 4,
             'enabled': True, 'mandatory': False, 'scanType': 'RIDER',
             'allowOptOut': True, 'prerequisiteActivityIds': ['ACT-004'],
             'restrictToAssignedUsers': True, 'variantOptions': [], 'notes': ''},
        ],
    },
    {
        'eventId': 'EVT-BAGLOAD',
        'eventName': 'Baggage Loading',
        'eventType': 'REPEATING',
        'location': 'Origin hotel',
        'sequenceEnforced': True,
        'defaultScanType': 'BAGGAGE',
        'allowSelfService': True,
        'activities': [
            {'activityId': 'ACT-001', 'name': 'Room pickup', 'sequenceNo': 0,
             'enabled': True, 'mandatory': False, 'scanType': 'BAGGAGE',
             'allowOptOut': False, 'prerequisiteActivityIds': [],
             'restrictToAssignedUsers': True, 'variantOptions': [], 'notes': ''},
            {'activityId': 'ACT-002', 'name': 'Handover for loading', 'sequenceNo': 1,
             'enabled': True, 'mandatory': True, 'scanType': 'BAGGAGE',
             'allowOptOut': False, 'prerequisiteActivityIds': ['ACT-001'],
             'restrictToAssignedUsers': True, 'variantOptions': [], 'notes': ''},
            {'activityId': 'ACT-003', 'name': 'Loaded to truck', 'sequenceNo': 2,
             'enabled': True, 'mandatory': True, 'scanType': 'BAGGAGE',
             'allowOptOut': False, 'prerequisiteActivityIds': ['ACT-002'],
             'restrictToAssignedUsers': True, 'variantOptions': [], 'notes': ''},
        ],
    },
    {
        'eventId': 'EVT-BAGUNLOAD',
        'eventName': 'Baggage Unloading',
        'eventType': 'REPEATING',
        'location': 'Destination hotel',
        'sequenceEnforced': True,
        'defaultScanType': 'BAGGAGE',
        'allowSelfService': True,
        'activities': [
            {'activityId': 'ACT-001', 'name': 'Unloaded from truck', 'sequenceNo': 0,
             'enabled': True, 'mandatory': True, 'scanType': 'BAGGAGE',
             'allowOptOut': False, 'prerequisiteActivityIds': [],
             'restrictToAssignedUsers': True, 'variantOptions': [], 'notes': ''},
            {'activityId': 'ACT-002', 'name': 'Sent to room', 'sequenceNo': 1,
             'enabled': True, 'mandatory': False, 'scanType': 'BAGGAGE',
             'allowOptOut': False, 'prerequisiteActivityIds': ['ACT-001'],
             'restrictToAssignedUsers': True, 'variantOptions': [], 'notes': ''},
            {'activityId': 'ACT-003', 'name': 'Dropped at room', 'sequenceNo': 2,
             'enabled': True, 'mandatory': True, 'scanType': 'BAGGAGE',
             'allowOptOut': False, 'prerequisiteActivityIds': ['ACT-002'],
             'restrictToAssignedUsers': True, 'variantOptions': [], 'notes': ''},
        ],
    },
]
```

Per D5/D6, each occurrence created from `EVT-BAGLOAD` for a given date is expected to set `linkedOccurrenceRef` to the matching `EVT-BAGUNLOAD` occurrence for the same date, and vice versa.

## 11. Security, audit, cost

**Security:**
- No new Cognito groups or secrets; all new endpoints reuse the existing JWT authorizer and RBAC layer.
- Hotel and rider data returned by hotel-stay endpoints is limited to fields required by the requesting role; the manual-adjustment screen must never expose editable rider-profile fields (§8.20 contract only accepts stay fields).
- CSV uploads are private, presigned, and retained in S3 for audit exactly like existing artifact uploads (`docs/tour-artifacts-handling-design.md`).

**Audit:**
- Every write endpoint records an actor (`scannedBy`, `updatedBy`, `cancelledBy`, `uploadedBy` equivalents) and a timestamp, consistent with existing `CheckIn`/`Ride` audit fields.
- `EventActivityRecord` cancellation is retained (never deleted) with `cancelledBy`/`cancelledAt`, matching the `CheckIn` cancellation pattern.

**Cost:**
- 5 new on-demand DynamoDB tables per tour; item counts (§5) are all in the low thousands per tour at worst (`EventActivityRecord`), consistent with existing `CheckIn-{tourId}` volumes, so no meaningful cost increase versus the existing table set.
- CSV upload reuses the existing S3 bucket and presigned-URL Lambda pattern — no new AWS service is introduced.

## 12. Backend task list

| # | Task | Acceptance criteria | Dependencies | Affected paths | Phase |
|---|---|---|---|---|---|
| 1 | Add `Permission.EVENT_MANAGE`, `EVENT_OCCURRENCE_MANAGE`, `EVENT_SCAN`, `HOTEL_ALLOC_MANAGE` and update `GROUP_PERMISSIONS`/`PIT_STOP_GROUP_PERMISSIONS` | Matrix in §9.2 reproduced exactly; existing RBAC tests still pass | None | `src/layers/common/rbac.py` | 1 |
| 2 | Add `validate_event_id`, `validate_activity_id`, `validate_occurrence_id`, `validate_hotel_id`, `validate_upload_id` | Regexes match §6 exactly | None | `src/layers/common/validation.py` | 1 |
| 3 | Add table specs for the 5 new tables to provisioning | `PUT /v1/tours/{tourId}/provision` creates missing tables idempotently on a live tour | Task 2 | `src/layers/common/tour_provisioning.py` | 1 |
| 4 | Implement `Event` CRUD handlers | §8.2–8.5 contracts met, including `409 EVENT_ALREADY_EXISTS` | Tasks 1–3 | `src/functions/events/{list,get,create,update}_event.py` | 2 |
| 5 | Implement `EventOccurrence` CRUD + start/complete/cancel handlers | §8.6–8.12 contracts met, including transition guards | Task 4 | `src/functions/events/{list,get,create,update,start,complete,cancel}_occurrence.py` | 2 |
| 6 | Implement activity scan create/cancel handlers | §8.13–8.14 contracts met, including duplicate/prerequisite/sequence/hotel-match checks | Tasks 1, 5 | `src/functions/events/{create,cancel}_activity_record.py` | 2 |
| 7 | Implement `require_event_assignment_access()` helper | §9.3 checks enforced identically to `require_pit_stop_stage_access()` pattern | Task 1 | `src/layers/common/rbac.py` | 2 |
| 8 | Implement dashboard/progress/reconciliation read handlers | §8.15–8.17 contracts met | Task 6 | `src/functions/events/{get_dashboard,get_dashboard_progress,get_rider_progress,get_reconciliation}.py` | 3 |
| 9 | Implement `Hotel` and `HotelStay` CRUD/query handlers | §8.18–8.20 contracts met, including `ROOM_CLASH`/`NON_RECIPROCAL_SHARING` checks | Task 3 | `src/functions/hotels/*.py` | 2 |
| 10 | Implement hotel-stay CSV presign + S3-triggered processor + status poll | §8.21–8.22 contracts met; re-upload for a date replaces rows idempotently | Task 9 | `src/functions/hotels/{presign_upload,get_upload_status}.py`, new S3-triggered processor function | 3 |
| 11 | Extend rider-exit handlers with `baggageDisposition`/baggage release | §8.23 contracts met, including `409 BAGGAGE_NOT_RETAINED` | Task 1 | `src/functions/riders/exit_tour_rider.py`, `cancel_rider_exit.py`, new `release_rider_baggage.py` | 2 |
| 12 | Add `dietaryPreference` to `RiderProfile` create/update handlers | Optional field round-trips; existing profile tests unaffected | None | `src/functions/riders/{create_rider_profile,update_rider_profile}.py` | 1 |
| 13 | Implement bootstrap endpoint | §8.24 contract met, ETag/304 supported | Tasks 4, 5, 9 | `src/functions/events/get_bootstrap.py` | 3 |
| 14 | Write tour-scoped event seed script | Seeds exactly the 3 definitions in §10.2 | Task 4 | `scripts/seed_tour_events.py` | 3 |
| 15 | Update `template.yaml` route registrations for all new Lambda functions | All endpoints in §8.1 routable | Tasks 4–13 | `template.yaml` | 3 |

## 13. Test strategy

**Unit tests** (extending the existing `tests/` pytest + moto suite): validation regexes (Task 2), RBAC matrix additions and `require_event_assignment_access()` (Tasks 1, 7), state-transition guards on occurrences (Task 5), duplicate/prerequisite/sequence checks on activity records (Task 6), room-clash/reciprocal-sharing checks (Task 9).

**Integration tests** (moto-backed, following `test_lambda_functions.py` conventions): full create-event → create-occurrence → start → scan → complete flow; full hotel-upload → presign → processed status flow.

**Named scenarios:**

1. **Released-tag fraud case** — a rider is exited with `baggageDisposition=RELEASED`; a subsequent baggage scan for that rider must be rejected with `409 BAGGAGE_NOT_IN_TOUR`, and the block message must include the rider name and release date (§8.25).
2. **Wrong-hotel-staff scan** — a `HOTEL_STAFF` user assigned to Hotel A attempts to scan a rider whose current-night `HotelStay.hotelId` is Hotel B; must reject with `403 HOTEL_MISMATCH`.
3. **Offline late-sync conflict** — a scan is submitted with a `timestamp` before an occurrence's `completedAt`/rider's `baggageReleasedAt`; must be accepted and flagged (`isFlagged=true`) rather than rejected, per §7.9/§7.10.
4. **CSV expansion and idempotent re-upload** — a CSV with `stayDates` header expands into N `HotelStay` items per row; re-uploading for an overlapping date replaces (not duplicates) that date's rows.
5. **Mandatory-activity completion gating** — an occurrence with an incomplete mandatory activity for one rider can still be force-completed by an ADMINISTRATOR/SUPER_USER, but `outstandingMandatoryCount` in the response is non-zero and the dashboard surfaces it.

## 14. Open risks and future enhancements

- Room-sharing beyond two occupants is out of scope; if a future tour requires triple-sharing, `HotelStay.sharingWith` will need to become a list, which is a breaking schema change for this table.
- The reconciliation model (§8.17) assumes exactly one loading/unloading pair per date; a future multi-leg baggage transfer (for example a mid-route relay point) would need a chained `linkedOccurrenceRef` rather than a single pointer.
- `assignedActivityIds` and `eventAssignments` are both soft, Lambda-enforced config rather than Cognito-native; if activity-level restriction needs to scale beyond a handful of hotel staff per tour, a directory-backed assignment model may be warranted.
