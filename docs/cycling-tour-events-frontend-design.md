# Cycling Tour Events — Frontend Design (`tour-mgmt-app` / `tour-rider-app`)

[← Backend Design](cycling-tour-events-design.md) · [Change Requirement](cycling-tour-events.md)

## 0. Document map

| Document | Owns |
|---|---|
| `docs/cycling-tour-events-design.md` | **Authoritative source** for all shared contracts: endpoint paths, request/response field names, enum values, error codes, permission names, DynamoDB model |
| `docs/cycling-tour-events-frontend-design.md` (this document) | `tour-mgmt-app` (organiser) and `tour-rider-app` (rider) screens, navigation, state management, SQLite offline stores, scan resolution |
| `docs/cycling-tour-events.md` | The frozen change requirement both designs implement |

**Consistency rule:** this document never restates or redefines an endpoint path, field name, enum value, error code, or permission name. Every such value is quoted from the backend design and referenced by section number, e.g. "backend §8.13". Where this document needs to describe backend behaviour, it links to the exact subsection rather than re-describing the rule.

**Assumed backend contract version:** `docs/cycling-tour-events-design.md` as committed alongside this document (design decision register §2, endpoints §8, RBAC §9). Any change to that document's §6/§8/§9 requires this document to be re-checked for drift before either app implements against it.

## 1. Introduction

This document designs the `tour-mgmt-app` and `tour-rider-app` surfaces for the events engine: event/occurrence administration, activity scanning, rider progress, occurrence dashboards, baggage reconciliation, hotel management/allocation, and rider exit with baggage disposition. It is written against each app's actual current architecture (§2) so a developer can start without further discovery.

## 2. Architecture fit

### 2.1 `tour-mgmt-app`

No new architectural layer is introduced. New work slots into the existing structure:

- **Screens:** `src/screens/events/` (new domain folder, alongside `src/screens/{dashboard,checkin,admin,auth}/`)
- **Contexts:** `src/context/EventSessionContext.tsx` (new, §6), alongside existing `AuthContext`, `TourContext`, `RideSessionContext`, `NameDirectoryContext`, `OfflineContext`
- **API services:** `src/services/api/eventsApi.ts`, `hotelsApi.ts` (new), following `checkInApi.ts`'s pattern of typed request/response + `apiClient`/`ApiError` + discriminated-union outcomes
- **SQLite stores:** `src/services/database/eventStore.ts`, `eventRecordStore.ts`, `hotelStayStore.ts` (new), following `checkInStore.ts`
- **Types:** additions to `src/types/api.ts` (request/response shapes) and `src/types/models.ts` (new `Permission` enum members, §8.1)
- **Navigation:** additions to `src/types/navigation.ts` and `src/navigation/AppNavigator.tsx` (§3)
- **Scan resolution:** generalisation of `src/services/idcode/idCodeService.ts` (§8)

### 2.2 `tour-rider-app`

Scope is intentionally tight: `dietaryPreference` self-service, the rider's own event/baggage status visibility, and offline-safe reads. It consumes `RiderApi`, not `TourDataApi`, mirroring the existing separation already used for rider-facing endpoints (for example the existing rider-profile and rider-tour-participation calls). No scanning UI is added to `tour-rider-app`.

### 2.3 Project-structure delta

In the style of `docs/project-structure.md`, the following additions apply to `tour-mgmt-app`:

```
tour-mgmt-app/
├── src/
│   ├── screens/
│   │   └── events/                       # New domain folder
│   │       ├── EventDefinitionListScreen.tsx
│   │       ├── EventDefinitionEditorScreen.tsx
│   │       ├── OccurrenceManagementScreen.tsx
│   │       ├── EventScanScreen.tsx
│   │       ├── RiderProgressScreen.tsx
│   │       ├── OccurrenceDashboardScreen.tsx
│   │       ├── BaggageReconciliationScreen.tsx
│   │       ├── HotelManagementScreen.tsx
│   │       ├── HotelAllocationUploadScreen.tsx
│   │       └── HotelAllocationAdjustScreen.tsx
│   ├── context/
│   │   └── EventSessionContext.tsx       # New, mirrors RideSessionContext
│   ├── services/
│   │   ├── api/
│   │   │   ├── eventsApi.ts              # New
│   │   │   └── hotelsApi.ts              # New
│   │   └── database/
│   │       ├── eventStore.ts             # New
│   │       ├── eventRecordStore.ts       # New
│   │       └── hotelStayStore.ts         # New
```

## 3. Navigation design

### 3.1 New `AppStackParamList` routes

Added to `src/types/navigation.ts`, following the existing route param convention:

