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
│   │       ├── HotelAllocationAdjustScreen.tsx
│   │       └── TourUserAssignmentScreen.tsx
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
| `BaggageReconciliation` | `{ eventId: string; occurrenceId: string }` | Stack | `Permission.DASHBOARD` |
| `HotelManagement` | none | Stack, from `TourManagement` | `isAdministrator` |
| `HotelAllocationUpload` | none | Stack, `onClose` modal-style | `hasPermission(role, Permission.HOTEL_ALLOC_MANAGE)` |
| `HotelAllocationAdjust` | `{ riderId: string; stayDate: string }` | Stack, `onClose` modal-style | `hasPermission(role, Permission.HOTEL_ALLOC_MANAGE)` |
| `TourUserAssignment` | `{ userId: string }` | Stack, `onClose` modal-style | `hasPermission(role, Permission.USER_MANAGE)` |

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

**Editor screen layout:** Top section — event-level fields (`eventName`, `eventType`, `location`, `sequenceEnforced` toggle, `defaultAllowedTypeCodes` multi-select sourced live from `AppConfig` `ID_CODE_TYPE` (backend §4.3, fetched via the existing `GET /v1/config` call — never a hardcoded RIDER/BAGGAGE toggle), `allowSelfService` toggle). Below — an ordered, drag-reorderable list of activity rows, each showing `name`, `sequenceNo`, `enabled`/`mandatory`/`allowOptOut` toggles, an `allowedTypeCodes` multi-select (same `ID_CODE_TYPE` source; empty selection means "inherit the event's `defaultAllowedTypeCodes`", shown as a placeholder chip reading "Inherits: {resolved names}"), `prerequisiteActivityIds` multi-select (restricted to earlier activities), `restrictToAssignedUsers` toggle (defaults `true` per backend D15), and `variantOptions` chip-input. A "+ Add Activity" row is appended at the end. Save button posts the full definition (backend §8.4/§8.5).

**Form factor priority (web-first, mobile fallback):** per product-owner refinement, this is the one screen in this design that is designed **web-first** rather than mobile-first, because drag-reordering a multi-row activity list with three multi-selects per row is materially harder to use one-handed on a phone than a definitional, low-frequency (created once, edited rarely) admin task deserves.

- **Web / tablet layout (primary):** two-column layout — event-level fields in a fixed left rail, the activity list as a full-width, drag-reorderable table (one row per activity, all fields visible inline as table cells: name, sequence, toggles, multi-selects) on the right. Drag-reorder uses pointer drag-and-drop (no long-press gesture needed). "+ Add Activity" appends a new table row without navigating away.
- **Mobile fallback layout:** the same fields are shown, but the activity list becomes a vertical list of **expandable cards** (one per activity, collapsed to `name` + `sequenceNo` + enabled/mandatory badges by default; tapping expands the card to reveal the remaining fields) rather than a table, since table columns do not fit a phone width. Reordering uses explicit "Move up"/"Move down" icon buttons per card instead of drag-and-drop, which is unreliable on small touch targets. All other behaviour (validation, save, API calls) is identical to the web layout — this is a layout-only fallback, not a reduced feature set.
- Both layouts share the same component logic and API calls; only the activity-list container and reorder-interaction components are swapped based on a breakpoint (matching the existing responsive-breakpoint convention already used elsewhere in `tour-mgmt-app`, rather than a separate mobile-only screen).

**States:** loading (skeleton cards/rows), empty (list screen shows "No events yet" + CTA), error (`StatusMessage kind: 'error'` with retry), offline (banner: "Event definitions require a connection to edit" — definitions are never offline-editable, §7.8), permission-denied (screen not reachable — route hidden per §3.1).

**Validation messages:** "Activity name is required.", "At least one activity is required.", "Prerequisite activities must come before this activity in sequence.", "Variant options require at least two values." — all client-side pre-checks mirroring backend `400 VALIDATION_ERROR` (backend §8.25); server error messages are surfaced verbatim on top of these when the API rejects.

**API calls:** `GET`/`POST`/`PUT` per backend §8.2–§8.5.

**Navigation:** in from `TourManagement`; out via back button or successful save (pops to list).

