# TODO: Documentation vs. Development Gap Analysis

Identified on: 2026-02-14
Last reviewed: 2026-02-14

This document lists all gaps found between project documentation and actual development artifacts. Each item should be reviewed and resolved before deployment.

> **Note:** SolutionDesign.md was updated on 2026-02-14 with the hybrid table strategy (shared + tour-specific tables), free-form tourId, SubscriptionId as tag-only, and tour provisioning/archiving workflows. Several items below have been updated to reflect the new design. New items (#26–#30) were added for design-driven implementation work.

---

## 1. ✅ RESOLVED: Missing Lambda Function Files

~~template.yaml references handler files that do not exist on disk. **SAM build will fail.**~~

| template.yaml Resource | Expected Handler | Expected File | Status |
|---|---|---|---|
| `ListToursFunction` | `list_tours.lambda_handler` | `src/functions/tours/list_tours.py` | ✅ Created |
| `GetTourRidersFunction` | `get_tour_riders.lambda_handler` | `src/functions/riders/get_tour_riders.py` | ✅ Created |

**Resolution:** Both Lambda function files have been created (2026-02-17).

**Notes:**
- `list_tours.py`: Lists all tours with optional status filter via query parameter
- `get_tour_riders.py`: Retrieves all riders for a specific tour with enriched profile data
- Both functions will require refactoring when TODO #26-30 (hybrid table strategy) is implemented

---

## 2. CRITICAL: Lambda Functions Not Wired in template.yaml

These 5 functions exist on disk but have no corresponding `AWS::Serverless::Function` resource in template.yaml, making them unreachable via API Gateway:

| File | Documented Endpoint |
|---|---|
| `src/functions/riders/get_rider_profile.py` | `GET /riders/{riderId}` (README) / `GET /riders/profile/{profileId}` (SolutionDesign) |
| `src/functions/riders/update_rider_profile.py` | `PUT /riders/{riderId}` (README) / `PUT /riders/profile/{profileId}` (SolutionDesign) |
| `src/functions/rides/list_rides.py` | `GET /tours/{tourId}/rides` (README) |
| `src/functions/users/get_current_user.py` | `GET /users/me` (README) |
| `src/functions/users/list_tour_users.py` | `GET /tours/{tourId}/users` (README) |

**Action:** Add corresponding `AWS::Serverless::Function` resources in template.yaml for each, or remove from docs if not in scope.

---

## 3. API Route Mismatches Across Documentation and Code

README, SolutionDesign, and template.yaml disagree on endpoint paths for many routes:

| Endpoint | README | SolutionDesign | template.yaml (actual) |
|---|---|---|---|
| Get rider profile | `GET /riders/{riderId}` | `GET /riders/profile/{profileId}` | **Not defined** |
| Update rider profile | `PUT /riders/{riderId}` | `PUT /riders/profile/{profileId}` | **Not defined** |
| Get today's ride | `GET /tours/{tourId}/rides/today` | `GET /rides/today?tourId={tourId}` | `GET /v1/rides/today` (no tourId) |
| Get ride by ID | `GET /tours/{tourId}/rides/{rideId}` | `GET /rides/{rideId}` | `GET /v1/rides/{rideId}` |
| Update ride | `PUT /tours/{tourId}/rides/{rideId}` | `PUT /rides/{rideId}` | `PUT /v1/rides/{rideId}` |
| Close ride | `POST /tours/{tourId}/rides/{rideId}/close` | `POST /rides/{rideId}/close` | `POST /v1/rides/{rideId}/close` |
| List rides | `GET /tours/{tourId}/rides` | `GET /tours/{tourId}/rides` | **Not defined** |
| Get ride check-ins | `GET /tours/{tourId}/rides/{rideId}/checkins` | `GET /rides/{rideId}/checkins` | `GET /v1/rides/{rideId}/checkins` |
| Dashboard | `GET /dashboard/{rideId}` | `GET /rides/{rideId}/dashboard` | `GET /v1/rides/{rideId}/dashboard` |
| Get current user | `GET /users/me` | `GET /users/me` | **Not defined** |
| List tour users | `GET /tours/{tourId}/users` | `GET /tours/{tourId}/users` | **Not defined** |
| List tours | Not in README | `GET /tours?status={status}` | `GET /v1/tours` (handler missing) |
| Create tour | Not in README | `POST /tours` | **Not defined** |
| Archive tour | Not in README | `POST /tours/{tourId}/archive` | **Not defined** |
| Get tour riders | Not a distinct endpoint in README | `GET /tours/{tourId}/riders` | `GET /v1/tours/{tourId}/riders` (handler missing) |

**Action:** Decide on authoritative API paths (SolutionDesign should be source of truth), then align README, template.yaml, and Lambda code.

---

## 4. README Missing `/v1/` Prefix on All API Endpoints

All template.yaml routes use the `/v1/` prefix (e.g., `GET /v1/tours/active`), but README documents all 15 endpoints without it (e.g., `GET /tours/active`).

**Action:** Update README to include the `/v1/` prefix on all endpoints.

---

## 5. CRITICAL: `bad_request_response()` Does Not Exist

Approximately 9 Lambda functions import or call `bad_request_response()`, but this function does **not exist** in `src/layers/common/python/response.py`. This causes `ImportError` at runtime.

**Affected files:** `get_rider_profile.py`, `get_tour_rider.py`, `update_rider_profile.py`, `get_todays_ride.py`, `get_ride.py`, `list_rides.py`, `create_ride.py`, `update_ride.py`, `close_ride.py`, `get_ride_checkins.py`

**Action:** Add `bad_request_response()` to `response.py`, or change all usages to `validation_error_response()` or `error_response()`.

---

## 6. CRITICAL: `validate_date` Does Not Exist in validation.py

`create_ride.py` and `update_ride.py` import `validate_date`, but the actual function name is `validate_iso_date`.

**Action:** Update imports to use `validate_iso_date`.

---

## 7. CRITICAL: `error_response()` Called with Wrong Signature

~8 functions call `error_response()` with a single string argument, but its signature is `error_response(error_code, message, status_code=400, details=None)`.

**Action:** Fix all call sites to pass both `error_code` and `message` arguments.

---

## 8. CRITICAL: `not_found_response()` Called with Wrong Signature

~5 functions call `not_found_response()` with a single formatted string, but its signature is `not_found_response(resource, identifier)` (requires 2 arguments).

**Action:** Fix all call sites to pass both `resource` and `identifier` arguments.

---

## 9. CRITICAL: `table_name` vs `table_name_env` Parameter Mismatch

`dynamodb_utils.py` functions (`get_item`, `put_item`, `query_items`, etc.) all expect a `table_name_env` parameter (the **environment variable name**, e.g., `'TOUR_TABLE'`). However, ~10 Lambda functions pass `table_name=` with the **resolved table name** string instead.

**Correctly using `table_name_env`:** `get_active.py`, `get_tour.py`, `create_checkin.py`, `get_dashboard_data.py`

**Incorrectly using `table_name=`:** `get_rider_profile.py`, `get_tour_rider.py`, `update_rider_profile.py`, `get_todays_ride.py`, `get_ride.py`, `list_rides.py`, `create_ride.py`, `update_ride.py`, `close_ride.py`, `get_ride_checkins.py`

**Action:** Fix all affected functions to use `table_name_env=` with the environment variable name.

> **Design Note:** With the updated hybrid table strategy, tour-specific tables (TourRider, Ride, CheckIn, User) are created at runtime and their names are derived dynamically as `{STACK_NAME}-{TableType}-{tourId}`. The `dynamodb_utils.py` module will need a new mechanism for dynamic table name resolution in addition to the existing `table_name_env` pattern. See TODO #28.

---

## 10. Route/Path Parameter Mismatch in Lambda Functions

Several ride-related functions expect `tourId` from path parameters, but the API routes in template.yaml do not include `{tourId}`. This means `tourId` is always `None`, causing the function to always return 400.

**Affected functions and routes:**
- `get_todays_ride.py` — Route: `GET /v1/rides/today` (no `{tourId}`)
- `get_ride.py` — Route: `GET /v1/rides/{rideId}` (no `{tourId}`)
- `update_ride.py` — Route: `PUT /v1/rides/{rideId}` (no `{tourId}`)
- `close_ride.py` — Route: `POST /v1/rides/{rideId}/close` (no `{tourId}`)
- `get_ride_checkins.py` — Route: `GET /v1/rides/{rideId}/checkins` (no `{tourId}`)

**Action:** Either add `{tourId}` to the routes, or change the Lambda code to derive `tourId` from the data rather than path parameters.

---

## 11. `get_tour.py` Missing Import

`src/functions/tours/get_tour.py` uses `error_response` but does not import it. Only `success_response`, `not_found_response`, and `internal_error_response` are imported. This causes `NameError` at runtime.

**Action:** Add `error_response` to the import statement.

---

## 12. DynamoDB GSI: `RideIdIndex` Referenced but Not Defined

`get_dashboard_data.py` queries a `RideIdIndex` GSI on the Ride table, but this index does not exist in template.yaml. The Ride table only has `DateIndex` and `StatusIndex`.

**Action:** Either add `RideIdIndex` GSI to the Ride table in template.yaml, or change the query approach in the dashboard function.

> **Design Note:** With the updated design, the Ride table is now tour-specific (`Ride-{tourId}`) and provisioned at runtime. Its GSIs (DateIndex on `date`, StatusIndex on `status`) are defined during provisioning, not in template.yaml. The dashboard function's use of `RideIdIndex` still needs to be resolved — the tour-specific Ride table uses `RIDE#<rideId>` as PK, so a direct `get_item` may suffice instead of a GSI query.

---

## 13. Ride Status Enum Mismatch: `SCHEDULED` vs `PLANNED`

| Source | Values |
|---|---|
| SolutionDesign.md | PLANNED, ACTIVE, COMPLETED, CLOSED |
| `models.py` `RideStatus` enum | PLANNED, ACTIVE, COMPLETED, CLOSED |
| `create_ride.py` | Uses `RideStatus.SCHEDULED` (**does not exist**) |
| `list_rides.py` docstring | References `SCHEDULED` |
| README.md | References "ACTIVE or SCHEDULED" |

**Action:** Standardize on `PLANNED` (per SolutionDesign and models.py). Fix code and README references to `SCHEDULED`.

---

## 14. `validate_stage_number()` Called with Wrong Argument Count

`create_ride.py` calls `validate_stage_number(body['stageNumber'])` with 1 argument, but the function signature is `validate_stage_number(stage_number, total_stages)` (requires 2).

**Action:** Fix the call to provide both arguments.

---

## 15. Python Runtime Version Inconsistency

| Source | Version |
|---|---|
| README.md (Prerequisites) | Python 3.12+ |
| Development guide (Troubleshooting) | "requires 3.12+" |
| template.yaml `Globals.Function.Runtime` | python3.11 |
| CI/CD workflow (ci-cd.yml) | python-version: '3.11' |

**Action:** Align all references. If runtime is 3.11, update README and development-guide. If 3.12 is intended, update template.yaml and CI/CD.

---

## 16. Lambda Function Count Mismatch

| Source | Count |
|---|---|
| README.md | "15 Lambda functions" |
| Infrastructure guide | "Total Functions: 15" (Tours: 2, Riders: 3, Rides: 6, Check-ins: 3, Users: 2) |
| template.yaml (actual) | **16** functions defined (includes `ListToursFunction`; 0 User functions, 2 Rider functions) |
| Files on disk | **16** unique handlers (Tours: 2, Riders: 3, Rides: 6, Check-ins: 3, Users: 2) |

The distribution in infrastructure-guide is also wrong — template.yaml has 3 Tour functions (not 2), 0 User functions (not 2), and 2 Rider functions (not 3).

> **Design Note:** The updated SolutionDesign adds 2 new endpoints: `POST /tours` (create/provision) and `POST /tours/{tourId}/archive`. These will require new Lambda functions, further increasing the count. Final count should be reconciled after all implementation work is done.

**Action:** Update README and infrastructure-guide to reflect actual function counts and distribution once all gaps above are resolved.

---

## 17. Cognito JWT Authorizer Not Attached to Routes

README and SolutionDesign emphasize JWT authentication on all (non-public) endpoints. template.yaml has a `HasCognitoUserPool` condition and `CognitoUserPoolArn` parameter, but **no `Auth` property is attached to any `HttpApi` event**. All API endpoints are currently **unauthenticated**.

**Action:** Add JWT authorizer configuration to the HttpApi resource and apply it to protected routes.

---

## 18. CI/CD Workflow Deploy Jobs Never Execute

The workflow file `.github/workflows/ci-cd.yml` has issues:

1. **Only trigger is `workflow_dispatch`** (manual), but deploy jobs have conditions like `if: github.ref == 'refs/heads/develop' && github.event_name == 'push'`. Since no `push` event is defined in `on:`, deploy jobs **never run**.
2. The `environment` input from `workflow_dispatch` is defined but **never used** by any deploy job — each job hardcodes a branch condition instead.
3. Deployment guide says "manual triggering only" with environment selection, contradicting the branch-based conditions in the workflow.

**Action:** Fix the workflow to either:
- Use `workflow_dispatch` input to select environment and remove branch conditions, OR
- Add `push` triggers for the appropriate branches.

---

## 19. Makefile Targets vs. Documentation

| Docs Reference | Actual Makefile | Gap |
|---|---|---|
| `make logs FUNCTION=X` | `make logs` (tails all, no FUNCTION param) | `logs` target doesn't accept FUNCTION; `logs-function` does |
| `make logs-tail FUNCTION=X` | Not defined | No `logs-tail` target exists |

**Action:** Update Makefile to add missing targets, or update documentation to reference correct targets (`make logs-function`).

---

## 20. Project Structure Documentation Incomplete

`docs/project-structure.md` is missing several files and directories that exist:

- `tests/test_lambda_functions.py`
- `tests/conftest.py`
- `tests/README.md`
- `tests/fixtures/` directory and `mock_data.py`
- `events/get-tour-rider.json`
- `.github/copilot-instructions.md`
- Docs files: `aws-setup-guide.md`, `deployment-guide.md`, `development-guide.md`, `infrastructure-guide.md`, `docs-index.md`
- `__init__.py` files in function directories

**Action:** Update `docs/project-structure.md` to reflect the actual file structure.

---

## 21. Mock Data Inconsistencies with Data Model

Test fixtures in `tests/fixtures/mock_data.py` use data formats that don't match SolutionDesign or models.py:

| Field | SolutionDesign (updated) | Mock Data |
|---|---|---|
| Tour `PK` | `TOUR#<tourId>` (e.g., `TOUR#India-Coast-2026`) | `TOUR#001` |
| Tour `tourId` | Free-form (e.g., `India-Coast-2026`) | `TOUR#001` (includes `#`, wrong format) |
| Rider Profile `PK` | `PROFILE#<uuid>` | `RIDER#R001` (wrong prefix) |
| Rider `riderId` | `R1`, `R57` (no zero-padding per Requirements) | `R001`, `R002` (zero-padded) |
| User `role` | `ADMINISTRATOR`, `SUPER_USER`, etc. (per `UserRole` enum) | `ADMIN` (not a valid enum value) |
| CheckIn `SK` | `CHECKIN#<riderId>#<stageNumber>#<timestamp>` | `2026-02-11T10:30:00#R001` (wrong format) |
| Tour `status` | Includes `PROVISIONING` (new) | Not present in mock data |
| Tour fields | `provisionedAt`, `archivedAt` (new) | Not present in mock data |

**Action:** Fix mock data to match the updated data model specification. Tour-specific table data (TourRider, Ride, CheckIn, User) should use the simplified key design (no tour prefix in PK).

---

## 22. ~~SolutionDesign References Non-Existent `src/authorizer/` Directory~~ — RESOLVED

~~The Infrastructure as Code section in SolutionDesign.md lists `src/authorizer/` for a JWT authorizer. This directory does not exist and no custom authorizer Lambda is implemented.~~

**Resolved:** The `src/authorizer/` reference was removed from SolutionDesign.md on 2026-02-14 during the design update.

---

## 23. Infrastructure Guide References Wrong Utility Filename

`docs/infrastructure-guide.md` (Project Statistics section) lists `response_utils.py` as a shared component. The actual filename is `response.py`.

**Action:** Update infrastructure-guide to reference `response.py`.

---

## 24. Tour Table GSI Documented but Not Implemented

`docs/deployment-guide.md` states the Tour table has `GSI: StatusIndex (for status-based queries)`. The actual Tour table in template.yaml has **no GSIs** — only a simple hash key (`PK`).

SolutionDesign.md (updated) now specifies `GSI1` on `status` for the shared Tour table, aligning with the deployment guide.

**Action:** Add the StatusIndex GSI (partition key: `status`) to the Tour table in template.yaml to match both SolutionDesign.md and deployment-guide.md.

---

## 25. `get_current_user.py` Declares Unused Environment Variable

`src/functions/users/get_current_user.py` reads `USER_TABLE` from environment but never queries DynamoDB — it only returns JWT claims. Minor but unnecessary dependency.

**Action:** Remove the unused `USER_TABLE` reference, or document that it's reserved for future use.

---

# New Items from SolutionDesign.md Update (2026-02-14)

The following items were identified after the SolutionDesign.md was updated with the hybrid table strategy (shared + tour-specific tables), free-form tourId, and tour provisioning/archiving workflows.

---

## 26. template.yaml Needs Restructuring for Hybrid Table Strategy

The current template.yaml defines 6 DynamoDB tables (Tour, RiderProfile, TourRider, Ride, CheckIn, User) all as SAM-managed resources. Per the updated SolutionDesign:

- **Keep as SAM-managed:** Tour, RiderProfile (shared tables)
- **Remove from template.yaml:** TourRider, Ride, CheckIn, User (now tour-specific, provisioned at runtime)

Additional changes needed:
- Add `STACK_NAME` environment variable to all Lambda functions (for dynamic table name resolution)
- Add `SUBSCRIPTION_ID` environment variable (from `SubscriptionId` parameter) for tagging runtime-created tables
- Add `SubscriptionId` as a SAM template parameter
- Add `StatusIndex` GSI to the Tour table (partition key: `status`)
- Update IAM policies: Lambda execution role needs `dynamodb:CreateTable`, `dynamodb:DeleteTable`, `dynamodb:DescribeTable`, `dynamodb:TagResource` for provisioning functions
- Update all Lambda environment variables that reference removed tables

**Action:** Restructure template.yaml to match the hybrid table strategy described in SolutionDesign.md.

---

## 27. New Lambda Functions Needed for Tour Provisioning and Archiving

SolutionDesign.md defines two new API endpoints with no corresponding Lambda functions:

| Endpoint | Handler | File (to create) |
|---|---|---|
| `POST /tours` | `create_tour.lambda_handler` | `src/functions/tours/create_tour.py` |
| `POST /tours/{tourId}/archive` | `archive_tour.lambda_handler` | `src/functions/tours/archive_tour.py` |

**`create_tour.py`** must:
1. Validate free-form tourId (3-50 chars, `[a-zA-Z0-9_.-]`, starts with letter/number)
2. Check tourId uniqueness in the shared Tour table
3. Create Tour record (status: PROVISIONING)
4. Create 4 DynamoDB tables: `{STACK_NAME}-TourRider-{tourId}`, `{STACK_NAME}-Ride-{tourId}`, `{STACK_NAME}-CheckIn-{tourId}`, `{STACK_NAME}-User-{tourId}`
5. Wait for tables to become ACTIVE
6. Update Tour status to PLANNING
7. Restricted to ADMINISTRATOR role

**`archive_tour.py`** must:
1. Optionally export tour-specific table data to S3
2. Delete 4 tour-specific DynamoDB tables
3. Update Tour status to ARCHIVED in shared Tour table
4. Restricted to ADMINISTRATOR role

**Action:** Create both Lambda functions and wire them in template.yaml.

---

## 28. `dynamodb_utils.py` Needs Dynamic Table Name Support

The current `dynamodb_utils.py` resolves table names from environment variables (`table_name_env` pattern). With the hybrid table strategy, tour-specific tables are named dynamically: `{STACK_NAME}-{TableType}-{tourId}`.

Lambda functions accessing tour-specific tables need to construct the table name at runtime using:
- `STACK_NAME` environment variable
- Table type (e.g., `TourRider`, `Ride`, `CheckIn`, `User`)
- `tourId` from the request

**Action:** Add a utility function (e.g., `get_tour_table_name(table_type, tour_id)`) to `dynamodb_utils.py` that builds the full table name. Update functions that access tour-specific tables to use this instead of `table_name_env`.

---

## 29. Tour Model in `models.py` Needs Updates

The `models.py` Tour-related definitions need to reflect the updated SolutionDesign:

| Change | Detail |
|---|---|
| `TourStatus` enum | Add `PROVISIONING` between `PLANNING` and `ACTIVE` |
| Tour model fields | Add `provisionedAt` (ISO 8601 timestamp) |
| Tour model fields | Add `archivedAt` (ISO 8601 timestamp) |
| Tour ID format | Change from year-based (`TOUR2026`) to free-form (e.g., `India-Coast-2026`) |
| Tour PK format | Change from `TOUR#<year>` to `TOUR#<tourId>` |
| Validation | Add `validate_tour_id()` for free-form tourId validation |

**Action:** Update `models.py` and `validation.py` to reflect the new Tour model.

---

## 30. Lambda Functions Need Refactoring for Tour-Specific Table Access

With tour-specific tables, all Lambda functions that access TourRider, Ride, CheckIn, or User data must:

1. Accept `tourId` as a path or query parameter
2. Derive the correct table name using `{STACK_NAME}-{TableType}-{tourId}`
3. Use simplified key design (no tour prefix in PK — e.g., `RIDER#<riderId>` not `TOUR#<tourId>#RIDER#<riderId>`)

**Affected functions (at minimum):**
- `get_tour_rider.py`, `get_tour_riders.py` → TourRider-{tourId} table
- `get_todays_ride.py`, `get_ride.py`, `create_ride.py`, `update_ride.py`, `close_ride.py`, `list_rides.py` → Ride-{tourId} table
- `create_checkin.py`, `get_ride_checkins.py`, `get_dashboard_data.py` → CheckIn-{tourId} table (and Ride-{tourId})
- `get_current_user.py`, `list_tour_users.py` → User-{tourId} table

This also impacts TODO #10 (route/path parameter mismatch) — `tourId` must now be available in routes for all tour-specific operations.

**Action:** Refactor all affected Lambda functions once template.yaml and dynamodb_utils.py changes are in place.