| Route | Params | Placement | Conditional registration |
|---|---|---|---|
| `EventDefinitionList` | none | Stack (from `TourManagement`) | `isAdministrator` |
| `EventDefinitionEditor` | `{ eventId?: string }` (absent = create) | Stack | `isAdministrator` |
| `OccurrenceManagement` | `{ eventId: string }` | Stack | `hasPermission(role, Permission.EVENT_OCCURRENCE_MANAGE)` (§8.1 mapping) |
| `EventScan` | `{ eventId: string; occurrenceId: string }` | Stack, pushed from `MainTabs` or `OccurrenceManagement` | `hasPermission(role, Permission.EVENT_SCAN)` |
| `RiderProgress` | `{ riderId: string }` | Stack | any authenticated user with `Permission.READ` |
| `OccurrenceDashboard` | `{ eventId: string; occurrenceId: string }` | Stack | `Permission.DASHBOARD` |
| `BaggageReconciliation` | `{ occurrenceId: string }` | Stack | `Permission.DASHBOARD` |
| `HotelManagement` | none | Stack, from `TourManagement` | `isAdministrator` |
| `HotelAllocationUpload` | none | Stack, `onClose` modal-style | `hasPermission(role, Permission.HOTEL_ALLOC_MANAGE)` |
| `HotelAllocationAdjust` | `{ riderId: string; stayDate: string }` | Stack, `onClose` modal-style | `hasPermission(role, Permission.HOTEL_ALLOC_MANAGE)` |

All new routes are registered in `AppStackParamList` inside the same conditional block already used for `TourManagement`/`UserOnboarding`, gated per the table above rather than solely on `isAdministrator`, since `EVENT_OCCURRENCE_MANAGE`, `EVENT_SCAN`, and `HOTEL_ALLOC_MANAGE` are also held by `SUPER_USER`/`HOTEL_STAFF`/pit-stop roles per backend §9.2.

### 3.2 Tab vs. stack placement

`EventScan` is reachable from `MainTabs` (a new "Events" tab entry, alongside the existing check-in tab) for day-to-day scanning, and also pushed from `OccurrenceManagement` for organisers jumping straight from occurrence setup to scanning. All other new routes are stack-only, matching the existing pattern where administrative screens are not tabs.

### 3.3 Route wrapper components

Following the existing `XxxRoute({ route, navigation })` pattern in `src/navigation/AppNavigator.tsx`:

```tsx
function EventScanRoute({ route, navigation }: AppStackScreenProps<'EventScan'>) {
  const { eventId, occurrenceId } = route.params;
  return <EventScanScreen eventId={eventId} occurrenceId={occurrenceId} navigation={navigation} />;
}
```

Each new screen gets an equivalent wrapper; wrappers do no logic beyond destructuring route params and passing `navigation` through, matching every existing wrapper in the file.

## 4. Screen-by-screen design

### 4.1 Event Definition list and editor (ADMINISTRATOR)

**Purpose:** Manage `Event` definitions (backend §5.1) and their embedded activity list.

**Permissions:** `EVENT_MANAGE` (backend §9.2) — list screen link only rendered when `isAdministrator`.

**List screen layout (prose):** Header "Event Definitions" with a "+ New Event" action. Below, a scrollable list of cards, one per event: `eventName`, `eventType` badge (`SINGLE`/`REPEATING`), `location`, and activity count. Tapping a card navigates to `EventDefinitionEditor` with `eventId`.

**Editor screen layout:** Top section — event-level fields (`eventName`, `eventType`, `location`, `sequenceEnforced` toggle, `defaultScanType` picker, `allowSelfService` toggle). Below — an ordered, drag-reorderable list of activity rows, each showing `name`, `sequenceNo`, `enabled`/`mandatory`/`allowOptOut` toggles, `scanType` picker, `prerequisiteActivityIds` multi-select (restricted to earlier activities), `restrictToAssignedUsers` toggle (defaults `true` per backend D15), and `variantOptions` chip-input. A "+ Add Activity" row is appended at the end. Save button posts the full definition (backend §8.4/§8.5).

**States:** loading (skeleton cards), empty (list screen shows "No events yet" + CTA), error (`StatusMessage kind: 'error'` with retry), offline (banner: "Event definitions require a connection to edit" — definitions are never offline-editable, §7.8), permission-denied (screen not reachable — route hidden per §3.1).

**Validation messages:** "Activity name is required.", "At least one activity is required.", "Prerequisite activities must come before this activity in sequence.", "Variant options require at least two values." — all client-side pre-checks mirroring backend `400 VALIDATION_ERROR` (backend §8.25); server error messages are surfaced verbatim on top of these when the API rejects.

**API calls:** `GET`/`POST`/`PUT` per backend §8.2–§8.5.

**Navigation:** in from `TourManagement`; out via back button or successful save (pops to list).

### 4.2 Occurrence management (ADMINISTRATOR + SUPER_USER)

**Purpose:** Create/manage `EventOccurrence` instances (backend §5.2) for a given event.

**Permissions:** `EVENT_OCCURRENCE_MANAGE` (backend §9.2).

**Layout:** A **read-only definition header** at the top of the screen — `eventName`, `location`, `sequenceEnforced`, and the activity list rendered as read-only chips (name + mandatory/enabled state only, no editing controls; per finding 1 the definition is never edited from this screen). Below the header, a list of occurrences for the event, each row showing `date`, `seq`, `status` badge, and action buttons appropriate to state: `Start` (when `PLANNED`), `Complete`/`Cancel` (when `ACTIVE`). A "+ New Occurrence" action opens a small form for `date` + `seq`. Each occurrence row also exposes a "Disabled activities" chip-toggle set and a "Self-service" switch, both writing to `disabledActivityIds`/`selfServiceEnabled` (backend §8.9).