### 4.2 Occurrence management (ADMINISTRATOR + SUPER_USER)

**Purpose:** Create/manage `EventOccurrence` instances (backend §5.2) for a given event.

**Permissions:** `EVENT_OCCURRENCE_MANAGE` (backend §9.2).

**Layout:** A **read-only definition header** at the top of the screen — `eventName`, `location`, `sequenceEnforced`, and the activity list rendered as read-only chips (name + mandatory/enabled state only, no editing controls; per finding 1 the definition is never edited from this screen). Below the header, a list of occurrences for the event, each row showing `date`, `seq`, `status` badge, and action buttons appropriate to state: `Start` (when `PLANNED`), `Complete`/`Cancel` (when `ACTIVE`). A "+ New Occurrence" action opens a small form for `date` + `seq`. Each occurrence row also exposes an **"Activity overrides"** panel, one row per activity, each with an "Adjust for this occurrence" action that opens the per-activity override editor (below) writing to `activityOverrides` (backend §5.2a, §8.9a) — replacing any earlier flat "disable activity"/single self-service toggle model.

**Per-activity override editor:** for the selected activity, three optional overrides plus a note: `enabled` (on/off, defaults to the activity's own `enabled`), `selfServiceEnabled` (on/off, defaults to the occurrence-wide `selfServiceEnabled` default), `allowedTypeCodes` (multi-select narrowing the activity's effective allowed types for this occurrence only, same `ID_CODE_TYPE` source as backend §4.3), and a free-text `note` explaining the day-specific reason (for example "Self-service drop-off for one day only — hotel short-staffed"). Leaving all three override fields unset and saving removes the override entry entirely (backend §8.9a merge/removal rule). Saved overrides are shown as a small badge on the activity chip in the occurrence header (for example "Self-service (Day 3 only)") so the day-specific change is visible at a glance without opening the editor.

**Form factor priority (web-first for create/major edits, mobile quick-actions for day-of changes):** per product-owner refinement, creating an event's initial run of occurrences and any multi-field edit is a planning-time task best done web-first; but a single override — for example "the hotel is short-staffed today, switch baggage loading to self-service for today only" — is exactly the kind of last-minute, on-site, one-handed decision that must also work quickly on a phone.

- **Full-edit operations (web-first, adaptive to mobile):** creating an occurrence, bulk-generating a `REPEATING` event's date range, and editing more than one override field at once. On web/tablet these use the full per-activity override editor described above, laid out as a side panel; on mobile the same editor is reachable but presented as a full-screen sheet (not a quick-action), since these are inherently multi-field operations.
- **Mobile quick-actions (mobile-first, also available on web):** a small, fixed set of single-tap toggles surfaced directly on the occurrence row without opening the full editor — specifically: toggle `enabled` off/on for one activity, toggle `selfServiceEnabled` off/on for one activity, and `Start`/`Complete`/`Cancel` the occurrence itself. Each quick-action is a single API call (backend §8.9a PUT with only that one field set, using the merge/upsert semantics) with an inline confirmation toast rather than a navigation to another screen, so it can be done in seconds from a phone at the hotel front desk. `allowedTypeCodes` narrowing and the free-text `note` are **not** quick-actions — they always route to the full editor, since they involve a multi-select/text-entry interaction that a single-tap toggle cannot express.

**States:** loading, empty ("No occurrences yet for this event"), error, offline (occurrence create/start/complete/cancel are online-only administrative actions — banner shown, actions disabled), permission-denied (route hidden).

**Interactions:** tapping `Start`/`Complete`/`Cancel` shows a confirmation dialog before calling backend §8.10/§8.11/§8.12; `Complete` confirmation surfaces `outstandingMandatoryCount` from the response if non-zero, e.g. "3 riders have outstanding mandatory activities. Complete anyway?".

**API calls:** backend §8.6–§8.12/§8.9a.

**Navigation:** in from `EventDefinitionList` (admin) or a dedicated "Occurrences" entry point; out via back; each occurrence row's "Scan" action pushes `EventScan`.

### 4.3 Event Scan screen

**Purpose:** Record `EventActivityLogs` scans (backend §5.3, §8.13). Modelled directly on `CheckInScreen.tsx`.

