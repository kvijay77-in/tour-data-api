# Deployment Guide

[← Back to README](../README.md)

This guide covers CI/CD pipeline configuration, GitHub Actions setup, multi-environment deployment, and AWS resources inventory.

## Table of Contents
- [CI/CD Pipeline](#cicd-pipeline)
- [Setting up GitHub Actions](#setting-up-github-actions)
- [Workflow File](#workflow-file)
- [AWS Resources Created by Deployment](#aws-resources-created-by-deployment)
- [Environments](#environments)

---

## CI/CD Pipeline

The project includes a GitHub Actions workflow for continuous integration and deployment.

> **Note**: The pipeline is configured for **manual triggering only**. It will not run automatically on code commits.

### How to Trigger the Pipeline

1. Go to your GitHub repository → **Actions** tab
2. Select the **CI/CD Pipeline** workflow from the left sidebar
3. Click **Run workflow** button
4. Select the target environment (dev, test, or prod)
5. Click **Run workflow** to start the pipeline

### Pipeline Stages

When manually triggered, the pipeline executes these stages:

#### 1. Test Stage

- Runs linters (pylint, black)
- Executes unit tests with coverage
- Uploads coverage reports to Codecov

**What it does**:
```bash
# Install dependencies
pip install -r requirements-dev.txt

# Run linter
pylint src/layers/common/python/*.py

# Check code formatting
black --check src/

# Run tests with coverage
pytest --cov=src --cov-report=xml
```

#### 2. Build Stage

- Validates SAM template
- Builds application artifacts

**What it does**:
```bash
# Validate template syntax
sam validate

# Build application
sam build
```

#### 3. Deploy Stage

Deploys to the chosen environment (dev, test, or prod):
- Provisions/updates all AWS resources
- Applies resource tags for cost tracking
- Outputs API endpoint URL

**What it does**:
```bash
# Deploy to selected environment
sam deploy \
  --config-env $ENVIRONMENT \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset
```

---

## Setting up GitHub Actions

To enable the CI/CD pipeline, you need to configure secrets in your GitHub repository.

### Required Secrets

Add these secrets to your GitHub repository (Settings → Secrets and variables → Actions):

#### For Dev/Test Environments

- `AWS_ACCESS_KEY_ID` - AWS access key with deployment permissions
- `AWS_SECRET_ACCESS_KEY` - AWS secret key

#### For Production Environment

- `AWS_ACCESS_KEY_ID_PROD` - AWS access key for production account
- `AWS_SECRET_ACCESS_KEY_PROD` - AWS secret key for production

> **Best Practice**: Use separate AWS accounts for production to isolate environments and improve security.

### Create IAM User for GitHub Actions

Create a dedicated IAM user with the necessary permissions for deployment:

```bash
# Create deployment user
aws iam create-user --user-name github-actions-deployer
```

#### Attach Required Policies

SAM deployment requires multiple permissions. Attach these managed policies:

```bash
# CloudFormation permissions (create/update stacks)
aws iam attach-user-policy --user-name github-actions-deployer \
  --policy-arn arn:aws:iam::aws:policy/AWSCloudFormationFullAccess

# IAM permissions (create Lambda execution roles)
aws iam attach-user-policy --user-name github-actions-deployer \
  --policy-arn arn:aws:iam::aws:policy/IAMFullAccess

# S3 permissions (deployment artifacts)
aws iam attach-user-policy --user-name github-actions-deployer \
  --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess

# Lambda permissions (create/update functions)
aws iam attach-user-policy --user-name github-actions-deployer \
  --policy-arn arn:aws:iam::aws:policy/AWSLambda_FullAccess

# API Gateway permissions (create/update APIs)
aws iam attach-user-policy --user-name github-actions-deployer \
  --policy-arn arn:aws:iam::aws:policy/AmazonAPIGatewayAdministrator

# DynamoDB permissions (create/update tables)
aws iam attach-user-policy --user-name github-actions-deployer \
  --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess
```

#### Create Access Keys

```bash
# Create access keys for the user
aws iam create-access-key --user-name github-actions-deployer
```

Save the `AccessKeyId` and `SecretAccessKey` from the output. Add these to your GitHub secrets.

### Alternative: Create Custom Policy (Least Privilege)

For better security, create a custom policy with only the required permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "cloudformation:*",
        "s3:*",
        "lambda:*",
        "apigateway:*",
        "dynamodb:*",
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:GetRole",
        "iam:PassRole",
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy",
        "iam:PutRolePolicy",
        "iam:DeleteRolePolicy",
        "logs:CreateLogGroup",
        "logs:DeleteLogGroup",
        "logs:PutRetentionPolicy"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## Workflow File

The CI/CD workflow is defined in `.github/workflows/ci-cd.yml`.

### Key Features

- **Manual Trigger**: Uses `workflow_dispatch` for manual execution
- **Environment Selection**: Choose target environment (dev/test/prod) when triggering — the selected environment determines which deploy job runs
- **Multi-Stage Pipeline**: Test → Build → Deploy (to selected environment)
- **Environment-Specific Credentials**: Uses different AWS credentials for prod
- **Coverage Reporting**: Uploads test coverage to Codecov

### Workflow Structure

```yaml
name: CI/CD Pipeline

on:
  workflow_dispatch:
    inputs:
      environment:
        description: 'Environment to deploy to'
        required: true
        default: 'dev'
        type: choice
        options:
          - dev
          - test
          - prod

jobs:
  test:
    # Run tests and linting
  
  build:
    # Build application
  
  deploy:
    # Deploy to selected environment
```

For the complete workflow configuration, see [.github/workflows/ci-cd.yml](../.github/workflows/ci-cd.yml).

---

## AWS Resources Created by Deployment

When the CI/CD pipeline (or `sam deploy`) executes, the following AWS resources are automatically created/updated:

### Compute & API

#### Lambda Functions (20)

**Tours:**
- `GetActiveTourFunction` - Get currently active tour
- `GetTourFunction` - Get specific tour details
- `ListToursFunction` - List all tours with optional status filter
- `CreateTourFunction` - Create and provision a new tour (creates tour-specific tables)
- `ArchiveTourFunction` - Archive a completed tour (optionally export data, delete tour tables)

**Riders:**
- `GetRiderProfileFunction` - Get rider profile by profile ID
- `UpdateRiderProfileFunction` - Update rider profile
- `GetTourRidersFunction` - Get all riders for a tour with profile data
- `GetTourRiderByIdFunction` - Get tour rider enrollment details

**Rides:**
- `GetTodaysRideFunction` - Get today's ride
- `GetRideFunction` - Get specific ride details
- `ListRidesFunction` - List all rides for a tour
- `CreateRideFunction` - Create a new ride
- `UpdateRideFunction` - Update ride details
- `CloseRideFunction` - Close a ride

**Check-ins:**
- `CreateCheckInFunction` - Create check-in record
- `GetRideCheckInsFunction` - Get check-ins for a ride
- `GetDashboardDataFunction` - Get dashboard statistics

**Users:**
- `GetCurrentUserFunction` - Get current authenticated user
- `ListTourUsersFunction` - List users with tour access

#### Lambda Layer
- **CommonLayer**: Shared utilities and dependencies used across all functions

#### API Gateway
- **HTTP API**: RESTful API with 20 endpoints under `/v1/` prefix
- **20 Lambda Permissions**: API Gateway invoke permissions for each function
- **JWT Authorizer**: Cognito-based JWT authentication (conditional, enabled when CognitoUserPoolArn is provided)
- **Routes**: All API routes defined in template.yaml

### Data Storage

#### DynamoDB Tables (Hybrid Strategy)

The project uses a **hybrid table strategy**: shared tables are SAM-managed, while tour-specific tables are provisioned at runtime per tour.

**Shared Tables (SAM-managed, always present):**

All tables use **On-demand billing mode** for cost efficiency:

- **RiderProfile** - Rider master data (persists across tours)
  - GSI: EmailIndex (for email lookups)
  
- **Tour** - Tour information and lifecycle status
  - GSI: StatusIndex (for status-based queries)

**Tour-Specific Tables (runtime-provisioned per tour):**

Created by `CreateTourFunction` when a tour is provisioned, deleted by `ArchiveTourFunction` when archived:

- **TourRider-{tourId}** - Tour enrollment mapping
  - Links riders to a specific tour
  
- **Ride-{tourId}** - Daily ride details
  - GSI: DateIndex (for date-based queries), StatusIndex (for status filtering)
  
- **CheckIn-{tourId}** - Check-in records
  - GSI: RideIndex (for ride-based queries)
  
- **User-{tourId}** - Admin/staff user accounts for a tour

#### S3 Bucket
- **Rider Photo Storage**: Stores rider profile photos
  - Lifecycle policies for cost optimization
  - Versioning enabled for data protection

### Security & Permissions

#### IAM Roles (20)

One execution role per Lambda function following least-privilege principle:

**Role Responsibilities:**
- Define AWS resource access (DynamoDB, S3, CloudWatch)
- Automatically assumed by Lambda during execution
- **Transparent to consumer applications** - consumers only handle JWT authentication

**Example Roles:**
- `CreateCheckInFunctionRole` - Can write to tour-specific CheckIn table
- `GetRideCheckInsFunctionRole` - Read-only access to tour-specific CheckIn and Ride tables
- `UpdateRiderProfileFunctionRole` - Can update shared RiderProfile table
- `CreateTourFunctionRole` - Can create DynamoDB tables, write to shared Tour table
- `ArchiveTourFunctionRole` - Can delete DynamoDB tables, write to S3 for data export

> **Important**: Consumer applications don't interact with these IAM roles. Apps authenticate users via Cognito, receive JWT tokens, and include tokens in API requests. API Gateway validates tokens and invokes Lambda functions, which then use their execution roles to access AWS resources.

#### IAM Policies

- Least-privilege policies attached to each execution role
- Policies define specific permissions (GetItem, PutItem, Query, etc.)

#### API Gateway Authorizer

- JWT authorizer connected to Cognito
- Validates JWT tokens from consumer applications
- Rejects requests with invalid/expired tokens

### Monitoring & Logging

#### CloudWatch Log Groups (20)

- One log group per Lambda function
- Retention policies configured (default: 7 days)
- Contains execution logs, errors, and custom logging

#### CloudWatch Alarms (Optional)

Can be added for monitoring:
- Lambda errors and throttles
- API Gateway 4xx/5xx errors
- DynamoDB throttling events

### Networking (Optional)

If VPC configuration is enabled:
- **VPC Integration**: Lambda functions with VPC access
- **Security Groups**: Control inbound/outbound traffic
- **Subnets**: Private subnets for Lambda functions

### CloudFormation

#### CloudFormation Stack

- **Stack Name**: `tour-data-api` (or custom name from samconfig.toml)
- **Stack Status**: Tracks deployment state
- **Change Sets**: Previews changes before deployment

#### SAM Deployment Bucket

- S3 bucket for storing deployment artifacts
- Created automatically by SAM CLI
- Named: `aws-sam-cli-managed-<region>-<hash>`

### Resource Summary

**Total SAM-Managed Resources**: ~55+ AWS resources (plus additional tour-specific tables created at runtime)

| Resource Type | Count | Purpose |
|---------------|-------|---------|
| Lambda Functions | 20 | Business logic and API handlers |
| Lambda Layers | 1 | Shared code and dependencies |
| DynamoDB Tables (shared) | 2 | Persistent data (RiderProfile, Tour) |
| DynamoDB Tables (per tour) | 4 per tour | Tour-scoped data (TourRider, Ride, CheckIn, User) |
| S3 Buckets | 1 | Photo storage + archive exports |
| IAM Roles | 20 | Lambda execution permissions |
| API Gateway APIs | 1 | HTTP API endpoints |
| CloudWatch Log Groups | 20 | Function logs |
| Lambda Permissions | 20 | API Gateway invoke permissions |

> **Note**: Tour-specific DynamoDB tables are provisioned at runtime by `CreateTourFunction` and are not included in the SAM template. The exact total depends on the number of active tours. All resources are tagged with project identifiers for cost tracking and management.

---

## Environments

The project supports three deployment environments with isolated resources.

### Environment Types

- **dev** (default): Development environment
- **test**: Testing/staging environment
- **prod**: Production environment

### Environment Configuration

Environments are configured in [samconfig.toml](../samconfig.toml).

**Example configuration:**

```toml
# Development environment (default)
[default.deploy.parameters]
stack_name = "tour-data-api"
capabilities = "CAPABILITY_IAM"
confirm_changeset = true
resolve_s3 = true
parameter_overrides = "Environment=dev"

# Test environment
[test.deploy.parameters]
stack_name = "tour-data-api-test"
capabilities = "CAPABILITY_IAM"
confirm_changeset = true
resolve_s3 = true
parameter_overrides = "Environment=test"

# Production environment
[prod.deploy.parameters]
stack_name = "tour-data-api-prod"
capabilities = "CAPABILITY_IAM"
confirm_changeset = false
resolve_s3 = true
parameter_overrides = "Environment=prod"
```

### Environment-Specific Configurations

Each environment has:
- **Separate CloudFormation stack** - Independent resource lifecycle
- **Environment tag** - All resources tagged with `Environment: dev/test/prod`
- **Separate AWS accounts** (recommended for prod) - Enhanced security isolation
- **Different stack names** - Prevents resource conflicts
- **Environment parameter** - Passed during deployment:
  ```bash
  sam deploy --parameter-overrides Environment=prod
  ```

### Deploying to Different Environments

```bash
# Deploy to dev (default)
sam deploy

# Deploy to test
sam deploy --config-env test

# Deploy to production
sam deploy --config-env prod

# Or use Make commands
make deploy          # dev
make deploy-test     # test
make deploy-prod     # prod
```

### Cost Tracking by Environment

All resources are automatically tagged with their environment, enabling:

- **Separate cost analysis** per environment in AWS Cost Explorer
- **Budget alerts** specific to production resources
- **Easy identification** of development vs production costs
- **Cost attribution** to specific teams or projects

**Example: View costs by environment**
```bash
# Use AWS Cost Explorer
# Filter by Tag: Environment = prod

# Or use AWS CLI
aws ce get-cost-and-usage \
  --time-period Start=2026-01-01,End=2026-01-31 \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --filter file://cost-filter.json
```

See [Infrastructure Guide → Resource Tagging Strategy](infrastructure-guide.md#resource-tagging-strategy) for details on using tags for cost tracking.

### Best Practices

1. **Use separate AWS accounts for production** - Enhanced security and cost isolation
2. **Tag all resources** - Enable cost tracking and resource management
3. **Test in dev/test first** - Never deploy directly to production
4. **Use different credentials** - Prod should use separate AWS credentials
5. **Enable change confirmation** - Review changes before applying in production
6. **Monitor production closely** - Set up CloudWatch alarms and budgets
7. **Backup production data** - Enable DynamoDB point-in-time recovery for prod

---

## Related Documentation

- [Infrastructure Guide](infrastructure-guide.md) - Resource tagging, monitoring, and cost estimation
- [AWS Setup Guide](aws-setup-guide.md) - AWS credentials and Cognito setup
- [Development Guide](development-guide.md) - Local development and testing

---

[← Back to README](../README.md)