**States:** loading, empty ("No occurrences yet for this event"), error, offline (occurrence create/start/complete/cancel are online-only administrative actions — banner shown, actions disabled), permission-denied (route hidden).

**Interactions:** tapping `Start`/`Complete`/`Cancel` shows a confirmation dialog before calling backend §8.10/§8.11/§8.12; `Complete` confirmation surfaces `outstandingMandatoryCount` from the response if non-zero, e.g. "3 riders have outstanding mandatory activities. Complete anyway?".

**API calls:** backend §8.6–§8.12.

**Navigation:** in from `EventDefinitionList` (admin) or a dedicated "Occurrences" entry point; out via back; each occurrence row's "Scan" action pushes `EventScan`.

### 4.3 Event Scan screen

**Purpose:** Record `EventActivityRecord` scans (backend §5.3, §8.13). Modelled directly on `CheckInScreen.tsx`.

**Permissions:** `EVENT_SCAN` (backend §9.2), further narrowed by the second authorisation layer (backend §9.3) — a denied scan surfaces the exact `RIDER_NOT_ASSIGNED`/`HOTEL_MISMATCH` message from backend §8.25.

**Layout (3-section, matching `CheckInScreen`):**

1. **Activity selector + scanner.** An activity picker (chips or dropdown) restricted to `enabled` activities not in the occurrence's `disabledActivityIds`; the currently selected activity determines the allowed ID Code type(s) passed to `resolveScannedRiderId()` (§8.1). Below, the camera scanner (mounted only `useIsFocused`, via `useCameraPermissions`) plus a manual-entry fallback field, matching `CheckInScreen`'s pattern exactly.
2. **Confirmation card.** Shows resolved rider name/photo, the selected activity, an auto-submit toggle, and scan-cooldown behaviour identical to `CheckInScreen` (`processingRef`/`scanCooldownUntilRef` guards, `playScanTick` on scan, `playSuccess`/`playFailure` on outcome). When the activity has `variantOptions`, a variant prompt (radio buttons, e.g. VEG/NON_VEG) appears before submit and defaults to the rider's `dietaryPreference` if the API returns it via the bootstrap payload (backend §8.24). When the activity has `allowOptOut=true`, an "Opt out" secondary action is shown alongside the primary "Confirm" action, submitting `outcome: "OPTED_OUT"`.
3. **Rolling recent-log.** Last N scans for this occurrence, newest first, showing rider name, activity, outcome, and a "cancel" affordance calling backend §8.14 with a confirmation dialog.

**States:** loading (initial occurrence/activity fetch), empty (occurrence has no enabled activities — should not occur given seed config, but handled defensively), error, offline (scans still permitted — see §7 offline design; a per-scan "queued" badge is shown instead of blocking), permission-denied (`RIDER_NOT_ASSIGNED`/`HOTEL_MISMATCH` rendered via `StatusMessage kind: 'error'` with no retry action, since retrying with the same user will not succeed), blocked-scan (`BAGGAGE_NOT_IN_TOUR` rendered via `StatusMessage kind: 'warning'` including the rider name and release date exactly as returned by backend §8.25, with a secondary "Escalate" action that simply surfaces a contact-admin hint — no override control is offered on this screen).

**Duplicate/prerequisite messages:** `409 DUPLICATE_ACTIVITY_RECORD` → "This activity has already been recorded for this rider." (verbatim from backend §8.25); `409 PREREQUISITE_NOT_MET` → "Complete the required prior activity before this one."; both rendered as `StatusMessage kind: 'info'` since they represent an expected flow outcome, not a system error — matching the `CheckInScreen` treatment of expected 409s as flows (§8 scan resolution outcome union).

**API calls:** backend §8.13/§8.14; activity/occurrence metadata from backend §8.6/§8.7.

**Navigation:** in from `MainTabs` "Events" tab or from `OccurrenceManagement`; out via back button (no destructive confirmation needed, scans are already persisted/queued).

### 4.4 Rider progress Stepper / Progress Tracker

**Purpose:** Show one rider's per-activity completion across an occurrence (or across all events, for the rider-app equivalent), in the agreed stepper UI style.

**Layout:** A vertical stepper, one node per activity in `sequenceNo` order, each node labelled with the activity name and a status icon: pending (hollow circle), completed (filled check), opted-out (dash), blocked (lock icon — prerequisite/sequence not yet satisfied), offline-queued (clock icon, §7). Tapping a completed node shows the record's `scannedBy`/`timestamp` in a tooltip/sheet.

**States:** loading, error, offline (offline-queued nodes render distinctly, §7), permission-denied (not applicable — any `READ` holder may view).

**API calls:** backend §8.16.

**Navigation:** in from `RiderCardModal` (existing component, reused per §5) "View event progress" action, or from `OccurrenceDashboard` drill-down; out via close/back.

### 4.5 Occurrence dashboard

**Purpose:** Aggregate counts for one occurrence: completed, outstanding mandatory, opted-out, and (for baggage occurrences) reconciliation variance.

**Permissions:** `DASHBOARD` (backend §9.2).