**Permissions:** `EVENT_SCAN` (backend §9.2), further narrowed by the second authorisation layer (backend §9.3) — a denied scan surfaces the exact `RIDER_NOT_ASSIGNED`/`HOTEL_MISMATCH` message from backend §8.25.

**Layout (3-section, matching `CheckInScreen`):**

1. **Activity selector + scanner.** An activity picker (chips or dropdown) restricted to activities whose *effective* `enabled` state (activity definition, then narrowed by any occurrence-level `activityOverrides` entry, backend §5.2a) is `true` for this occurrence; the currently selected activity's *effective* `allowedTypeCodes` — resolved as the activity's own value if non-empty, else the event's `defaultAllowedTypeCodes` (backend §4.3), then further narrowed for this occurrence only if an `activityOverrides` entry sets its own `allowedTypeCodes` (backend §5.2a) — determines the allowed ID Code type(s) passed to `resolveScannedRiderId()` (§8.1). Below, the camera scanner (mounted only `useIsFocused`, via `useCameraPermissions`) plus a manual-entry fallback field, matching `CheckInScreen`'s pattern exactly.
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

**Purpose:** Bulk-load `RoomAllocation` records via the S3 presigned-upload + async-processing flow (backend §8.21/§8.22, design decision D11), with a **strict all-or-nothing apply** (backend §8.22a/§8.22b, D21) — the frontend must never present a "partially applied" outcome, since one cannot occur.

**Layout (`onClose` modal-style, matching admin screen convention):** File-pick button (native document picker), selected-file name display, "Upload" action. On upload: progress bar tracking the S3 `PUT`, then a "Validating…" spinner while polling. On completion, exactly one of two outcomes is shown — never a mixed one:
- **Applied:** a success banner "{appliedCount} allocations applied for {rowCount} rows." with a "Done" action closing the modal.
- **Rejected:** an error banner "This file was not applied — fix the {errorCount} issue(s) below and re-upload the corrected file. No allocations were changed." followed by a row-level error table with columns Row, Code, Message — each row number mapped directly back to the source CSV so the organiser can locate and fix it — plus a "Choose another file" action that re-opens the file picker. The banner's wording is deliberately explicit that **nothing was written**, so the organiser does not assume the valid-looking rows went through.

**Flow detail:**
1. Screen calls backend §8.21 to get `{ uploadId, uploadUrl, s3Key, expiresIn }`.
2. App performs the S3 `PUT` of the picked CSV file to `uploadUrl`, tracking progress via the HTTP client's upload-progress callback.
3. App polls backend §8.22 with the returned `uploadId` on a fixed interval (e.g. every 3s) until `status` is `APPLIED` or `REJECTED`, capped at a maximum poll duration with a "still validating — check back later" fallback message.
4. On `REJECTED`, errors are rendered from the `errors[]` array in the poll response, each `{ row, code, message }` mapped 1:1 to a table row; on `APPLIED`, `appliedCount` is shown and no error table is rendered.

**States:** loading (initial presign call), uploading (progress bar), validating (poll spinner, labelled "Validating…" rather than "Processing…" to make clear nothing is applied yet), error (presign failure, S3 `PUT` failure, or `REJECTED` status — both are "expected" outcomes handled in-screen per §9, not thrown exceptions), offline (upload is online-only — screen shows "Connect to the internet to upload hotel allocations" and disables the file picker).

**API calls:** backend §8.21/§8.22.

### 4.9 Manual hotel allocation adjustment

**Purpose:** Single-night edit of one rider's `RoomAllocation` (backend §8.20).

