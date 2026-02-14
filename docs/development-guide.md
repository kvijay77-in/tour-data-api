# Development Guide

[← Back to README](../README.md)

This guide covers local development setup, testing, code quality tools, troubleshooting, and useful development workflows.

## Table of Contents
- [Local Development](#local-development)
- [Running Tests](#running-tests)
- [Code Quality](#code-quality)
- [Useful Commands](#useful-commands)
- [Troubleshooting](#troubleshooting)
- [Support](#support)

---

## Local Development

> **Remember**: Activate your virtual environment before running any commands:
> ```bash
> source venv/bin/activate
> ```

### Understanding Local Development Data

**Important**: By default, `sam local start-api` connects to your **real AWS DynamoDB tables** - not local data.

When you run the local API:
- Lambda functions execute on your local machine (using Docker)
- **Data operations go to actual AWS resources** (DynamoDB tables, S3 buckets)
- Uses your AWS credentials from `aws configure`
- **Any data changes affect your AWS environment** (typically dev environment)

**Pros**: Test with realistic data, proper AWS service integration  
**Cons**: Requires AWS credentials, changes affect real environment, incurs minimal AWS costs

### Local Development Options

#### Option 1: Use AWS Resources (Default - Recommended)

```bash
# Local API connects to your AWS DynamoDB tables
sam local start-api

# API available at http://localhost:3000
# All data operations go to your AWS account
```

**Prerequisites**:
- AWS credentials configured (`aws configure`)
- DynamoDB tables already deployed to AWS (`sam deploy`)
- Proper IAM permissions for DynamoDB access

**Best for**: Integration testing, testing with realistic data, full API endpoint testing

**Example requests**:
```bash
# Test active tour endpoint
curl http://localhost:3000/v1/tours/active

# Create check-in (requires valid tour/rider data in DynamoDB)
curl -X POST http://localhost:3000/v1/checkins \
  -H "Content-Type: application/json" \
  -d '{"tourId": "TOUR#123", "riderId": "RIDER#456", "rideId": "RIDE#789", "checkInType": "NORMAL"}'
```

#### Testing Individual Lambda Functions

You can also test individual Lambda functions locally with sample events:

```bash
# Test single function (connects to AWS DynamoDB)
sam local invoke GetActiveTourFunction -e events/get-active-tour.json

# Test check-in function
sam local invoke CreateCheckInFunction -e events/create-checkin.json

# Use Make command
make invoke FUNCTION=GetActiveTourFunction EVENT=events/get-active-tour.json
```

> **Note**: These commands run Lambda functions locally but still connect to real AWS resources. For testing without AWS, see Option 2 below.

#### Option 2: Unit Testing with Mocked AWS Services

Run unit tests with pytest and moto (AWS service mocking):

```bash
# Run all unit tests with mocked AWS services
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_lambda_functions.py -v

# Run specific test function
pytest tests/test_lambda_functions.py::test_get_active_tour_success -v
```

**How It Works:**
- Uses **moto** library to mock AWS DynamoDB (no real AWS resources)
- Tests run with in-memory mock databases
- Production code (`dynamodb_utils.py`) remains clean - no test logic
- Standard Python testing approach using pytest fixtures

**Best for**: Unit testing, CI/CD pipelines, testing business logic without AWS, offline development

**Pros**: No AWS credentials needed, fast execution, no AWS costs, proper separation of concerns  
**Cons**: Mocks may not catch all AWS-specific edge cases

See [tests/test_lambda_functions.py](../tests/test_lambda_functions.py) for examples.

> **Note**: For local API testing with real AWS resources, use Option 1 above. For unit testing without AWS, use pytest with moto.

---

## Running Tests

> **Important**: Always ensure your virtual environment is activated before running tests:
> ```bash
> source venv/bin/activate  # On Linux/Mac
> # or
> venv\Scripts\activate     # On Windows
> ```

### Run All Tests

```bash
# Run all tests
pytest

# or use Make
make test
```

### Run Tests with Coverage

```bash
# Run with coverage report
pytest --cov=src --cov-report=html

# View coverage report
# Open htmlcov/index.html in your browser
```

### Run Specific Tests

```bash
# Run specific test file
pytest tests/test_validation.py

# Run specific test function
pytest tests/test_validation.py::test_validate_checkin_success -v

# Run tests matching a pattern
pytest -k "checkin" -v
```

### Test Verbosity

```bash
# Verbose output
pytest -v

# Extra verbose (show print statements)
pytest -vv

# Show local variables on failure
pytest -l
```

---

## Code Quality

### Linting

```bash
# Run linter on common utilities
pylint src/layers/common/python/*.py

# Run linter on all source code
pylint src/

# or use Make
make lint
```

### Code Formatting

```bash
# Format all code with black
black src/

# Check formatting without making changes
black --check src/

# or use Make
make format
```

### Pre-commit Checks

Before committing code, run:

```bash
# Lint and format
make lint
make format

# Run tests
make test
```

---

## Useful Commands

### Build and Deploy

```bash
# Build the application
make build

# Build and deploy to dev environment
make deploy

# Deploy to test environment
make deploy-test

# Deploy to production (with confirmation)
make deploy-prod

# Sync code changes (build + deploy)
make sync
```

### Monitoring and Logs

```bash
# View CloudWatch logs for a function
make logs FUNCTION=GetActiveTourFunction

# Tail logs in real-time
make logs-tail FUNCTION=CreateCheckinFunction

# Example with specific function
make logs FUNCTION=GetRideCheckinsFunction
```

### Cleanup and Validation

```bash
# Clean build artifacts
make clean

# Validate SAM template
make validate
```

### Local Testing

```bash
# Start local API (connects to AWS resources)
sam local start-api

# Invoke specific function locally
sam local invoke FunctionName -e events/event-file.json

# Using Make
make invoke FUNCTION=GetActiveTourFunction EVENT=events/get-active-tour.json
```

---

## Troubleshooting

### SAM Build Fails

**Issue**: Build fails with dependency errors or Python version mismatch

**Solution**:
```bash
# Clear cache and rebuild
make clean
make build

# Verify Python version (requires 3.12+)
python --version

# Ensure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements-dev.txt
```

### Deployment Fails

**Issue**: Deployment fails with CloudFormation errors

**Solution**:
```bash
# Validate template syntax
make validate

# Check AWS credentials
aws sts get-caller-identity

# View CloudFormation events for details
aws cloudformation describe-stack-events --stack-name tour-data-api

# Check specific stack status
aws cloudformation describe-stacks --stack-name tour-data-api
```

**Common Issues**:
- **Insufficient IAM permissions**: Ensure your AWS credentials have necessary permissions
- **S3 bucket conflicts**: SAM creates deployment buckets; name conflicts can cause failures
- **Parameter errors**: Check `samconfig.toml` for correct parameter values
- **Resource limits**: Verify you haven't hit AWS service limits

### Lambda Function Errors

**Issue**: Lambda function returns errors or unexpected results

**Solution**:
```bash
# View recent logs
make logs FUNCTION=YourFunctionName

# Tail logs in real-time
make logs-tail FUNCTION=YourFunctionName

# Test locally with AWS resources
sam local invoke YourFunctionName -e events/your-event.json

# Or run unit tests with mocked AWS services
pytest tests/test_lambda_functions.py -v
```

**Debugging Tips**:
- Check CloudWatch Logs for detailed error messages
- Verify function has correct IAM permissions for DynamoDB/S3 access
- Test with sample events in `events/` directory
- Use `print()` statements in code (will appear in CloudWatch Logs)
- Verify request payload matches expected schema

### DynamoDB Issues

**Issue**: DynamoDB operations fail or return unexpected results

**Solution**:
```bash
# List all tables
aws dynamodb list-tables

# Describe table structure
aws dynamodb describe-table --table-name RiderProfile

# Scan table (dev only! Use carefully)
aws dynamodb scan --table-name RiderProfile --limit 10

# Get specific item
aws dynamodb get-item \
  --table-name RiderProfile \
  --key '{"PK": {"S": "RIDER#123"}, "SK": {"S": "PROFILE"}}'
```

**Common Issues**:
- **Table not found**: Ensure tables are deployed (`sam deploy`)
- **Access denied**: Check Lambda function's IAM execution role has DynamoDB permissions
- **Validation errors**: Verify data matches table schema (PK, SK, GSIs)
- **Throttling**: Consider switching to on-demand billing or increasing provisioned capacity

### API Gateway Issues

**Issue**: API returns 403 Forbidden or 401 Unauthorized

**Solution**:
- Verify JWT token is valid and not expired
- Check Cognito User Pool is configured correctly
- Ensure `Authorization: Bearer <token>` header is present
- Verify API Gateway authorizer is properly configured

**Issue**: API returns 502 Bad Gateway

**Solution**:
- Check Lambda function logs for errors
- Verify Lambda function returns proper response format
- Ensure Lambda function timeout is sufficient (default 30s)

### Local Development Issues

**Issue**: `sam local start-api` fails to start

**Solution**:
```bash
# Ensure Docker is running
docker ps

# Build application first
sam build

# Check for port conflicts (default: 3000)
lsof -i :3000

# Use different port if needed
sam local start-api --port 3001
```

**Issue**: Local API can't connect to AWS resources

**Solution**:
```bash
# Verify AWS credentials
aws sts get-caller-identity

# Check IAM permissions
aws iam get-user

# Ensure DynamoDB tables exist
aws dynamodb list-tables
```

---

## Support

For issues and questions:

1. **Check Documentation**: Review documentation in `docs/` folder
2. **CloudWatch Logs**: Check CloudWatch logs for detailed error messages
3. **SAM Template**: Review template configuration in `template.yaml`
4. **AWS Console**: Use AWS Console to inspect resources directly
5. **GitHub Issues**: Create an issue in the repository with:
   - Error messages and logs
   - Steps to reproduce
   - Environment details (OS, Python version, SAM version)

### Useful Resources

- [AWS SAM Troubleshooting Guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-cli-troubleshooting.html)
- [AWS Lambda Troubleshooting](https://docs.aws.amazon.com/lambda/latest/dg/lambda-troubleshooting.html)
- [DynamoDB Troubleshooting](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Programming.Errors.html)
- [Python Pytest Documentation](https://docs.pytest.org/)
- [Moto Documentation](https://docs.getmoto.org/)

---

[← Back to README](../README.md)
