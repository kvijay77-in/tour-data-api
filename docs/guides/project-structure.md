# Project Folder Structure

Following structure will be used in the project and any addition/restructure should be updated here. But first changes should be approved before it be applied.

```
tour-data-api/
├── .github/
│   ├── copilot-instructions.md        # Copilot AI coding instructions
│   └── workflows/
│       └── ci-cd.yml                  # GitHub Actions CI/CD pipeline
├── docs/
│   ├── aws-setup-guide.md            # AWS CLI and Cognito setup
│   ├── deployment-guide.md           # CI/CD, multi-environment deployment
│   ├── development-guide.md          # Local development and testing
│   ├── docs-index.md                 # Documentation index
│   ├── infrastructure-guide.md       # Resource tagging, monitoring, costs
│   ├── project-structure.md          # This file - project organization
│   ├── Requirements.md               # Detailed requirements and use cases
│   └── SolutionDesign.md             # Architecture and design
├── src/
│   ├── functions/                     # Lambda function handlers
│   │   ├── artifacts/
│   │   │   ├── __init__.py
│   │   │   ├── presign_tour_artifact_upload.py  # POST /v1/artifacts/tour/presign-upload
│   │   │   ├── presign_ride_artifact_upload.py  # POST /v1/artifacts/ride/presign-upload
│   │   │   ├── delete_tour_artifact.py          # DELETE /v1/artifacts/tour/{tourId}/{artifactId}
│   │   │   ├── delete_ride_artifact.py          # DELETE /v1/artifacts/ride/{tourId}/{rideId}/{artifactId}
│   │   │   ├── get_tour_artifacts.py            # GET /v1/tours/{tourId}/artifacts
│   │   │   └── get_ride_artifacts.py            # GET /v1/tours/{tourId}/rides/{rideId}/artifacts
│   │   ├── checkins/
│   │   │   ├── __init__.py
│   │   │   ├── cancel_checkin.py      # POST /v1/tours/{tourId}/rides/{rideId}/checkins/{checkInId}/cancel
│   │   │   ├── create_checkin.py      # POST /v1/tours/{tourId}/checkins
│   │   │   ├── get_dashboard_data.py  # GET /v1/tours/{tourId}/rides/{rideId}/dashboard
│   │   │   ├── get_dashboard_progress.py # GET /v1/tours/{tourId}/rides/{rideId}/dashboard/progress
│   │   │   ├── get_ride_checkins.py   # GET /v1/tours/{tourId}/rides/{rideId}/checkins
│   │   │   ├── get_rider_checkins.py  # GET /v1/tours/{tourId}/riders/{riderId}/checkins
│   │   │   └── get_rider_ride_checkins.py # GET /v1/tours/{tourId}/riders/{riderId}/rides/{rideNo}/checkins
│   │   ├── events/
│   │   │   ├── __init__.py
│   │   │   ├── list_events.py         # GET /v1/tours/{tourId}/events
│   │   │   ├── get_event.py           # GET /v1/tours/{tourId}/events/{eventId}
│   │   │   ├── create_event.py        # POST /v1/tours/{tourId}/events
│   │   │   ├── update_event.py        # PUT /v1/tours/{tourId}/events/{eventId}
│   │   │   ├── list_occurrences.py    # GET /v1/tours/{tourId}/events/{eventId}/occurrences
│   │   │   ├── get_occurrence.py      # GET /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}
│   │   │   ├── create_occurrence.py   # POST /v1/tours/{tourId}/events/{eventId}/occurrences
│   │   │   ├── update_occurrence.py   # PUT /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}
│   │   │   ├── get_activity_overrides.py # GET /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/activity-overrides
│   │   │   ├── update_activity_overrides.py # PUT /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/activity-overrides
│   │   │   ├── start_occurrence.py    # POST /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/start
│   │   │   ├── complete_occurrence.py # POST /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/complete
│   │   │   ├── cancel_occurrence.py   # POST /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/cancel
│   │   │   ├── create_activity_record.py # POST /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/records
│   │   │   ├── cancel_activity_record.py # POST /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/records/{recordId}/cancel
│   │   │   ├── get_dashboard.py       # GET /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/dashboard
│   │   │   ├── get_event_dashboard_progress.py # GET /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/dashboard/progress
│   │   │   ├── get_rider_progress.py  # GET /v1/tours/{tourId}/riders/{riderId}/events/progress
│   │   │   ├── get_reconciliation.py  # GET /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/reconciliation
│   │   │   └── get_bootstrap.py       # GET /v1/tours/{tourId}/events/bootstrap
│   │   ├── hotels/
│   │   │   ├── __init__.py
│   │   │   ├── list_hotels.py         # GET /v1/tours/{tourId}/hotels
│   │   │   ├── create_hotel.py        # POST /v1/tours/{tourId}/hotels
│   │   │   ├── update_hotel.py        # PUT /v1/tours/{tourId}/hotels/{hotelId}
│   │   │   ├── get_hotel_stays_by_date.py # GET /v1/tours/{tourId}/hotelstays?date={date}
│   │   │   ├── get_hotel_stays_by_rider.py # GET /v1/tours/{tourId}/riders/{riderId}/hotelstays
│   │   │   ├── get_hotel_stays_by_hotel.py # GET /v1/tours/{tourId}/hotels/{hotelId}/hotelstays?date={date}
│   │   │   ├── update_hotel_stay.py   # PUT /v1/tours/{tourId}/hotelstays/{stayDate}/{riderId}
│   │   │   ├── presign_upload.py      # POST /v1/tours/{tourId}/hotelstays/uploads/presign
│   │   │   ├── get_upload_status.py   # GET /v1/tours/{tourId}/hotelstays/uploads/{uploadId}
│   │   │   ├── process_upload.py      # EventBridge (S3 Object Created) - hotel CSV validate + apply
│   │   │   └── process_upload_failure.py # OnFailure destination of process_upload (timeout/crash recovery)
│   │   ├── config/
│   │   │   ├── __init__.py
│   │   │   └── get_config.py          # GET /v1/config
│   │   ├── riders/
│   │   │   ├── __init__.py
│   │   │   ├── cancel_rider_exit.py # POST /v1/tours/{tourId}/riders/{riderId}/exit/cancel
│   │   │   ├── create_rider_profile.py # POST /v1/riders/profile and /v1/riders/profile/{profileId}
│   │   │   ├── exit_tour_rider.py    # POST /v1/tours/{tourId}/riders/{riderId}/exit
│   │   │   ├── get_rider_profile.py   # GET /v1/riders/profile/{profileId}
│   │   │   ├── get_rider_tours.py # GET /v1/profile/{profileId}/tours
│   │   │   ├── get_rider_tour.py # GET /v1/profile/{profileId}/tours/{tourId}
│   │   │   ├── get_rider_statistics.py # GET /v1/tours/{tourId}/riders/{riderId}/statistics
│   │   │   ├── get_tour_rider.py      # GET /v1/tours/{tourId}/riders/{riderId}
│   │   │   ├── get_rider_ride_details.py # GET /v1/tours/{tourId}/rides/{rideId}/riders/{riderId}/details
│   │   │   ├── get_tour_riders.py     # GET /v1/tours/{tourId}/riders
│   │   │   ├── get_tour_rider_names.py # GET /v1/tours/{tourId}/riders/names
│   │   │   ├── register_tour_rider.py # POST /v1/tours/{tourId}/riders
│   │   │   ├── release_rider_baggage.py # POST /v1/tours/{tourId}/riders/{riderId}/baggage/release
│   │   │   ├── update_rider_profile.py # PUT /v1/riders/profile/{profileId}
│   │   │   ├── link_rider_cognito_user.py # GET|POST|DELETE /v1/riders/link/{cognitoUserName}
│   │   │   ├── upload_profile_picture.py # POST /v1/riders/profile/{profileId}/picture
│   │   │   └── get_profile_picture.py   # GET /v1/riders/profile/{profileId}/picture
│   │   ├── rides/
│   │   │   ├── __init__.py
│   │   │   ├── close_ride.py          # POST /v1/tours/{tourId}/rides/{rideId}/close
│   │   │   ├── close_pit_stop.py      # POST /v1/tours/{tourId}/rides/{rideId}/stages/{stageNumber}/pitstop/close
│   │   │   ├── create_ride.py         # POST /v1/tours/{tourId}/rides
│   │   │   ├── get_ride.py            # GET /v1/tours/{tourId}/rides/{rideId}
│   │   │   ├── get_todays_ride.py     # GET /v1/tours/{tourId}/rides/today
│   │   │   ├── list_rides.py          # GET /v1/tours/{tourId}/rides
│   │   │   ├── open_pit_stop.py       # POST /v1/tours/{tourId}/rides/{rideId}/stages/{stageNumber}/pitstop/open
│   │   │   ├── open_ride.py           # POST /v1/tours/{tourId}/rides/open
│   │   │   ├── start_ride.py          # POST /v1/tours/{tourId}/rides/start
│   │   │   └── update_ride.py         # PUT /v1/tours/{tourId}/rides/{rideId}
│   │   ├── tours/
│   │   │   ├── __init__.py
│   │   │   ├── archive_tour.py        # POST /v1/tours/{tourId}/archive
│   │   │   ├── create_tour.py         # POST /v1/tours
│   │   │   ├── get_active.py          # GET /v1/tours/active
│   │   │   ├── get_tour.py            # GET /v1/tours/{tourId}
│   │   │   ├── list_tours.py          # GET /v1/tours
│   │   │   ├── provision_tour.py      # PUT /v1/tours/{tourId}/provision
│   │   │   └── update_tour.py         # PUT /v1/tours
│   │   └── users/
│   │       ├── __init__.py
│   │       ├── create_managed_user.py # POST /v1/admin/usermgmt/users
│   │       ├── delete_managed_user.py # DELETE /v1/admin/usermgmt/users/{cognitoUserId}
│   │       ├── disable_managed_user.py # POST /v1/admin/usermgmt/users/{cognitoUserId}/disable
│   │       ├── enable_managed_user.py # POST /v1/admin/usermgmt/users/{cognitoUserId}/enable
│   │       ├── list_cognito_users.py  # GET /v1/users/cognito
│   │       ├── get_current_user.py    # GET /v1/users/me
│   │       ├── list_managed_users.py  # GET /v1/admin/usermgmt/users
│   │       ├── list_role_groups.py    # GET /v1/admin/usermgmt/roles
│   │       ├── list_tour_users.py     # GET /v1/tours/{tourId}/users
│   │       ├── get_current_tour_user.py # GET /v1/tours/{tourId}/users/me
│   │       ├── create_tour_user.py    # POST /v1/tours/{tourId}/users
│   │       ├── update_managed_user.py # PUT /v1/admin/usermgmt/users/{cognitoUserId}
│   │       ├── update_tour_user.py    # PUT /v1/tours/{tourId}/users/{userId}
│   │       └── usermgmt_common.py     # Shared Cognito admin user management helpers
│   │   └── notifications/
│   │       ├── __init__.py
│   │       ├── common.py
│   │       ├── register_device.py     # POST /v1/notifications/devices
│   │       ├── delete_device.py       # DELETE /v1/notifications/devices/{token}
│   │       ├── get_notifications.py   # GET /v1/notifications
│   │       ├── get_unread_count.py    # GET /v1/notifications/unread-count
│   │       ├── mark_read.py           # PUT /v1/notifications/read
│   │       ├── send_notification.py   # POST /v1/notifications
│   │       ├── send_reminder.py       # POST /v1/notifications/reminders
│   │       ├── list_rules.py          # GET /v1/admin/notification-rules
│   │       ├── get_rule.py            # GET /v1/admin/notification-rules/{ruleId}
│   │       ├── create_rule.py         # POST /v1/admin/notification-rules
│   │       ├── update_rule.py         # PUT /v1/admin/notification-rules/{ruleId}
│   │       ├── delete_rule.py         # DELETE /v1/admin/notification-rules/{ruleId}
│   │       ├── push_sender.py         # Stream-to-Expo sender
│   │       ├── create_notification.py # Legacy POST /v1/tours/{tourId}/notifications
│   │       ├── list_notifications.py  # Legacy GET /v1/tours/{tourId}/notifications
│   │       └── update_notification.py # Legacy PUT /v1/tours/{tourId}/notifications/{notificationId}
│   └── layers/
│       └── common/                    # Shared utilities layer
│           ├── __init__.py
│           ├── requirements.txt       # Layer dependencies
│           ├── dynamodb_utils.py      # DynamoDB operations (shared + tour-specific)
│           ├── event_engine.py        # Shared events/hotels/tour-user business logic helpers
│           ├── logger.py              # Logging utilities
│           ├── models.py              # Data models and enums
│           ├── notification_service.py # Notification framework service
│           ├── rbac.py                # RBAC utilities: Permission enum, group→permission mapping, enforcement helpers
│           ├── response.py            # API response utilities
│           ├── tour_provisioning.py   # Tour-specific table provisioning logic
│           └── validation.py          # Input validation
├── tests/                             # Unit and integration tests
│   ├── __init__.py
│   ├── conftest.py                    # Pytest fixtures and setup
│   ├── README.md                      # Testing documentation
│   ├── test_lambda_functions.py       # Lambda function tests
│   ├── test_checkin_enhancements.py  # Check-in business logic tests (QR, manual, fallback)
│   ├── test_rbac.py                   # RBAC utility and handler enforcement tests
│   ├── test_rider_app_apis.py        # Rider-app API Lambda function tests
│   ├── test_rider_exit_apis.py       # Rider exit + baggage lifecycle API tests
│   ├── test_event_engine_apis.py     # Event engine, hotel, and tour-user API tests
│   ├── test_hotel_upload_processor.py # Hotel allocation CSV processor + failure handler tests
│   ├── test_tour_provisioning.py     # Tour provisioning utility tests
│   ├── test_validation.py            # Validation utility tests
│   └── fixtures/
│       ├── __init__.py
│       └── mock_data.py              # Test mock data
├── events/                            # Sample event payloads for local testing
│   ├── create-checkin.json
│   ├── get-active-tour.json
│   └── get-tour-rider.json
├── .gitignore                         # Git ignore file
├── Makefile                           # Build and deployment automation
├── README.md                          # Project documentation
├── TODO.md                            # Gap analysis and task tracking
├── pytest.ini                         # Test configuration
├── requirements-dev.txt               # Development dependencies
├── samconfig.toml                     # SAM CLI configuration
├── template.yaml                      # SAM CloudFormation template
├── cloudformation/                    # Supplementary CloudFormation templates
│   └── github-oidc.yaml              # GitHub OIDC provider + IAM deploy role
└── scripts/                           # Utility scripts
    ├── preflight-check.sh            # Pre-deployment environment validation
    ├── dev-test-setup.sh             # Exports env vars for dev API testing
    ├── provision_tour.py             # CLI script for tour provisioning (deployment method)
    ├── cleanup_tour_tables.py        # Deletes tour-specific DynamoDB tables not managed by CloudFormation
    ├── load_test_data.py             # Load JSON data into a DynamoDB table
    ├── seed_app_config.py            # Seed shared AppConfig defaults
    ├── seed_notification_rules.py    # Seed default NotificationRule rows
    └── simulate/                     # Test data simulation utility
        ├── README.md                 # Simulation utility documentation
        ├── generate_data.py          # Main data generation script
        ├── scenarios/                # Scenario configuration files
        │   └── tot_2026.yaml         # TOT-2026 tour scenario template
        └── output/                   # Dry-run JSON output (git-ignored)
```

