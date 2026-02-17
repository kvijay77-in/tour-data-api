# TODO: Documentation vs. Development Gap Analysis

Identified on: 2026-02-14
Last reviewed: 2026-02-19

This document lists all gaps found between project documentation and actual development artifacts. Each item should be reviewed and resolved before deployment.

> **Note:** SolutionDesign.md was updated on 2026-02-14 with the hybrid table strategy (shared + tour-specific tables), free-form tourId, SubscriptionId as tag-only, and tour provisioning/archiving workflows. Several items below have been updated to reflect the new design. New items (#26–#30) were added for design-driven implementation work.

> **Status (2026-02-17):** All 30 items are now **RESOLVED**. All 20 Lambda functions implemented, template.yaml restructured with JWT authorizer, common layer utilities updated, tests aligned, CI/CD workflow fixed, Makefile updated, and all documentation updated to reflect the hybrid table design.

> **Update (2026-02-17):** Items #31–#33 added for deployment experience improvements. #31 and #33 RESOLVED. #32 is a future TODO.

---

## 31. ✅ RESOLVED: Auto-Create Cognito User Pool During Deployment

Previously, users had to manually create a Cognito User Pool and App Client via CLI commands, construct an ARN, and add it to `samconfig.toml`. This was the hardest manual step for non-technical users.

**Resolution:** Cognito User Pool and User Pool Client are now auto-created as CloudFormation resources in `template.yaml`. The `CognitoUserPoolArn` and `CognitoAppClientId` parameters default to empty, which triggers auto-creation. Users can still provide their own values to use an existing User Pool.

---

## 32. 🔲 TODO: Web-Based Admin Panel

A browser-based admin UI for tour organizers to manage tours, riders, rides, and view dashboards without using API tools (curl, Postman, etc.). Would be served as static files from the existing S3 bucket at zero extra cost.

**Scope:** This is a significant front-end feature outside the current "backend only" project scope. Deferred for future consideration.

---

## 33. ✅ RESOLVED: OIDC Authentication for GitHub Actions + Preflight Check

**OIDC:** GitHub Actions now supports OIDC-based authentication to AWS (no static access keys). A bootstrap CloudFormation template (`cloudformation/github-oidc.yaml`) creates the OIDC provider and IAM deploy role. `make setup-github-oidc` automates the setup. CI/CD workflow updated to support both OIDC and legacy access keys.

**Preflight Check:** `make check-config` runs `scripts/preflight-check.sh` to validate AWS CLI, SAM CLI, Python, credentials, and template before deployment.

---

## 1. ✅ RESOLVED: Missing Lambda Function Files

~~template.yaml references handler files that do not exist on disk. **SAM build will fail.**~~

| template.yaml Resource | Expected Handler | Expected File | Status |
|---|---|---|---|
| `ListToursFunction` | `list_tours.lambda_handler` | `src/functions/tours/list_tours.py` | ✅ Created |
| `GetTourRidersFunction` | `get_tour_riders.lambda_handler` | `src/functions/riders/get_tour_riders.py` | ✅ Created |

**Resolution:** Both Lambda function files have been created (2026-02-17).

**Notes:**
- `list_tours.py`: Lists all tours with optional status filter via StatusIndex GSI
- `get_tour_riders.py`: Retrieves all riders for a specific tour with enriched profile data
- Both functions fully refactored for hybrid table strategy

---

## 2. ✅ RESOLVED: Lambda Functions Not Wired in template.yaml

~~These 5 functions exist on disk but have no corresponding `AWS::Serverless::Function` resource in template.yaml, making them unreachable via API Gateway.~~

**Resolution:** All functions are now wired in the restructured template.yaml with proper HTTP API routes. Routes follow the `/v1/` prefix and SolutionDesign conventions.

---

## 3. ✅ RESOLVED: API Route Mismatches Across Documentation and Code

~~README, SolutionDesign, and template.yaml disagree on endpoint paths for many routes.~~

**Resolution:** All API routes in template.yaml, Lambda functions, README, and docs now follow the SolutionDesign conventions with `/v1/` prefix. All tour-specific operations use `/v1/tours/{tourId}/` prefix.

---

## 4. ✅ RESOLVED: README Missing `/v1/` Prefix on All API Endpoints

~~All template.yaml routes use the `/v1/` prefix (e.g., `GET /v1/tours/active`), but README documents all 15 endpoints without it.~~

**Resolution:** README updated with all 20 endpoints using the `/v1/` prefix. Endpoints section now matches template.yaml routes exactly.

---

## 5. ✅ RESOLVED: `bad_request_response()` Does Not Exist

~~Approximately 9 Lambda functions import or call `bad_request_response()`, but this function does **not exist** in `src/layers/common/python/response.py`.~~

**Resolution:** `bad_request_response(message, details=None)` added to `response.py`. All Lambda functions now use it correctly.

---

## 6. ✅ RESOLVED: `validate_date` Does Not Exist in validation.py

~~`create_ride.py` and `update_ride.py` import `validate_date`, but the actual function name is `validate_iso_date`.~~

**Resolution:** All Lambda functions now import and use `validate_iso_date`.

---

## 7. ✅ RESOLVED: `error_response()` Called with Wrong Signature

~~~8 functions call `error_response()` with a single string argument, but its signature is `error_response(error_code, message, status_code=400, details=None)`.~~

**Resolution:** All Lambda functions now use `bad_request_response()`, `not_found_response()`, `conflict_response()`, etc. with correct signatures.

---

## 8. ✅ RESOLVED: `not_found_response()` Called with Wrong Signature

~~~5 functions call `not_found_response()` with a single formatted string, but its signature is `not_found_response(resource, identifier)` (requires 2 arguments).~~

**Resolution:** All Lambda functions now call `not_found_response(resource, identifier)` with both arguments.

---

## 9. ✅ RESOLVED: `table_name` vs `table_name_env` Parameter Mismatch

~~`dynamodb_utils.py` functions all expect a `table_name_env` parameter but ~10 Lambda functions pass `table_name=` with the resolved table name string instead.~~

**Resolution:** Hybrid table strategy implemented. Shared tables use `table_name_env=` (e.g., `get_item(table_name_env='TOUR_TABLE', ...)`). Tour-specific tables use `get_tour_item(table_type='Ride', tour_id=tour_id, ...)` and related `*_tour_*` functions that derive names dynamically as `{STACK_NAME}-{TableType}-{tourId}`.

---

## 10. ✅ RESOLVED: Route/Path Parameter Mismatch in Lambda Functions

~~Several ride-related functions expect `tourId` from path parameters, but the API routes in template.yaml do not include `{tourId}`.~~

**Resolution:** All tour-specific operations now use `/v1/tours/{tourId}/` prefix in routes. Both template.yaml routes and Lambda functions consistently extract `tourId` from path parameters.

---

## 11. ✅ RESOLVED: `get_tour.py` Missing Import

~~`src/functions/tours/get_tour.py` uses `error_response` but does not import it.~~

**Resolution:** `get_tour.py` rewritten with correct imports: `bad_request_response`, `not_found_response`, `success_response`, `internal_error_response`.

---

## 12. ✅ RESOLVED: DynamoDB GSI: `RideIdIndex` Referenced but Not Defined

~~`get_dashboard_data.py` queries a `RideIdIndex` GSI on the Ride table, but this index does not exist.~~

**Resolution:** `get_dashboard_data.py` rewritten. Now uses `get_tour_item('Ride', tour_id, {'PK': f'RIDE#{ride_id}'})` — a direct `get_item` on the tour-specific Ride table. No `RideIdIndex` GSI needed.

---

## 13. ✅ RESOLVED: Ride Status Enum Mismatch: `SCHEDULED` vs `PLANNED`

~~`create_ride.py` uses `RideStatus.SCHEDULED` which does not exist.~~

**Resolution:** All Lambda functions and README now use `RideStatus.PLANNED` consistently.

---

## 14. ✅ RESOLVED: `validate_stage_number()` Called with Wrong Argument Count

~~`create_ride.py` calls `validate_stage_number(body['stageNumber'])` with 1 argument.~~

**Resolution:** `create_ride.py` rewritten. Stages are now handled as a list within the ride object; `validate_stage_number` is no longer called directly.

---

## 15. ✅ RESOLVED: Python Runtime Version Inconsistency

~~README.md and Development guide reference Python 3.12+ but template.yaml and CI/CD use 3.11.~~

**Resolution:** All references aligned to Python 3.11 (matching template.yaml and CI/CD). Updated README prerequisites, development guide troubleshooting, and infrastructure guide project statistics.

---

## 16. ✅ RESOLVED: Lambda Function Count Mismatch

~~README, infrastructure guide, and deployment guide reported incorrect Lambda function counts.~~

**Resolution:** All documentation updated to reflect the actual count of **20 Lambda functions** with correct distribution:
- Tours: 5 (get_active, get_tour, list_tours, create_tour, archive_tour)
- Riders: 4 (get_rider_profile, update_rider_profile, get_tour_riders, get_tour_rider)
- Rides: 6 (get_todays_ride, get_ride, list_rides, create_ride, update_ride, close_ride)
- Check-ins: 3 (create_checkin, get_ride_checkins, get_dashboard_data)
- Users: 2 (get_current_user, list_tour_users)

---

## 17. ✅ RESOLVED: Cognito JWT Authorizer Not Attached to Routes

~~template.yaml has a `HasCognitoUserPool` condition but no `Auth` property is attached to any `HttpApi` event.~~

**Resolution:** JWT authorizer added to the HttpApi resource in template.yaml. Uses `!If` condition:
- When `CognitoUserPoolArn` is provided: `DefaultAuthorizer: CognitoAuthorizer` with JWT configuration (issuer derived from ARN, audience from new `CognitoAppClientId` parameter)
- When not provided: Auth block is `AWS::NoValue`, leaving all routes open (suitable for dev/testing)
- AWS setup guide updated with deployment instructions for Cognito parameters.

---

## 18. ✅ RESOLVED: CI/CD Workflow Deploy Jobs Never Execute

~~Deploy jobs had branch-based conditions (`github.ref == 'refs/heads/develop' && github.event_name == 'push'`) but the only trigger was `workflow_dispatch`.~~

**Resolution:** Deploy job conditions updated to use `github.event.inputs.environment` from the `workflow_dispatch` input. Each deploy job (dev, test, prod) now runs when its corresponding environment is selected. Removed the `needs: deploy-test` dependency from prod job so environments can be deployed independently.

---

## 19. ✅ RESOLVED: Makefile Targets vs. Documentation

~~`make logs FUNCTION=X` didn't accept FUNCTION parameter; `make logs-tail` didn't exist.~~

**Resolution:** Makefile updated:
- `make logs` now accepts optional `FUNCTION=X` parameter (tails all if omitted, specific function if provided)
- `make logs-tail FUNCTION=X` added as alias for `make logs-function`
- Documentation references updated to match actual targets.

---

## 20. ✅ RESOLVED: Project Structure Documentation Incomplete

~~`docs/project-structure.md` was missing several files and directories.~~

**Resolution:** `project-structure.md` completely rewritten to reflect the full actual file structure including:
- All 20 Lambda function files with their API routes
- All docs files
- Test files (conftest.py, test_lambda_functions.py, fixtures/mock_data.py)
- Events files
- `.github/copilot-instructions.md`
- `__init__.py` files in all packages
- Updated descriptions reflecting hybrid table strategy.

---

## 21. ✅ RESOLVED: Mock Data Inconsistencies with Data Model

~~Test fixtures in `tests/fixtures/mock_data.py` use data formats that don't match SolutionDesign or models.py.~~

**Resolution:** `mock_data.py` completely rewritten. Tours use `TOUR#{tourId}` PK with free-form ID (e.g., `TestTour-2026`). RiderProfiles use `PROFILE#` prefix. TourRiders/Rides/CheckIns/Users use simplified PKs without tour prefix. All field names and enum values match the updated models.

---

## 22. ~~SolutionDesign References Non-Existent `src/authorizer/` Directory~~ — RESOLVED

~~The Infrastructure as Code section in SolutionDesign.md lists `src/authorizer/` for a JWT authorizer. This directory does not exist and no custom authorizer Lambda is implemented.~~

**Resolved:** The `src/authorizer/` reference was removed from SolutionDesign.md on 2026-02-14 during the design update.

---

## 23. ✅ RESOLVED: Infrastructure Guide References Wrong Utility Filename

~~`docs/infrastructure-guide.md` (Project Statistics section) lists `response_utils.py` as a shared component.~~

**Resolution:** Infrastructure guide updated to reference `response.py` (the actual filename).

---

## 24. ✅ RESOLVED: Tour Table GSI Documented but Not Implemented

~~`docs/deployment-guide.md` states the Tour table has `GSI: StatusIndex` but template.yaml had no GSIs.~~

**Resolution:** The Tour table in template.yaml now includes `StatusIndex` GSI with partition key `status`. Used by `get_active.py` and `list_tours.py` for efficient status-based queries.

---

## 25. ✅ RESOLVED: `get_current_user.py` Declares Unused Environment Variable

~~`src/functions/users/get_current_user.py` reads `USER_TABLE` from environment but never queries DynamoDB.~~

**Resolution:** `get_current_user.py` rewritten. No longer references `USER_TABLE` or DynamoDB. Returns JWT claims only.

---

# New Items from SolutionDesign.md Update (2026-02-14)

The following items were identified after the SolutionDesign.md was updated with the hybrid table strategy (shared + tour-specific tables), free-form tourId, and tour provisioning/archiving workflows.

---

## 26. ✅ RESOLVED: template.yaml Needs Restructuring for Hybrid Table Strategy

~~The current template.yaml defines 6 DynamoDB tables all as SAM-managed resources.~~

**Resolution:** template.yaml completely restructured:
- Shared tables (Tour with StatusIndex GSI, RiderProfile) remain SAM-managed
- Tour-specific tables (TourRider, Ride, CheckIn, User) removed from template — provisioned at runtime by `create_tour.py`
- `STACK_NAME`, `ENVIRONMENT`, `SUBSCRIPTION_ID` environment variables added to all functions
- `SubscriptionId` added as SAM template parameter
- IAM policies updated with `dynamodb:CreateTable`, `dynamodb:DeleteTable`, `dynamodb:DescribeTable`, `dynamodb:TagResource`
- S3 bucket added for archive exports
- All 20 Lambda functions wired with proper HTTP API routes

---

## 27. ✅ RESOLVED: New Lambda Functions Needed for Tour Provisioning and Archiving

~~SolutionDesign.md defines two new API endpoints with no corresponding Lambda functions.~~

**Resolution:** Both functions created and wired in template.yaml:
- `src/functions/tours/create_tour.py`: Validates free-form tourId, creates Tour record (PROVISIONING → PLANNING), provisions 4 DynamoDB tables with GSIs, tags with project/environment/subscription metadata
- `src/functions/tours/archive_tour.py`: Optionally exports tour data to S3, deletes 4 tour-specific tables, updates Tour status to ARCHIVED

---

## 28. ✅ RESOLVED: `dynamodb_utils.py` Needs Dynamic Table Name Support

~~The current `dynamodb_utils.py` resolves table names only from environment variables. Tour-specific tables named dynamically need a new mechanism.~~

**Resolution:** `dynamodb_utils.py` updated with dual API pattern:
- Shared tables: `get_item(table_name_env=...)`, `put_item(table_name_env=...)`, `query_items(table_name_env=...)`, etc.
- Tour-specific tables: `get_tour_item(table_type=..., tour_id=...)`, `put_tour_item(...)`, `query_tour_items(...)`, etc.
- `get_tour_table_name(table_type, tour_id)` utility builds `{STACK_NAME}-{TableType}-{tourId}` at runtime

---

## 29. ✅ RESOLVED: Tour Model in `models.py` Needs Updates

~~The `models.py` Tour-related definitions need to reflect the updated SolutionDesign.~~

**Resolution:** `models.py` updated:
- `TourStatus` enum includes `PROVISIONING`
- `TOUR_TABLE_TYPES = ['TourRider', 'Ride', 'CheckIn', 'User']`
- Tour PK format: `TOUR#<tourId>` with free-form tourId
- `provisionedAt` and `archivedAt` fields documented
- `validation.py` updated: `validate_tour_id()` accepts free-form IDs (3-50 chars, `[a-zA-Z0-9_.-]`)

---

## 30. ✅ RESOLVED: Lambda Functions Need Refactoring for Tour-Specific Table Access

~~All Lambda functions accessing TourRider, Ride, CheckIn, or User data must be refactored to use tour-specific table patterns.~~

**Resolution:** All 16 existing Lambda functions rewritten to use the hybrid table strategy:
- Tour-specific operations use `get_tour_item()`, `put_tour_item()`, `query_tour_items()`, `scan_tour_items()` with `table_type` and `tour_id` parameters
- Simplified PK design: `RIDER#<riderId>`, `RIDE#<rideId>`, etc. (no tour prefix)
- All routes include `{tourId}` in path for tour-specific operations
- Test files (`conftest.py`, `mock_data.py`, `test_lambda_functions.py`, `test_validation.py`) updated to match