**Layout:** Header repeats the occurrence's `date`/`seq`/`status`. Count tiles: total riders, completed, outstanding mandatory (tappable → filtered rider list), opted-out. For baggage occurrences with a `linkedOccurrenceRef`, an additional "Reconciliation" tile shows "{loadedCount} loaded vs {unloadedCount} unloaded" with a drill-down to `BaggageReconciliationScreen` when variance is non-zero.

**States:** loading, empty (occurrence has no records yet), error, offline (dashboard is a read screen — served from the last synced snapshot with a "stale data" banner showing last-refresh time, §7).

**API calls:** backend §8.15 (`/dashboard` for full detail on drill-down, `/dashboard/progress` for the lightweight polling refresh).

**Navigation:** in from `OccurrenceManagement` row action or `MainTabs`; out via back; drill-downs push `RiderProgress` or `BaggageReconciliation`.

### 4.6 Baggage reconciliation view

**Purpose:** Compare a Baggage Loading occurrence against its paired Baggage Unloading occurrence via `linkedOccurrenceRef` (backend §5.2, §8.17).

**Layout:** Two-column summary (Loaded / Unloaded) with counts, followed by a list of `missingRiderIds` — riders whose bag was loaded but not yet unloaded — each row showing rider name and a "contact" affordance (reuses existing rider-contact patterns from check-in screens).

**States:** loading, empty ("No variance — all bags accounted for"), error (including `400 NO_LINKED_OCCURRENCE` rendered as "This occurrence has no linked occurrence to reconcile against."), offline (read-only from last synced snapshot).

**API calls:** backend §8.17.

**Navigation:** in from `OccurrenceDashboard` drill-down; out via back.

### 4.7 Hotel management (CRUD)

**Purpose:** Manage `Hotel-{tourId}` master data (backend §5.4).

**Permissions:** `HOTEL_ALLOC_MANAGE` (backend §9.2).

**Layout:** List of hotel cards (`name`, `city`) with "+ New Hotel" action; tapping opens an editor form for `name`, `city`, `address`, `contact`, `notes`.

**States:** loading, empty, error, offline (hotel CRUD is online-only administrative action, banner + disabled form), permission-denied (route hidden).

**Validation:** "Hotel name is required.", "City is required." — client pre-checks; server `409 HOTEL_ALREADY_EXISTS` surfaced verbatim.

**API calls:** backend §8.18.

### 4.8 Hotel allocation CSV upload

**Purpose:** Bulk-load `HotelStay` records via the S3 presigned-upload + async-processing flow (backend §8.21/§8.22, design decision D11).

**Layout (`onClose` modal-style, matching admin screen convention):** File-pick button (native document picker), selected-file name display, "Upload" action. On upload: progress bar tracking the S3 `PUT`, then a "Processing…" spinner while polling. On completion: summary ("{successCount} of {rowCount} rows applied") and, if `errorCount > 0`, a row-level error table with columns Row, Code, Message — each row number mapped directly back to the source CSV so the organiser can locate and fix it, plus a "Retry" action that re-opens the file picker for a corrected file.

**Flow detail:**
1. Screen calls backend §8.21 to get `{ uploadId, uploadUrl, s3Key, expiresIn }`.
2. App performs the S3 `PUT` of the picked CSV file to `uploadUrl`, tracking progress via the HTTP client's upload-progress callback.
3. App polls backend §8.22 with the returned `uploadId` on a fixed interval (e.g. every 3s) until `status` is `COMPLETED` or `FAILED`, capped at a maximum poll duration with a "still processing — check back later" fallback message.
4. Errors are rendered from the `errors[]` array in the poll response, each `{ row, code, message }` mapped 1:1 to a table row.

**States:** loading (initial presign call), uploading (progress bar), processing (poll spinner), error (presign failure, S3 PUT failure, or `FAILED` status), offline (upload is online-only — screen shows "Connect to the internet to upload hotel allocations" and disables the file picker).

**API calls:** backend §8.21/§8.22.

### 4.9 Manual hotel allocation adjustment

**Purpose:** Single-night edit of one rider's `HotelStay` (backend §8.20).

**Layout:** A **read-only rider profile display** at the top (name, photo, `riderId` — per finding 1/finding 15, rider profile fields are never editable here), followed by an editable form for `hotelId` (picker), `roomNo`, and `sharingWith` (rider picker, optional) for the single `stayDate` passed via route params. A **room-clash warning** banner appears inline the moment the chosen `hotelId`+`roomNo` combination is already occupied by a non-reciprocal rider for that date (client-side pre-check against the cached `hotelStayStore`, backed by a final server-side check on save).

**States:** loading, error, offline (edit is online-only administrative action; if a cached room-clash check cannot be performed offline because the local cache is stale, the warning is suppressed and a "verify online before saving" note is shown instead), permission-denied (route hidden).

**Validation messages:** "Room number is required.", room-clash banner text: "Room {roomNo} at {hotelName} is already allocated to {otherRiderName} on {stayDate}." (mirrors backend `409 ROOM_CLASH` message, backend §8.25), "The paired rider does not confirm this room sharing." (mirrors `409 NON_RECIPROCAL_SHARING`).

**API calls:** backend §8.20; hotel list from §8.18; existing stays from §8.19 (by-hotel query) for clash pre-checking.

