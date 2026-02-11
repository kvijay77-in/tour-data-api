# Testing Documentation

This directory contains unit tests for the Tour Data API Lambda functions using proper mocking techniques.

## Testing Approach

We use **pytest** with **moto** for AWS service mocking. This approach keeps production code clean while allowing comprehensive testing without AWS connectivity.

### Key Principles

1. **Separation of Concerns**: Production code (`src/`) never contains test logic
2. **AWS Mocking**: Use moto to mock AWS services (DynamoDB, S3, etc.)
3. **No AWS Costs**: Tests run entirely in-memory, no real AWS resources used
4. **Fast Execution**: Tests complete in seconds, ideal for CI/CD

## Directory Structure

```
tests/
├── conftest.py                    # Shared pytest fixtures
├── test_validation.py             # Validation utility tests
├── test_lambda_functions.py       # Lambda function tests with moto
├── fixtures/
│   ├── __init__.py
│   └── mock_data.py               # Mock data for testing
└── README.md                      # This file
```

## Running Tests

### Run All Tests

```bash
# Activate virtual environment first
source venv/bin/activate

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=src --cov-report=html
```

### Run Specific Tests

```bash
# Run specific test file
pytest tests/test_lambda_functions.py -v

# Run specific test function
pytest tests/test_lambda_functions.py::test_get_active_tour_success -v

# Run tests matching a pattern
pytest -k "active_tour" -v
```

### Coverage Reports

```bash
# Generate HTML coverage report
pytest --cov=src --cov-report=html

# Open coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

## Writing Tests

### Example Test Structure

```python
import pytest
import boto3
from moto import mock_dynamodb

@pytest.fixture
def dynamodb_mock(aws_credentials, lambda_environment):
    """Create mock DynamoDB tables with test data"""
    with mock_dynamodb():
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        
        # Create table
        table = dynamodb.create_table(
            TableName='test-tour-table',
            KeySchema=[{'AttributeName': 'PK', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'PK', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST'
        )
        
        # Populate with test data
        table.put_item(Item={'PK': 'TOUR#001', 'tourName': 'Test Tour'})
        
        yield dynamodb

def test_example(dynamodb_mock):
    """Example test with mocked DynamoDB"""
    from get_active import lambda_handler
    
    event = {
        'version': '2.0',
        'routeKey': 'GET /v1/tours/active'
    }
    
    response = lambda_handler(event, None)
    assert response['statusCode'] == 200
```

### Using Fixtures

Fixtures are defined in `conftest.py` and available automatically:

- `aws_credentials` - Sets mock AWS credentials
- `dynamodb_client` - Provides mocked DynamoDB client
- `dynamodb_resource` - Provides mocked DynamoDB resource
- `lambda_environment` - Sets Lambda environment variables

## Testing Best Practices

### 1. Mock AWS Services, Not Business Logic

```python
# ✅ Good - Mocks AWS, tests your code
with mock_dynamodb():
    # Your Lambda function runs with mocked AWS
    response = lambda_handler(event, None)

# ❌ Bad - Mocks your business logic
with patch('my_module.business_function'):
    # You're not testing anything
    response = lambda_handler(event, None)
```

### 2. Keep Production Code Clean

```python
# ❌ Bad - Test logic in production code
def get_item(table_name):
    if os.environ.get('MOCK_MODE') == 'true':
        return mock_data[table_name]
    return boto3.resource('dynamodb').Table(table_name).get_item()

# ✅ Good - Production code stays clean
def get_item(table_name):
    return boto3.resource('dynamodb').Table(table_name).get_item()
```

### 3. Test Both Success and Failure Cases

```python
def test_success_case(dynamodb_mock):
    """Test when everything works"""
    response = lambda_handler(event, None)
    assert response['statusCode'] == 200

def test_not_found_case(dynamodb_mock):
    """Test when resource doesn't exist"""
    response = lambda_handler(event, None)
    assert response['statusCode'] == 404

def test_error_case(dynamodb_mock):
    """Test error handling"""
    # Simulate DynamoDB error
    response = lambda_handler(invalid_event, None)
    assert response['statusCode'] == 500
```

### 4. Use Descriptive Test Names

```python
# ✅ Good - Describes what's being tested
def test_get_active_tour_returns_active_tour_when_exists():
    pass

def test_get_active_tour_returns_404_when_no_active_tour():
    pass

# ❌ Bad - Vague names
def test_tour():
    pass

def test_case_1():
    pass
```

## Mock Data

Mock data fixtures are defined in `fixtures/mock_data.py`:

```python
from fixtures.mock_data import MOCK_TOURS, MOCK_RIDERS

def test_with_mock_data(dynamodb_mock):
    table = dynamodb_mock.Table('test-tour-table')
    for tour in MOCK_TOURS:
        table.put_item(Item=tour)
```

## Continuous Integration

Tests run automatically in GitHub Actions:

```yaml
# .github/workflows/ci-cd.yml
- name: Run Tests
  run: |
    pytest --cov=src --cov-report=xml
    
- name: Upload Coverage
  uses: codecov/codecov-action@v3
```

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [moto documentation](http://docs.getmoto.org/)
- [boto3 testing](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/testing.html)