**Key Structure Notes:**

### Source Code (`src/`)
- **`functions/`**: Contains all Lambda function handlers organized by feature domain (checkins, config, riders, rides, tours, users, notifications). Each domain has an `__init__.py` for package initialization.
- **`layers/common/`**: Shared utilities and dependencies used across all Lambda functions. Python modules (models, validation, database operations, logging, response formatting, RBAC) and `requirements.txt` are at the layer root for correct SAM build packaging.
  - **`rbac.py`**: Server-side RBAC utilities. Defines the `Permission` enum (API-level actions), the `GROUP_PERMISSIONS` mapping for standard Cognito groups, dynamic `PS_<n>_USER` pit-stop role handling, and helper functions (`get_user_groups`, `get_user_permissions`, `require_permission`) used by Lambda handlers to enforce access control without coupling to Cognito group names.

### Documentation (`docs/`)
- **`Requirements.md`**: Detailed business requirements and use cases
- **`SolutionDesign.md`**: System architecture, data model, API specifications
- **`project-structure.md`**: This file - project organization documentation
- **`aws-setup-guide.md`**: AWS CLI configuration, Cognito setup, JWT tokens
- **`deployment-guide.md`**: CI/CD via GitHub Actions, multi-environment deployment
- **`development-guide.md`**: Environment setup, deploy to dev, local testing, troubleshooting
- **`infrastructure-guide.md`**: Resource tagging, monitoring, cost estimation
- **`docs-index.md`**: Complete documentation index
- **`notification-framework-design.md`**: Notification framework architecture and contract
- **`notification-framework-mgmt-app-handoff.md`**: Backend delivery summary and mgmt-app integration expectations