**Navigation:** in from `HotelManagementScreen` room-wise view or from a rider's `RiderCardModal`; out via `onClose`.

### 4.10 Rider exit with mandatory baggage disposition

**Purpose:** Extend the existing rider-exit screen/flow to require `baggageDisposition` (backend §8.23).

**Layout:** The existing exit confirmation dialog gains a mandatory radio choice: "Baggage retained by organisers" (`RETAINED`) or "Baggage already released" (`RELEASED`), with the Confirm button disabled until one is chosen. Submitting without a choice is prevented client-side; if somehow submitted, the server's `400 BAGGAGE_DISPOSITION_REQUIRED` message ("Choose whether baggage is retained or released before exiting this rider.") is shown.

**Exit cancellation:** the existing cancel-exit action is unchanged in the UI; it now also restores `baggageStatus` server-side (backend §8.23) with no additional client UI required.

**Baggage release:** a new action on the rider detail screen, visible only when `baggageStatus=RETAINED`, labelled "Release retained baggage", with a confirmation dialog and optional note field (maps to `note` in backend §8.23). Disabled with a tooltip when `baggageStatus` is not `RETAINED` (server would reject with `409 BAGGAGE_NOT_RETAINED`).

**API calls:** backend §8.23.

### 4.11 Extensions to existing user management screens

`UserOnboarding`/`UserModify` screens gain two new optional fields when creating/editing a `User-{tourId}` record: a `hotelId` picker (for `HOTEL_STAFF` users, backend §5.7) and an `eventAssignments` editor (multi-select of event + date-range/`"ALL"` pairs, backend §5.7). Both are rendered only when the target role is one that can hold `EVENT_SCAN`/`EVENT_OCCURRENCE_MANAGE` (ADMINISTRATOR, SUPER_USER, PS_\<n\>_USER, HOTEL_STAFF), matching the existing pattern of conditionally shown fields based on selected role.

## 5. Component design

Reusable components introduced:

- **`ActivityStepper`** — props: `activities: { activityId, name, status }[]`, `onNodePress?`. Used by §4.4 and reusable inside §4.2's read-only header (rendered without status icons, activity list only).
- **`ScanConfirmationCard`** — props mirror the existing check-in confirmation card component but add `variantOptions?`, `allowOptOut`, `onOptOut?`. Extracted from `CheckInScreen`'s inline confirmation card if not already a standalone component, so both check-in and event scanning share one implementation.
- **`RowErrorTable`** — props: `errors: { row, code, message }[]`. Used only by §4.8.
- **`ReadOnlyProfileHeader`** — props: `riderId, name, photoUrl`. Used by §4.9 and reusable wherever a read-only rider identity strip is needed.

Existing components reused as-is: `RiderCardModal` (extended with a new "View event progress" action linking to §4.4, and a "Release baggage" action linking to §4.10), the existing `StatusMessage` component (`kind: 'error' | 'info' | 'warning'`), and `COLORS`/`QR_SCANNER_COLORS` from `src/constants/colors.ts` for all new scan-related UI.

## 6. State management

### 6.1 `EventSessionContext`

Mirrors `RideSessionContext`'s shape and responsibilities:

```ts
interface EventSessionContextValue {
  selectedEventId: string | null;
  selectedOccurrenceId: string | null;
  selectedActivityId: string | null;
  cachedRecords: EventActivityRecord[];       // records for the current occurrence, kept in sync with SQLite
  setSelection: (eventId: string, occurrenceId: string, activityId?: string) => void;
  clearSelection: () => void;
  refreshCachedRecords: () => Promise<void>;
}
```

**Justification:** `EventScanScreen`, `OccurrenceDashboardScreen`, and `RiderProgressScreen` all need the currently-selected event/occurrence/activity without prop-drilling through navigation params alone, exactly the problem `RideSessionContext` already solves for ride/stage selection. Keeping it a distinct context (rather than folding into `RideSessionContext`) preserves the existing context's single responsibility and avoids coupling ride check-in state to event state, which have independent lifecycles (a ride and an event occurrence are not the same entity and can be active simultaneously).

**Interaction with existing contexts:** `EventSessionContext` reads the current tour from `TourContext` (for API base tour scoping) and reads connectivity from `OfflineContext` to decide whether `refreshCachedRecords()` hits the network or reads SQLite only. It does not depend on `RideSessionContext` or `NameDirectoryContext` directly, though `EventScanScreen` separately consumes `NameDirectoryContext` to resolve rider names for display, exactly as `CheckInScreen` does today.

## 7. Offline design

### 7.1 SQLite DDL

Following `checkInStore.ts`'s pattern (table + `pending_operations` queue entries):