**Layout:** A **read-only rider profile display** at the top (name, photo, `riderId` — per finding 1/finding 15, rider profile fields are never editable here), followed by an editable form for `hotelId` (picker), `roomNo`, `roomCapacity` (stepper, `2` or `3`, defaults `2`, backend §5.4/D19), and `sharingWith` (rider **multi-select**, optional, capped to `roomCapacity - 1` selections so the room's total occupancy including the current rider cannot exceed `roomCapacity`) for the single `stayDate` passed via route params. A **room-clash warning** banner appears inline the moment the chosen `hotelId`+`roomNo` combination is already occupied by a non-reciprocal rider for that date (client-side pre-check against the cached `hotelStayStore`, backed by a final server-side check on save). A **capacity warning** banner appears inline the moment the selected `sharingWith` list would exceed `roomCapacity` (client-side pre-check; the picker itself also disables further selections once the cap is reached).

**States:** loading, error, offline (edit is online-only administrative action; if a cached room-clash check cannot be performed offline because the local cache is stale, the warning is suppressed and a "verify online before saving" note is shown instead), permission-denied (route hidden).

**Validation messages:** "Room number is required.", room-clash banner text: "Room {roomNo} at {hotelName} is already allocated to {otherRiderName} on {stayDate}." (mirrors backend `409 ROOM_CLASH` message, backend §8.25), "The paired rider's record does not confirm this room sharing." (mirrors `409 NON_RECIPROCAL_SHARING`), "Room {roomNo} cannot hold more than {roomCapacity} riders on this date." (mirrors `409 ROOM_CAPACITY_EXCEEDED`).

**API calls:** backend §8.20; hotel list from §8.18; existing stays from §8.19 (by-hotel query) for clash pre-checking.

**Navigation:** in from `HotelManagementScreen` room-wise view or from a rider's `RiderCardModal`; out via `onClose`.

### 4.10 Rider exit with mandatory baggage disposition

**Purpose:** Extend the existing rider-exit screen/flow to require `baggageDisposition` (backend §8.23).

**Layout:** The existing exit confirmation dialog gains a mandatory radio choice: "Baggage retained by organisers" (`RETAINED`) or "Rider is taking baggage now" (`WITH_RIDER`), with the Confirm button disabled until one is chosen. Submitting without a choice is prevented client-side; if somehow submitted, the server's `400 BAGGAGE_DISPOSITION_REQUIRED` message ("Choose whether baggage is retained or released before exiting this rider.") is shown.

**Exit cancellation:** the existing cancel-exit action is unchanged in the UI; it now also restores `baggageStatus` server-side (backend §8.23) with no additional client UI required.

**Baggage release:** a new action on the rider detail screen, visible only when `baggageStatus=RETAINED`, labelled "Release retained baggage", with a confirmation dialog and optional note field (maps to `note` in backend §8.23). Disabled with a tooltip when `baggageStatus` is not `RETAINED` (server would reject with `409 BAGGAGE_NOT_RETAINED`).

**API calls:** backend §8.23.

### 4.11 User provisioning — create/update `User-{tourId}` assignments

**Purpose:** Provide the screen flow for the previously-missing backend contract (backend §8.23a, D22) that creates/updates a `User-{tourId}` record's tour-assignment attributes: `role`, `assignedStage`, `hotelId`, `eventAssignments`, `assignedActivityIds`.

**Permissions:** `USER_MANAGE` (backend §9.2) — entry points hidden unless held.

**Relationship to existing user-management screens:** this is **not** a replacement for `UserOnboarding`/`UserModify` (which create/manage the Cognito identity via `/v1/admin/usermgmt/users` — unaffected by this design). It is a new step that follows identity creation: `UserOnboarding`'s existing "Save" success state gains a secondary action, "Assign to this tour →", which navigates straight into this screen pre-filled with the just-created `userId`; the screen is also reachable directly from a "Tour Assignments" entry on `TourManagement` for assigning an already-existing managed user.

**Layout:** A **read-only identity header** at the top (`username`, `email`, `name` — sourced from the existing managed-user record, never re-entered or edited here) followed by an editable tour-assignment form: `role` picker (same options as `User-{tourId}.role`, backend §5.7 header), `assignedStage` (number stepper, shown only when `role=PS_<n>_USER`), `hotelId` (hotel picker, shown only when `role=HOTEL_STAFF`), `eventAssignments` editor (repeatable rows, each an event picker + a `dates` control that is either "All dates" or a specific multi-date picker), and `assignedActivityIds` (multi-select scoped to the activities of the events already chosen in `eventAssignments`, shown only when at least one event is assigned). Save calls `POST`/`PUT` backend §8.23a depending on whether a `User-{tourId}` record already exists for this `userId` (determined from the initial `GET /v1/tours/{tourId}/users` list load, backend existing endpoint).

**States:** loading (fetching the current assignment, if any, plus the event/hotel pickers' source lists), empty (no existing assignment — form starts blank aside from the identity header), error, offline (assignment is online-only administrative action; banner shown, form disabled), permission-denied (route hidden).

**Validation messages:** "Select a role.", `400 INVALID_EVENT_ASSIGNMENT` surfaced verbatim as "One or more assignments reference an event or hotel that does not exist." (backend §8.25) — shown inline next to the offending `eventAssignments`/`hotelId` field rather than as a generic top-of-screen error, since the field causing it is otherwise ambiguous; `404 USER_NOT_FOUND` (the identity was deleted between load and save) is shown as a full-screen message with a "Back to user list" action rather than a form-field error, since the form can no longer be saved at all.

**API calls:** backend §8.23a; identity data and existing-assignment check from the existing `GET /v1/tours/{tourId}/users`.

**Navigation:** in from `UserOnboarding`'s post-save action or from a new `TourManagement` → "Tour Assignments" entry; out via `onClose` back to the user list.

### 4.12 Extensions to existing user management screens

`UserOnboarding`/`UserModify` screens are otherwise unchanged by this design (they continue to own Cognito identity creation only); §4.11 above is the sole screen responsible for the fields added to `User-{tourId}` by this design.

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
  cachedRecords: EventActivityLogs[];       // records for the current occurrence, kept in sync with SQLite
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
  default_allowed_type_codes_json TEXT,
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
  activity_overrides_json TEXT,   -- serialized activityOverrides[] array, backend §5.2a
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
CREATE TABLE IF NOT EXISTS room_allocations (
  stay_date TEXT NOT NULL,
  rider_id TEXT NOT NULL,
  hotel_id TEXT NOT NULL,
  room_no TEXT,
  room_capacity INTEGER NOT NULL DEFAULT 2,
  sharing_with_json TEXT,   -- serialized List<String> of rider IDs, backend §5.4/D19
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

`EventScanScreen` (§4.3) computes `allowedTypes` from the selected activity's effective `allowedTypeCodes` (backend §4.3/§5.1 — resolved as `Activity.allowedTypeCodes` if non-empty, else `Event.defaultAllowedTypeCodes`), then, if the occurrence has an `activityOverrides` entry for that activity with its own `allowedTypeCodes` set, that override further **narrows** the resolved set for this occurrence only (it is not a fallback in the chain, but a per-occurrence restriction applied on top of it, §4.2/backend §5.2a). The screen never hardcodes `RIDER`/`BAGGAGE`: it resolves the effective code list to the matching `ID_CODE_TYPE` config entries (fetched via the existing `GET /v1/config` call) and passes those entries' codes as `allowedTypes`. On a successful resolution, `{ riderId, typeCode, bagLabel }` is passed directly into the activity-record submission (backend §8.13 request body).

## 9. Error and message catalogue

### 9.1 Graceful handling of expected validation errors and 404s

Per product-owner refinement, the apps must treat backend validation errors (`400`) and expected "not found" responses (`404`) as **normal, in-screen flow outcomes** — never as thrown/uncaught exceptions that crash a screen or fall back to a generic error boundary. This formalises a pattern already used ad hoc in a few screens (for example `EventScanScreen`'s duplicate/prerequisite handling, §4.3) into a rule for every screen in this design:

- Every API call in `eventsApi.ts`/`hotelsApi.ts` returns a **discriminated-union outcome** (mirroring `checkInApi.ts`'s existing pattern, §2.1), not a thrown `ApiError` for the codes listed in the table below — callers `switch` on `outcome.type` rather than wrapping the call in `try/catch` for these expected cases. A `try/catch`/error boundary is reserved for genuinely unexpected failures (network loss mid-request, `500`s, malformed responses).
- A `400 VALIDATION_ERROR` (or a named validation code such as `INVALID_EVENT_ASSIGNMENT`) is always shown **inline, next to the field that caused it** when the field is unambiguous (for example §4.11's `eventAssignments`/`hotelId` handling), and only falls back to a top-of-screen `StatusMessage kind: 'error'` when no single field is responsible.
- A `404` always resolves to an explicit **next-step action** rather than a dead-end message: "not found because it was deleted elsewhere" screens (for example `404 USER_NOT_FOUND` in §4.11, `404 UPLOAD_NOT_FOUND`) show a full-screen message plus a button back to the owning list screen; "not found because the ID typed/scanned was wrong" screens (for example a manual rider-ID entry that doesn't resolve) show an inline retry affordance instead, since the user is expected to immediately correct their input.
- No screen in this design shows a raw stack trace, a generic "Something went wrong" message, or a native alert/dialog for any code listed in §9.2 — those are reserved for the unexpected-failure path described above.

### 9.2 Error code to message mapping

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
| `ROOM_CAPACITY_EXCEEDED` | verbatim from server | warning |
| `UPLOAD_NOT_FOUND` | "Upload not found." | error |
| `BAGGAGE_DISPOSITION_REQUIRED` | verbatim from server | error |
| `BAGGAGE_NOT_RETAINED` | "Baggage is not currently retained for this rider." | error |
| `RECORD_NOT_FOUND` | "Activity record not found." | error |
| `RECORD_ALREADY_CANCELLED` | "This activity record has already been cancelled." | info |
| `USER_NOT_FOUND` | "User not found." (§4.11, next-step: back to user list) | error |
| `USER_ALREADY_EXISTS` | "A user with this ID already exists." | error |
| `INVALID_EVENT_ASSIGNMENT` | "One or more assignments reference an event or hotel that does not exist." (§4.11, shown inline next to the offending field) | error |

## 10. `tour-mgmt-app` task list

| # | Task | Acceptance criteria | Dependencies | Affected paths | Phase |
|---|---|---|---|---|---|
| 1 | Add new `AppStackParamList` routes + route wrappers | All §3.1 routes registered and conditionally gated | Backend §9.1 permissions shipped | `src/types/navigation.ts`, `src/navigation/AppNavigator.tsx` | 1 |
| 2 | Add new `Permission` enum members + `hasPermission` mapping | App-side `Permission` enum documents the mapping to backend permission names (§8.1 of backend design's RBAC naming) | Backend §9.1 | `src/types/models.ts`, `src/utils/permissions.ts` | 1 |
| 3 | Implement `eventsApi.ts`/`hotelsApi.ts` | Typed request/response for every endpoint in backend §8.1; `ApiError` + outcome unions for expected 409s | Task 2 | `src/services/api/{eventsApi,hotelsApi}.ts`, `src/types/api.ts` | 1 |
| 4 | Generalise `resolveScannedRiderId()` | Signature and behaviour exactly per §8.1; existing check-in tests unaffected | None | `src/services/idcode/idCodeService.ts`, `src/constants/idCodes.ts` | 1 |
| 5 | Implement `eventStore.ts`, `eventRecordStore.ts`, `hotelStayStore.ts` | DDL per §7.1; write-local-first + `pending_operations` integration | Task 3 | `src/services/database/*.ts` | 2 |
| 6 | Implement `EventSessionContext` | Shape per §6.1 | Task 5 | `src/context/EventSessionContext.tsx` | 2 |
| 7 | Build Event Definition list/editor screens | §4.1 states/validation implemented, including the web-first table layout and mobile expandable-card fallback | Tasks 1–3 | `src/screens/events/EventDefinition*.tsx` | 2 |
| 8 | Build Occurrence management screen | §4.2, including read-only definition header, per-activity `activityOverrides` editor, and mobile quick-action toggles | Tasks 1–3, 6 | `src/screens/events/OccurrenceManagementScreen.tsx` | 2 |
| 9 | Build Event Scan screen | §4.3, reusing/extracting `ScanConfirmationCard`, resolving effective `enabled`/`allowedTypeCodes` via `activityOverrides` | Tasks 1–6 | `src/screens/events/EventScanScreen.tsx` | 3 |
| 10 | Build Rider Progress stepper | §4.4 | Tasks 1–3 | `src/screens/events/RiderProgressScreen.tsx`, `ActivityStepper` component | 3 |
| 11 | Build Occurrence dashboard + Baggage reconciliation screens | §4.5, §4.6 | Tasks 1–3 | `src/screens/events/{OccurrenceDashboard,BaggageReconciliation}Screen.tsx` | 3 |
| 12 | Build Hotel management, upload (all-or-nothing outcome only, §4.8), and manual-adjustment (multi-select `sharingWith` + `roomCapacity`, §4.9) screens | §4.7–§4.9 | Tasks 1–5 | `src/screens/events/Hotel*.tsx` | 3 |
| 13 | Extend rider-exit UI with baggage disposition (`RETAINED`/`WITH_RIDER`) + release action | §4.10 | Task 3 | existing rider-exit screen/component | 2 |
| 14 | Build the `TourUserAssignment` screen for `User-{tourId}` create/update | §4.11 | Task 3 | `src/screens/events/TourUserAssignmentScreen.tsx` | 3 |
| 15 | Sync service integration | §7.3/§7.4 new operation types handled by outbound/inbound timers | Task 5 | `src/services/sync/syncService.ts` | 2 |

## 11. `tour-rider-app` task list

| # | Task | Acceptance criteria | Dependencies | Phasing |
|---|---|---|---|---|
| 1 | Add `dietaryPreference` self-service field to rider profile screen | Field round-trips via `RiderApi` rider-profile update call; optional, defaults empty | Backend Task 12 | 1 |
| 2 | Add rider's own event/baggage status visibility screen | Read-only view of the rider's own activity progress (backend §8.16) and `baggageStatus` | Backend §8.16 | 2 |
| 3 | Offline-safe read caching | Bootstrap-equivalent rider payload cached locally; screen renders from cache when offline | Task 2 | 2 |

## 12. Frontend test strategy

**Unit:** `resolveScannedRiderId()` backwards-compatibility (existing `['RIDER']` behaviour byte-for-byte unchanged) and new `TYPE_NOT_ALLOWED_FOR_EVENT` path; `hasPermission` mapping for the five new backend permissions (including `USER_MANAGE`); SQLite DDL migration idempotency; `activityOverrides` effective-value resolution (activity → occurrence override → event default precedence, §4.3/backend §5.2a).

**Component:** `EventScanScreen` state rendering for each state in §4.3 (loading/empty/error/offline/permission-denied/blocked-scan); `OccurrenceManagementScreen` read-only header rendering (activities must not be editable from this screen) and per-activity override editor + mobile quick-action toggles (§4.2); room-clash and room-capacity banner rendering in `HotelAllocationAdjustScreen` (§4.9); `HotelAllocationUploadScreen` renders only the `Applied`/`Rejected` outcomes (§4.8) and never a partial-success state; `TourUserAssignmentScreen` field-level `INVALID_EVENT_ASSIGNMENT` rendering (§4.11); `EventDefinitionEditorScreen` renders the table layout above the web/mobile breakpoint and the expandable-card layout below it (§4.1).

**Manual QA scenarios:** end-to-end scan of all 5 Day-0-Registration activities for one rider including a variant choice and an opt-out; end-to-end Baggage Loading → Baggage Unloading with one bag deliberately withheld to verify the reconciliation drill-down; wrong-hotel-staff scan producing the exact `HOTEL_MISMATCH` message; airplane-mode scan followed by reconnection and successful sync; CSV upload with a deliberately malformed row producing a full-batch rejection with zero rows applied (never a partial count); a mobile quick-action toggle of `selfServiceEnabled` for one activity on one occurrence, verified not to affect any other occurrence of the same event; a `roomCapacity=3` triple-sharing save followed by a fourth-rider attempt producing `ROOM_CAPACITY_EXCEEDED`.

## 13. Accessibility and field-usability notes

- All scan-confirmation primary actions use large touch targets (minimum 48dp) for gloved use in cool early-morning starts.
- `QR_SCANNER_COLORS` high-contrast palette is reused as-is for outdoor/bright-sunlight legibility; no new palette is introduced.
- `playSuccess`/`playFailure`/`playScanTick` audio feedback (existing `feedbackService`) is reused for every new scan outcome, so staff can operate by sound alone in one-handed, eyes-on-the-bag scanning scenarios.
- The confirmation card's auto-submit toggle (existing pattern) is preserved for event scanning so a single hand can hold a bag while scanning without needing a second tap to confirm.
