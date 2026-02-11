# Project Folder Structure

Following structure will be used in the project and any addition/restructure should be updated here. But first changes should be approved before it be applied.

```
tour-data-api/
├── .github/
│   └── workflows/
│       └── ci-cd.yml              # GitHub Actions CI/CD pipeline
├── docs/
│   ├── Requirements.md            # Detailed requirements
│   ├── SolutionDesign.md          # Architecture and design
│   └── project-structure.md       # Project structure documentation
├── src/
│   ├── functions/                 # Lambda function handlers
│   │   ├── checkins/
│   │   │   ├── create_checkin.py
│   │   │   ├── get_dashboard_data.py
│   │   │   └── get_ride_checkins.py
│   │   ├── riders/
│   │   │   ├── get_rider_profile.py
│   │   │   ├── update_rider_profile.py
│   │   │   └── get_tour_rider.py
│   │   ├── rides/
│   │   │   ├── get_todays_ride.py
│   │   │   ├── get_ride.py
│   │   │   ├── list_rides.py
│   │   │   ├── create_ride.py
│   │   │   ├── update_ride.py
│   │   │   └── close_ride.py
│   │   ├── tours/
│   │   │   ├── get_active.py
│   │   │   └── get_tour.py
│   │   └── users/
│   │       ├── get_current_user.py
│   │       └── list_tour_users.py
│   └── layers/
│       └── common/                # Shared utilities layer
│           ├── python/
│           │   ├── models.py      # Data models
│           │   ├── response.py    # Response utilities
│           │   ├── validation.py  # Input validation
│           │   ├── dynamodb_utils.py  # DynamoDB operations
│           │   └── logger.py      # Logging utilities
│           └── requirements.txt
├── tests/                         # Unit and integration tests
│   ├── test_validation.py
│   └── __init__.py
├── events/                        # Sample event payloads for testing
│   ├── get-active-tour.json
│   └── create-checkin.json
├── venv/                          # Virtual environment (local only, not in git)
├── .aws-sam/                      # SAM build artifacts (local only, not in git)
├── template.yaml                  # SAM CloudFormation template
├── samconfig.toml                 # SAM CLI configuration
├── Makefile                       # Build and deployment automation
├── requirements-dev.txt           # Development dependencies
├── pytest.ini                     # Test configuration
├── .gitignore                     # Git ignore file
└── README.md                      # Project documentation
```

**Key Structure Notes:**

### Source Code (`src/`)
- **`functions/`**: Contains all Lambda function handlers organized by feature domain (checkins, riders, rides, tours, users)
- **`layers/common/`**: Shared utilities and dependencies used across all Lambda functions
  - `python/`: Python modules for models, validation, database operations, logging, and response formatting
  - `requirements.txt`: Dependencies for the common layer

### Documentation (`docs/`)
- **`Requirements.md`**: Detailed business requirements and use cases
- **`SolutionDesign.md`**: System architecture, data model, API specifications
- **`project-structure.md`**: This file - project organization documentation

### Testing (`tests/`)
- Unit and integration tests
- Test configuration in `pytest.ini`
- Should mirror the structure of `src/` for easy navigation

### Events (`events/`)
- Sample JSON payloads for testing Lambda functions locally
- Used with `sam local invoke` command

### Infrastructure as Code
- **`template.yaml`**: AWS SAM template defining all AWS resources (Lambda, API Gateway, DynamoDB, IAM roles, etc.)
- **`samconfig.toml`**: SAM CLI configuration for different environments (dev, test, prod)
- **`Makefile`**: Automation scripts for common tasks (build, deploy, test, logs)

### CI/CD (`.github/workflows/`)
- **`ci-cd.yml`**: GitHub Actions workflow for automated testing and deployment
- Handles linting, testing, building, and multi-environment deployment

### Local Development Files (Not in Git)
- **`venv/`**: Python virtual environment for local development
- **`.aws-sam/`**: SAM build artifacts and deployment packages

### Important Files
- **`requirements-dev.txt`**: Development dependencies (pytest, moto, black, pylint, boto3)
- **`.gitignore`**: Specifies files to exclude from version control (venv, .aws-sam, __pycache__, etc.)