```sql
-- eventStore.ts
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY,
  event_name TEXT NOT NULL,
  event_type TEXT NOT NULL,
  location TEXT,
  sequence_enforced INTEGER NOT NULL,
  default_scan_type TEXT,
  allow_self_service INTEGER NOT NULL,
  activities_json TEXT NOT NULL,   -- serialized activities[] array, backend §5.1
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_occurrences (
  occurrence_id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL,
  date TEXT NOT NULL,
  seq INTEGER NOT NULL,
  status TEXT NOT NULL,
  disabled_activity_ids_json TEXT,
  self_service_enabled INTEGER,
  linked_occurrence_ref TEXT,
  updated_at TEXT NOT NULL
);

-- eventRecordStore.ts
CREATE TABLE IF NOT EXISTS event_activity_records (
  record_id TEXT PRIMARY KEY,
  occurrence_id TEXT NOT NULL,
  activity_id TEXT NOT NULL,
  activity_name TEXT NOT NULL,
  rider_id TEXT NOT NULL,
  type_code TEXT,
  bag_label TEXT,
  outcome TEXT NOT NULL,
  variant_selected TEXT,
  method TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  synced INTEGER NOT NULL DEFAULT 0,
  is_flagged INTEGER NOT NULL DEFAULT 0
);

-- hotelStayStore.ts
CREATE TABLE IF NOT EXISTS hotel_stays (
  stay_date TEXT NOT NULL,
  rider_id TEXT NOT NULL,
  hotel_id TEXT NOT NULL,
  room_no TEXT,
  sharing_with TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (stay_date, rider_id)
);
```

### 7.2 Write-local-first flow

`eventRecordStore.ts` writes a new activity record to SQLite immediately (marking `synced=0`) and enqueues a `pending_operations` entry with `operationType: 'CREATE_EVENT_ACTIVITY_RECORD'` and the full request payload, following `checkInStore.ts`'s exact pattern. The scan screen reflects the local write immediately (optimistic UI, recent-log entry appears at once with a "queued" indicator when offline).

### 7.3 `pending_operations` integration

Event activity record creation and cancellation share the same `pending_operations` queue and `src/services/sync/syncService.ts` outbound timer as check-ins; no new queue or sync loop is introduced. The outbound sync handler dispatches on `operationType`, adding two new cases (`CREATE_EVENT_ACTIVITY_RECORD`, `CANCEL_EVENT_ACTIVITY_RECORD`) alongside the existing check-in cases, each calling backend §8.13/§8.14 respectively.

### 7.4 Conflict and late-sync handling

When an outbound sync for a queued scan returns `409 OCCURRENCE_NOT_ACTIVE` or `409 BAGGAGE_NOT_IN_TOUR`, the sync service does not silently drop the record: per backend §7.9/§7.10, the server itself decides whether a late `timestamp` is accepted-but-flagged (`isFlagged=true` in the response) or rejected outright. On success (including flagged-success), the local record is marked `synced=1`, `is_flagged` set from the response. On a hard rejection, the record is marked with a local `sync_error` state and surfaced in a "sync issues" list on the recent-log screen for organiser review, mirroring how check-in sync failures are already surfaced.

### 7.5 Bootstrap payload and refresh triggers