### Testing (`tests/`)
- Unit and integration tests using pytest with moto for AWS mocking
- `conftest.py`: Shared fixtures (mock DynamoDB tables, environment variables)
- `fixtures/mock_data.py`: Test data matching the hybrid table data model
- Test configuration in `pytest.ini`

### Events (`events/`)
- Sample JSON payloads for testing Lambda functions locally with `sam local invoke`

### Infrastructure as Code
- **`template.yaml`**: AWS SAM template defining all AWS resources (Lambda functions, API Gateway HTTP API, Cognito User Pool + Groups, shared DynamoDB tables, S3 bucket, IAM roles). Cognito is auto-created by default, including the standard management groups (`ADMINISTRATOR`, `SUPER_USER`, `HOTEL_STAFF`, `GUEST`) and five predefined pit-stop groups (`PS_1_USER` to `PS_5_USER`). Tour-specific tables (TourRider, Ride, CheckIn, User, Notification, Artifacts, Event, EventOccurrence, EventActivityLogs, Hotel, RoomAllocation) are provisioned at runtime by `create_tour.py`.
- **`samconfig.toml`**: SAM CLI configuration for different environments (dev, test, prod)
- **`Makefile`**: Automation scripts for common tasks (build, deploy, test, logs, preflight check, OIDC setup)
- **`cloudformation/github-oidc.yaml`**: Bootstrap template for GitHub OIDC authentication (deployed once per AWS account)
- **`scripts/preflight-check.sh`**: Pre-deployment checks for AWS CLI, SAM CLI, Python, credentials, and template validity
- **`scripts/dev-test-setup.sh`**: Exports environment variables (API endpoint, JWT token, etc.) for dev API testing
- **`scripts/provision_tour.py`**: CLI tool for provisioning tours during deployment. Creates a Tour record and 11 tour-specific DynamoDB tables. This is the deployment-time equivalent of the `POST /v1/tours` API endpoint.
- **`scripts/cleanup_tour_tables.py`**: Deletes tour-specific DynamoDB tables (TourRider, Ride, CheckIn, User, Notification, Artifacts, Event, EventOccurrence, EventActivityLogs, Hotel, RoomAllocation) that are created at runtime and not managed by CloudFormation. Runs automatically as part of `make delete` and can also be used standalone.
- **`scripts/simulate/`**: Test data simulation utility. Uses YAML scenario configs to generate and load realistic test data (rider profiles, tour riders, rides, check-ins) into DynamoDB. See `scripts/simulate/README.md` for full documentation.

### CI/CD (`.github/workflows/`)
- **`ci-cd.yml`**: GitHub Actions workflow for manual-trigger testing and deployment
- Supports environment selection (dev/test/prod) via `workflow_dispatch` input
- Supports both OIDC (recommended) and static access key authentication

### Local Development Files (Not in Git)
- **`venv/` or `.venv/`**: Python virtual environment for local development
- **`.aws-sam/`**: SAM build artifacts and deployment packages
