# Test suite
_Last updated: 2026-09-29_

The backend test suite uses pytest and moto to exercise Lambda handlers and shared modules with mocked AWS services. Tests do not require deployed AWS resources or AWS credentials.

## Run tests

From the repository root, after creating and activating the project virtual environment and installing `requirements-dev.txt` (see the [Development Guide](../docs/guides/development.md)):

```bash
source .venv/bin/activate
pytest tests/ -v
```

Or run the Make target:

```bash
make test
```

The GitHub Actions workflow runs the test suite with coverage reporting. To generate a local HTML coverage report:

```bash
pytest tests/ --cov=src --cov-report=html --cov-report=term
```

## Test organization

| Test file | Coverage |
|---|---|
| `test_lambda_functions.py` | Tour APIs, provisioning, and shared DynamoDB utilities |
| `test_validation.py` | Shared validation helpers |
| `test_rbac.py` | Permission resolution and handler authorization |
| `test_checkin_enhancements.py` | Check-in rules and stage restrictions |
| `test_rider_app_apis.py` | Rider-facing profile, registration, and tour APIs |
| `test_rider_exit_apis.py` | Rider exit and baggage custody APIs |
| `test_rider_profile_ownership.py` | Rider profile ownership checks |
| `test_rider_profile_definitions_version_api.py` | Profile definition version behavior |
| `test_profile_schema.py` | Configuration-driven profile schema validation |
| `test_admin_profile_config_api.py` | Administrator profile definition APIs |
| `test_profile_attribute_download_access.py` | Profile file download authorization |
| `test_config_api.py` | Shared configuration read API |
| `test_seed_app_config_profile.py` | Profile configuration seed behavior |
| `test_event_engine_apis.py` | Events, hotel, and tour-user APIs |
| `test_usermgmt_apis.py` | User management APIs |
| `test_hotel_upload_processor.py` | Hotel allocation upload processing and failure handling |
| `test_notification_framework.py` | Notification inbox, rules, devices, and delivery behavior |
| `test_artifacts_apis.py` | Artifact upload, delete, and manifest APIs |
| `test_tour_provisioning.py` | Runtime tour table provisioning |

Shared fixtures are in `conftest.py`; reusable test data is in `fixtures/mock_data.py`. AWS interactions in tests use moto's `mock_aws` context.

See the [Development Guide](../docs/guides/development.md) for environment setup, linting, formatting, and test commands.