After sign-in, the app calls backend §8.24 (`GET /v1/tours/{tourId}/events/bootstrap`) and writes the response into `eventStore`, `hotelStayStore` (today's stays only), and a lightweight in-memory rider `baggageStatus` map. Critically, `riderBaggageStatus` (including `baggageReleasedAt`) is included so the `BAGGAGE_NOT_IN_TOUR` block (§4.3) works fully offline without a per-scan network call. Refresh triggers: app foreground after being backgrounded > 5 minutes, pull-to-refresh on the Events tab, and successful completion of any outbound sync batch (to pick up server-side state changes made by other users).

### 7.6 Offline indicators

The existing `OfflineContext`-driven banner pattern is reused; the Events tab and `EventScanScreen` additionally show a small "queued" badge count (number of unsynced local records) sourced from `eventRecordStore`.

### 7.7 What is deliberately not available offline

- Event definition create/edit (§4.1) — administrative, low-frequency, requires a connection.
- Occurrence create/start/complete/cancel (§4.2) — state-changing administrative actions that must be authoritative and are not expected to happen in the field without connectivity.
- Hotel CRUD (§4.7) and CSV upload (§4.8) — administrative, office-based tasks.
- Manual hotel allocation adjustment save (§4.9) — requires a live room-clash check against the server; a stale local cache cannot safely authorise this write.
- Occurrence dashboard and reconciliation (§4.5, §4.6) are offline-**readable** from the last synced snapshot but never offline-**writable**.

Activity scanning itself (§4.3) is the one write path designed to be fully offline-capable, because it happens in the field (hotel lobbies, truck yards) where connectivity is unreliable — matching the existing rationale for offline check-ins.

## 8. Scan resolution

### 8.1 Generalised `resolveScannedRiderId()`

Current signature (RIDER-only, hardcoded):

```ts
function resolveScannedRiderId(qrText: string): ScanResolution
```

**New, backwards-compatible signature:**

```ts
function resolveScannedRiderId(
  qrText: string,
  allowedTypes: IdCodeType[] = ['RIDER'],
): ScanResolution
```

- The `allowedTypes` parameter defaults to `['RIDER']`, so every existing call site (check-in flows) compiles and behaves identically without modification — **no existing call site needs to change**.
- On success, the return shape becomes `{ riderId: string; typeCode: string; bagLabel?: string }`, a superset of the current `{ riderId }` shape, so existing callers destructuring only `riderId` are unaffected.
- New reason codes added to the `ScanResolution` discriminated union alongside the existing `INVALID_QR | INVALID_TYPE | RIDER_NOT_FOUND`:
  - `TYPE_NOT_ALLOWED_FOR_EVENT` — the scanned type code is valid per `AppConfig` `ID_CODE_TYPE` (backend `docs/idcode-backend-api-change-request.md` §3) but is not in the caller-supplied `allowedTypes`.
- New message constants added to `src/constants/idCodes.ts` alongside `ERR_INVALID_ID_TYPE`, `ERR_INVALID_QR`, `ERR_RIDER_NOT_FOUND`:
  - `ERR_TYPE_NOT_ALLOWED_FOR_EVENT` — "This ID Code type ({bagLabel}) is not allowed for this activity. Allowed types: {allowedTypesList}." The message explicitly names both the disallowed scanned type and the allowed types for the event, per the change requirement (`cycling-tour-events.md` §5).
- The existing `INVALID_TYPE` reason (used when `allowedTypes=['RIDER']` and a non-RIDER code is scanned) keeps its exact current message (`ERR_INVALID_ID_TYPE`) for check-in call sites — the new `TYPE_NOT_ALLOWED_FOR_EVENT` reason is only returned when `allowedTypes` was explicitly widened by a caller (i.e. an event-scanning call site), so check-in behaviour is provably unchanged.
- Legacy dev format gating via `EXPO_PUBLIC_QR_DEV_FORMAT` is unaffected — it governs QR text parsing, not the new type-filtering step, which happens after `idCode`/`typeCode`/`personalCode` extraction.

### 8.2 Per-activity allowed-type flow

`EventScanScreen` (§4.3) computes `allowedTypes` from the selected activity's `scanType` (backend §5.1: `RIDER` or `BAGGAGE`). Because `BAGGAGE` covers type codes `3`–`8` (backend §6 / `docs/idcode-backend-api-change-request.md` §3), the screen passes the full set of currently-enabled `BAGGAGE`-typed `ID_CODE_TYPE` config entries (fetched via the existing `GET /v1/config` call) as `allowedTypes` when the activity's `scanType` is `BAGGAGE`, and `['RIDER']` when it is `RIDER`. On a successful resolution, `{ riderId, typeCode, bagLabel }` is passed directly into the activity-record submission (backend §8.13 request body).

## 9. Error and message catalogue

Every backend error code from backend §8.25 maps to a user-facing message. Where the backend message already contains user-facing text (e.g. `BAGGAGE_NOT_IN_TOUR`), it is rendered verbatim; otherwise, the app supplies a message consistent with existing `StatusMessage` tone:

| Backend code (§8.25) | App message | `StatusMessage kind` |
|---|---|---|
| `EVENT_NOT_FOUND` | "Event not found." | error |
| `EVENT_ALREADY_EXISTS` | "An event with this ID already exists." | error |
| `OCCURRENCE_NOT_FOUND` | "Occurrence not found." | error |
| `OCCURRENCE_ALREADY_EXISTS` | "An occurrence already exists for this date and sequence." | error |
| `OCCURRENCE_CLOSED` | "This occurrence is closed and cannot be edited." | error |
| `INVALID_OCCURRENCE_TRANSITION` | "This occurrence cannot be transitioned from its current status." | error |
| `NO_LINKED_OCCURRENCE` | "This occurrence has no linked occurrence to reconcile against." | info |
| `ACTIVITY_NOT_FOUND` | "Activity not found or disabled for this occurrence." | error |
| `SCAN_TYPE_NOT_ALLOWED` | (see §8.1 `ERR_TYPE_NOT_ALLOWED_FOR_EVENT`) | warning |
| `DUPLICATE_ACTIVITY_RECORD` | "This activity has already been recorded for this rider." | info |
| `PREREQUISITE_NOT_MET` | "Complete the required prior activity before this one." | info |
| `OCCURRENCE_NOT_ACTIVE` | "This occurrence is not currently open for scanning." | warning |
| `BAGGAGE_NOT_IN_TOUR` | verbatim from server (includes rider name + release date) | warning |
| `RIDER_NOT_ASSIGNED` | "You are not assigned to this event today." | error |
| `HOTEL_MISMATCH` | "This rider is not staying at your assigned hotel tonight." | error |
| `HOTEL_NOT_FOUND` | "Hotel not found." | error |
| `HOTEL_ALREADY_EXISTS` | "A hotel with this ID already exists." | error |
| `ROOM_CLASH` | verbatim from server | warning |
| `NON_RECIPROCAL_SHARING` | verbatim from server | warning |
| `UPLOAD_NOT_FOUND` | "Upload not found." | error |
| `BAGGAGE_DISPOSITION_REQUIRED` | verbatim from server | error |
| `BAGGAGE_NOT_RETAINED` | "Baggage is not currently retained for this rider." | error |
| `RECORD_NOT_FOUND` | "Activity record not found." | error |
| `RECORD_ALREADY_CANCELLED` | "This activity record has already been cancelled." | info |

## 10. `tour-mgmt-app` task list

| # | Task | Acceptance criteria | Dependencies | Affected paths | Phase |
|---|---|---|---|---|---|
| 1 | Add new `AppStackParamList` routes + route wrappers | All §3.1 routes registered and conditionally gated | Backend §9.1 permissions shipped | `src/types/navigation.ts`, `src/navigation/AppNavigator.tsx` | 1 |
| 2 | Add new `Permission` enum members + `hasPermission` mapping | App-side `Permission` enum documents the mapping to backend permission names (§8.1 of backend design's RBAC naming) | Backend §9.1 | `src/types/models.ts`, `src/utils/permissions.ts` | 1 |
| 3 | Implement `eventsApi.ts`/`hotelsApi.ts` | Typed request/response for every endpoint in backend §8.1; `ApiError` + outcome unions for expected 409s | Task 2 | `src/services/api/{eventsApi,hotelsApi}.ts`, `src/types/api.ts` | 1 |
| 4 | Generalise `resolveScannedRiderId()` | Signature and behaviour exactly per §8.1; existing check-in tests unaffected | None | `src/services/idcode/idCodeService.ts`, `src/constants/idCodes.ts` | 1 |
| 5 | Implement `eventStore.ts`, `eventRecordStore.ts`, `hotelStayStore.ts` | DDL per §7.1; write-local-first + `pending_operations` integration | Task 3 | `src/services/database/*.ts` | 2 |
| 6 | Implement `EventSessionContext` | Shape per §6.1 | Task 5 | `src/context/EventSessionContext.tsx` | 2 |
| 7 | Build Event Definition list/editor screens | §4.1 states/validation implemented | Tasks 1–3 | `src/screens/events/EventDefinition*.tsx` | 2 |
| 8 | Build Occurrence management screen | §4.2, including read-only definition header | Tasks 1–3, 6 | `src/screens/events/OccurrenceManagementScreen.tsx` | 2 |
| 9 | Build Event Scan screen | §4.3, reusing/extracting `ScanConfirmationCard` | Tasks 1–6 | `src/screens/events/EventScanScreen.tsx` | 3 |
| 10 | Build Rider Progress stepper | §4.4 | Tasks 1–3 | `src/screens/events/RiderProgressScreen.tsx`, `ActivityStepper` component | 3 |
| 11 | Build Occurrence dashboard + Baggage reconciliation screens | §4.5, §4.6 | Tasks 1–3 | `src/screens/events/{OccurrenceDashboard,BaggageReconciliation}Screen.tsx` | 3 |
| 12 | Build Hotel management, upload, and manual-adjustment screens | §4.7–§4.9 | Tasks 1–5 | `src/screens/events/Hotel*.tsx` | 3 |
| 13 | Extend rider-exit UI with baggage disposition + release action | §4.10 | Task 3 | existing rider-exit screen/component | 2 |
| 14 | Extend user management screens with `hotelId`/`eventAssignments` fields | §4.11 | Task 3 | existing `UserOnboarding`/`UserModify` screens | 3 |
| 15 | Sync service integration | §7.3/§7.4 new operation types handled by outbound/inbound timers | Task 5 | `src/services/sync/syncService.ts` | 2 |

## 11. `tour-rider-app` task list

| # | Task | Acceptance criteria | Dependencies | Phasing |
|---|---|---|---|---|
| 1 | Add `dietaryPreference` self-service field to rider profile screen | Field round-trips via `RiderApi` rider-profile update call; optional, defaults empty | Backend Task 12 | 1 |
| 2 | Add rider's own event/baggage status visibility screen | Read-only view of the rider's own activity progress (backend §8.16) and `baggageStatus` | Backend §8.16 | 2 |
| 3 | Offline-safe read caching | Bootstrap-equivalent rider payload cached locally; screen renders from cache when offline | Task 2 | 2 |

## 12. Frontend test strategy

**Unit:** `resolveScannedRiderId()` backwards-compatibility (existing `['RIDER']` behaviour byte-for-byte unchanged) and new `TYPE_NOT_ALLOWED_FOR_EVENT` path; `hasPermission` mapping for the four new backend permissions; SQLite DDL migration idempotency.

**Component:** `EventScanScreen` state rendering for each state in §4.3 (loading/empty/error/offline/permission-denied/blocked-scan); `OccurrenceManagementScreen` read-only header rendering (activities must not be editable from this screen); room-clash banner rendering in `HotelAllocationAdjustScreen`.

**Manual QA scenarios:** end-to-end scan of all 5 Day-0-Registration activities for one rider including a variant choice and an opt-out; end-to-end Baggage Loading → Baggage Unloading with one bag deliberately withheld to verify the reconciliation drill-down; wrong-hotel-staff scan producing the exact `HOTEL_MISMATCH` message; airplane-mode scan followed by reconnection and successful sync; CSV upload with a deliberately malformed row producing a row-mapped error.

## 13. Accessibility and field-usability notes

- All scan-confirmation primary actions use large touch targets (minimum 48dp) for gloved use in cool early-morning starts.
- `QR_SCANNER_COLORS` high-contrast palette is reused as-is for outdoor/bright-sunlight legibility; no new palette is introduced.
- `playSuccess`/`playFailure`/`playScanTick` audio feedback (existing `feedbackService`) is reused for every new scan outcome, so staff can operate by sound alone in one-handed, eyes-on-the-bag scanning scenarios.
- The confirmation card's auto-submit toggle (existing pattern) is preserved for event scanning so a single hand can hold a bag while scanning without needing a second tap to confirm.
