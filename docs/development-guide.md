# Development Guide

[← Back to README](../README.md)

Complete guide for setting up your development environment, deploying to the dev AWS environment, local testing, and daily development workflows.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Initial Setup](#initial-setup)
- [Deploy to Dev Environment](#deploy-to-dev-environment)
- [Unit Testing](#unit-testing)
- [Code Quality](#code-quality)
- [Useful Commands](#useful-commands)
- [Troubleshooting](#troubleshooting)
- [Support](#support)
- [Advanced: Local Lambda Debugging](#advanced-local-lambda-debugging)

---

## Prerequisites

| Tool | Version | Purpose | Install Guide |
|------|---------|---------|---------------|
| **Python** | 3.11+ | Runtime for Lambda functions | [python.org](https://www.python.org/downloads/) |
| **AWS CLI** | v2 | Interact with AWS services | [Install guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) |
| **SAM CLI** | Latest | Build and deploy SAM applications | [Install guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) |
| **Git** | Any | Version control | [git-scm.com](https://git-scm.com/) |
| **Make** | Any | Optional — shortcut commands | Pre-installed on Linux/Mac |

---

## Initial Setup

### 1. Clone the Repository

```bash
git clone <repository-url>
cd tour-data-api
```

### 2. Set Up Virtual Environment

```bash
python3.14 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

> **Note**: Python 3.11 to 3.14 are supported. 3.14 is the default.

### 3. Install Development Dependencies

```bash
pip install -r requirements-dev.txt
```

This installs local development tools (pytest, moto, pylint, black, boto3). These are **not** deployed to AWS — they are for local development only.

### 4. Run Preflight Check

Verify all tools and configuration are in place:

```bash
make check-config
```

This checks for AWS CLI, SAM CLI, Python, and valid AWS credentials. Fix any reported issues before continuing.

### 5. Configure AWS Credentials

Your terminal needs permission to access your AWS account. Verify:

```bash
aws sts get-caller-identity
```

If you see your account ID, you're all set. If you get an error, follow the [AWS Setup Guide](aws-setup-guide.md) for configuration options (SSO, STS assume role, or access keys).

---

## Deploy to Dev Environment

Deploy the application to your AWS dev environment. This creates all AWS resources (API Gateway, Lambda functions, DynamoDB tables, Cognito User Pool, S3 bucket).

### Build

```bash
sam build
# or
make build
```

### Deploy

```bash
sam deploy
# or
make deploy
```

SAM shows a summary of resources to be created/updated and asks for confirmation. Type `y` to proceed.

> **First deployment** creates everything from scratch and takes slightly longer (~5-10 min). Subsequent deployments only update what changed.

### Verify Deployment

After deployment completes, note the outputs:

- **API URL**: Your API endpoint (e.g., `https://<api-id>.execute-api.<region>.amazonaws.com/dev/`)
- **Cognito User Pool ID**: Auto-created user authentication pool
- **Cognito App Client ID**: Client ID for your applications

Retrieve the API URL anytime:

```bash
aws cloudformation describe-stacks \
  --stack-name tour-data-api \
  --query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" \
  --output text
```

Test the deployment:

```bash
curl <api-url>/v1/tours
```

> **Note**: Most endpoints require JWT authentication. An "Unauthorized" response confirms the API is running correctly. See [AWS Setup Guide → Get JWT Token for Testing](aws-setup-guide.md#3-get-jwt-token-for-testing) for creating test users and generating tokens.

---

## Unit Testing

Unit tests use **pytest** with **moto** (AWS service mocking). No AWS credentials or deployed resources needed.

### How It Works

- **moto** creates in-memory mock DynamoDB tables
- Tests run entirely locally — no AWS costs
- Production code remains clean (no test logic mixed in)
- Fixtures in `tests/conftest.py` set up the mock environment
- Test data in `tests/fixtures/mock_data.py`

See [tests/test_lambda_functions.py](../tests/test_lambda_functions.py) for examples.

### Run All Tests

```bash
pytest
# or
make test
```

### Test Coverage

```bash
pytest --cov=src --cov-report=html
# or
make test-coverage

# Open htmlcov/index.html in your browser to view the report
```

### Run Specific Tests

```bash
# Specific test file
pytest tests/test_validation.py

# Specific test function
pytest tests/test_validation.py::test_validate_checkin_success -v

# Tests matching a pattern
pytest -k "checkin" -v
```

### Test Verbosity

```bash
pytest -v      # Verbose output
pytest -vv     # Extra verbose (show print statements)
pytest -l      # Show local variables on failure
```

---

## Code Quality

### Linting

```bash
pylint src/layers/common/*.py           # Common utilities
pylint src/                             # All source code
make lint                               # Using Make
```

### Code Formatting

```bash
black src/                  # Format all code
black --check src/          # Check without changing
make format                 # Using Make
```

### Before Committing

```bash
make lint
make format
make test
```

---

## Useful Commands

| Command | Description |
|---------|-------------|
| `make build` | Build the SAM application |
| `make deploy` | Build and deploy to dev |
| `make validate` | Validate SAM template |
| `make test` | Run all unit tests |
| `make test-coverage` | Run tests with coverage report |
| `make lint` | Lint Python code |
| `make format` | Format code with Black |
| `make logs FUNCTION=X` | View CloudWatch logs |
| `make logs-tail FUNCTION=X` | Tail logs in real-time |
| `make sync` | Sync code changes (fast iteration) |
| `make clean` | Clean build artifacts |
| `make delete` | Delete CloudFormation stack |
| `make check-config` | Run preflight checks |

> **Note**: For deploying to test or prod environments, see the [Deployment Guide](deployment-guide.md).

---

## Troubleshooting

### SAM Build Fails

```bash
# Clear cache and rebuild
make clean && make build

# Verify Python version (3.11+ required)
python --version

# Ensure virtual environment is activated
source .venv/bin/activate

# Reinstall dependencies
pip install -r requirements-dev.txt
```

### Deployment Fails

```bash
# Validate template syntax
make validate

# Check AWS credentials
aws sts get-caller-identity

# View CloudFormation events for details
aws cloudformation describe-stack-events --stack-name tour-data-api

# Check stack status
aws cloudformation describe-stacks --stack-name tour-data-api
```

**Common causes**:
- **Insufficient IAM permissions**: Ensure your AWS user has rights to create Lambda, DynamoDB, API Gateway, S3, Cognito, and IAM roles
- **S3 bucket conflicts**: SAM creates deployment buckets; name conflicts can cause failures
- **Parameter errors**: Check `samconfig.toml` for correct values
- **Resource limits**: Verify you haven't hit AWS service limits

### Lambda Function Errors

```bash
# View recent logs
make logs FUNCTION=YourFunctionName

# Tail logs in real-time
make logs-tail FUNCTION=YourFunctionName

# Test locally
sam local invoke YourFunctionName -e events/your-event.json

# Run unit tests
pytest tests/test_lambda_functions.py -v
```

**Debugging tips**:
- Check CloudWatch Logs for detailed error messages
- Verify function has correct IAM permissions for DynamoDB/S3 access
- Test with sample events in `events/` directory
- Use `print()` statements (output appears in CloudWatch Logs)
- Verify request payload matches expected schema

### DynamoDB Issues

```bash
# List all tables (shared + tour-specific)
aws dynamodb list-tables

# Describe a table
aws dynamodb describe-table --table-name tour-data-api-RiderProfile

# Scan a table (dev only, use carefully)
aws dynamodb scan --table-name tour-data-api-RiderProfile --limit 10

# Get a specific item
aws dynamodb get-item \
  --table-name tour-data-api-RiderProfile \
  --key '{"PK": {"S": "PROFILE#abc-123-uuid"}}'

# Scan a tour-specific table
aws dynamodb scan --table-name tour-data-api-Ride-India-Coast-2026 --limit 10
```

**Common causes**:
- **Table not found**: Shared tables require `sam deploy`; tour-specific tables require creating a tour via `POST /v1/tours`
- **Access denied**: Check Lambda execution role has DynamoDB permissions
- **Validation errors**: Verify data matches table schema (PK, GSIs)
- **Throttling**: On-demand billing is the default; check if provisioned capacity was mistakenly set

### API Gateway Issues

**403 Forbidden / 401 Unauthorized**:
- Verify JWT token is valid and not expired
- Check `Authorization: Bearer <token>` header is present
- Verify Cognito User Pool is configured correctly

**502 Bad Gateway**:
- Check Lambda function logs for errors
- Verify function returns proper response format
- Ensure Lambda timeout is sufficient (default 30s)

---

## Support

1. **Check documentation** in `docs/` folder
2. **CloudWatch Logs** for detailed error messages
3. **SAM template** — review `template.yaml` configuration
4. **AWS Console** — inspect resources directly
5. **GitHub Issues** — create an issue with:
   - Error messages and logs
   - Steps to reproduce
   - Environment details (OS, Python version, SAM version)

### Useful Resources

- [AWS SAM Troubleshooting](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-cli-troubleshooting.html)
- [AWS Lambda Troubleshooting](https://docs.aws.amazon.com/lambda/latest/dg/lambda-troubleshooting.html)
- [DynamoDB Troubleshooting](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Programming.Errors.html)
- [Pytest Documentation](https://docs.pytest.org/)
- [Moto Documentation](https://docs.getmoto.org/)

---

## Advanced: Local Lambda Debugging

> **Optional.** This section is for developers who want to run Lambda functions on their local machine. It requires [Docker](https://www.docker.com/get-started). For most workflows, unit tests (pytest + moto) and the deployed dev API are sufficient.

### Local API with AWS Resources

`sam local start-api` runs Lambda functions locally (via Docker) but connects to **real AWS resources** (DynamoDB, S3). Data changes affect your dev environment.

**Requires**: Docker installed and running, AWS credentials configured, dev environment deployed.

```bash
sam local start-api
# or
make local-api

# API available at http://localhost:3000
```

Example requests:

```bash
curl http://localhost:3000/v1/tours/active
curl http://localhost:3000/v1/tours/India-Coast-2026/rides
```

### Testing Individual Lambda Functions

```bash
sam local invoke GetActiveTourFunction -e events/get-active-tour.json

# Or with Make
make invoke FUNCTION=GetActiveTourFunction EVENT=events/get-active-tour.json
```

### Troubleshooting Local API

**`sam local start-api` fails to start**:

```bash
# Ensure Docker is running
docker ps

# Build first
sam build

# Check for port conflicts
lsof -i :3000

# Use a different port
sam local start-api --port 3001
```

**Local API can't connect to AWS**:

```bash
aws sts get-caller-identity
aws dynamodb list-tables
```

---

[← Back to README](../README.md)
