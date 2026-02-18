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
│   │   ├── checkins/
│   │   │   ├── __init__.py
│   │   │   ├── create_checkin.py      # POST /v1/tours/{tourId}/checkins
│   │   │   ├── get_dashboard_data.py  # GET /v1/tours/{tourId}/rides/{rideId}/dashboard
│   │   │   └── get_ride_checkins.py   # GET /v1/tours/{tourId}/rides/{rideId}/checkins
│   │   ├── riders/
│   │   │   ├── __init__.py
│   │   │   ├── get_rider_profile.py   # GET /v1/riders/profile/{profileId}
│   │   │   ├── get_tour_rider.py      # GET /v1/tours/{tourId}/riders/{riderId}
│   │   │   ├── get_tour_riders.py     # GET /v1/tours/{tourId}/riders
│   │   │   └── update_rider_profile.py # PUT /v1/riders/profile/{profileId}
│   │   ├── rides/
│   │   │   ├── __init__.py
│   │   │   ├── close_ride.py          # POST /v1/tours/{tourId}/rides/{rideId}/close
│   │   │   ├── create_ride.py         # POST /v1/tours/{tourId}/rides
│   │   │   ├── get_ride.py            # GET /v1/tours/{tourId}/rides/{rideId}
│   │   │   ├── get_todays_ride.py     # GET /v1/tours/{tourId}/rides/today
│   │   │   ├── list_rides.py          # GET /v1/tours/{tourId}/rides
│   │   │   └── update_ride.py         # PUT /v1/tours/{tourId}/rides/{rideId}
│   │   ├── tours/
│   │   │   ├── __init__.py
│   │   │   ├── archive_tour.py        # POST /v1/tours/{tourId}/archive
│   │   │   ├── create_tour.py         # POST /v1/tours
│   │   │   ├── get_active.py          # GET /v1/tours/active
│   │   │   ├── get_tour.py            # GET /v1/tours/{tourId}
│   │   │   └── list_tours.py          # GET /v1/tours
│   │   └── users/
│   │       ├── __init__.py
│   │       ├── get_current_user.py    # GET /v1/users/me
│   │       └── list_tour_users.py     # GET /v1/tours/{tourId}/users
│   └── layers/
│       └── common/                    # Shared utilities layer
│           ├── requirements.txt       # Layer dependencies
│           └── python/
│               ├── __init__.py
│               ├── dynamodb_utils.py  # DynamoDB operations (shared + tour-specific)
│               ├── logger.py          # Logging utilities
│               ├── models.py          # Data models and enums
│               ├── response.py        # API response utilities
│               └── validation.py      # Input validation
├── tests/                             # Unit and integration tests
│   ├── __init__.py
│   ├── conftest.py                    # Pytest fixtures and setup
│   ├── README.md                      # Testing documentation
│   ├── test_lambda_functions.py       # Lambda function tests
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
    └── preflight-check.sh            # Pre-deployment environment validation
```

**Key Structure Notes:**

### Source Code (`src/`)
- **`functions/`**: Contains all Lambda function handlers organized by feature domain (checkins, riders, rides, tours, users). Each domain has an `__init__.py` for package initialization.
- **`layers/common/`**: Shared utilities and dependencies used across all Lambda functions
  - `python/`: Python modules for models, validation, database operations, logging, and response formatting
  - `requirements.txt`: Dependencies for the common layer

### Documentation (`docs/`)
- **`Requirements.md`**: Detailed business requirements and use cases
- **`SolutionDesign.md`**: System architecture, data model, API specifications
- **`project-structure.md`**: This file - project organization documentation
- **`aws-setup-guide.md`**: AWS CLI configuration, Cognito setup, JWT tokens
- **`deployment-guide.md`**: CI/CD via GitHub Actions, multi-environment deployment
- **`development-guide.md`**: Environment setup, deploy to dev, local testing, troubleshooting
- **`infrastructure-guide.md`**: Resource tagging, monitoring, cost estimation
- **`docs-index.md`**: Complete documentation index

### Testing (`tests/`)
- Unit and integration tests using pytest with moto for AWS mocking
- `conftest.py`: Shared fixtures (mock DynamoDB tables, environment variables)
- `fixtures/mock_data.py`: Test data matching the hybrid table data model
- Test configuration in `pytest.ini`

### Events (`events/`)
- Sample JSON payloads for testing Lambda functions locally with `sam local invoke`

### Infrastructure as Code
- **`template.yaml`**: AWS SAM template defining all AWS resources (Lambda functions, API Gateway HTTP API, Cognito User Pool, shared DynamoDB tables, S3 bucket, IAM roles). Cognito is auto-created by default. Tour-specific tables are provisioned at runtime by `create_tour.py`.
- **`samconfig.toml`**: SAM CLI configuration for different environments (dev, test, prod)
- **`Makefile`**: Automation scripts for common tasks (build, deploy, test, logs, preflight check, OIDC setup)
- **`cloudformation/github-oidc.yaml`**: Bootstrap template for GitHub OIDC authentication (deployed once per AWS account)
- **`scripts/preflight-check.sh`**: Pre-deployment checks for AWS CLI, SAM CLI, Python, credentials, and template validity

### CI/CD (`.github/workflows/`)
- **`ci-cd.yml`**: GitHub Actions workflow for manual-trigger testing and deployment
- Supports environment selection (dev/test/prod) via `workflow_dispatch` input
- Supports both OIDC (recommended) and static access key authentication

### Local Development Files (Not in Git)
- **`venv/` or `.venv/`**: Python virtual environment for local development
- **`.aws-sam/`**: SAM build artifacts and deployment packages

