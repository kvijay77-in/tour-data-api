# TODO: Documentation vs. Development Gap Analysis

Identified on: 2026-02-14

This document lists all gaps found between project documentation and actual development artifacts. Each item should be reviewed and resolved before deployment.

---

## 1. CRITICAL: Missing Lambda Function Files

template.yaml references handler files that do not exist on disk. **SAM build will fail.**

| template.yaml Resource | Expected Handler | Expected File |
|---|---|---|
| `ListToursFunction` | `list_tours.lambda_handler` | `src/functions/tours/list_tours.py` |
| `GetTourRidersFunction` | `get_tour_riders.lambda_handler` | `src/functions/riders/get_tour_riders.py` |

**Action:** Either create the missing files or remove the resources from template.yaml.

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
| List tours | Not in README | `GET /tours?year={year}&status={status}` | `GET /v1/tours` (handler missing) |
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

| Field | SolutionDesign / models.py | Mock Data |
|---|---|---|
| Tour `PK` | `TOUR#<year>` (e.g., `TOUR#2026`) | `TOUR#001` |
| Tour `tourId` | `TOUR2026` (no `#`) | `TOUR#001` (includes `#`) |
| Rider Profile `PK` | `PROFILE#<uuid>` | `RIDER#R001` (wrong prefix) |
| Rider `riderId` | `R1`, `R57` (no zero-padding per Requirements) | `R001`, `R002` (zero-padded) |
| User `role` | `ADMINISTRATOR`, `SUPER_USER`, etc. (per `UserRole` enum) | `ADMIN` (not a valid enum value) |
| CheckIn `SK` | `CHECKIN#<riderId>#<stageNumber>#<timestamp>` | `2026-02-11T10:30:00#R001` (wrong format) |

**Action:** Fix mock data to match the data model specification.

---

## 22. SolutionDesign References Non-Existent `src/authorizer/` Directory

The Infrastructure as Code section in SolutionDesign.md lists `src/authorizer/` for a JWT authorizer. This directory does not exist and no custom authorizer Lambda is implemented.

**Action:** Remove the reference from SolutionDesign, or create the authorizer if needed.

---

## 23. Infrastructure Guide References Wrong Utility Filename

`docs/infrastructure-guide.md` (Project Statistics section) lists `response_utils.py` as a shared component. The actual filename is `response.py`.

**Action:** Update infrastructure-guide to reference `response.py`.

---

## 24. Tour Table GSI Documented but Not Implemented

`docs/deployment-guide.md` states the Tour table has `GSI: StatusIndex (for status-based queries)`. The actual Tour table in template.yaml has **no GSIs** — only a simple hash key (`PK`).

**Action:** Either add the StatusIndex GSI to template.yaml, or correct the deployment guide.

---

## 25. `get_current_user.py` Declares Unused Environment Variable

`src/functions/users/get_current_user.py` reads `USER_TABLE` from environment but never queries DynamoDB — it only returns JWT claims. Minor but unnecessary dependency.

**Action:** Remove the unused `USER_TABLE` reference, or document that it's reserved for future use.
