# Tour Data API

Backend REST API for cycling tour management system. A serverless application built with AWS SAM, Lambda, and DynamoDB to manage rider check-ins, tour rides, and rider profiles.

## 📋 Overview

This API supports managing cycling tours with approximately 100 riders, 7-8 rides per tour, and multiple staff members. It provides functionality for:

- **Rider Management**: Profile management, tour participation tracking
- **Tour Management**: Tour lifecycle, rider enrollment
- **Ride Management**: Daily ride scheduling, route planning
- **Check-in System**: Recording rider arrivals at checkpoints (Normal/Not Riding/Quit Riding)
- **Dashboard**: Real-time ride status and statistics
- **User Management**: Admin and staff access control

## 🏗️ Architecture

- **Platform**: AWS Serverless (Lambda, API Gateway HTTP API, DynamoDB)
- **Runtime**: Python 3.11
- **Infrastructure**: AWS SAM (Serverless Application Model)
- **Authentication**: AWS Cognito with JWT tokens
- **Storage**: DynamoDB (6 tables), S3 (rider photos)
- **Functions**: 15 Lambda functions handling tours, riders, rides, check-ins, and users
- **CI/CD**: GitHub Actions with automated testing and multi-environment deployment

### Data Model

- **RiderProfile**: Rider personal information
- **Tour**: Tour details and status
- **TourRider**: Rider participation in specific tours
- **Ride**: Daily ride schedule and routes
- **CheckIn**: Rider check-ins at destinations
- **User**: Admin/staff user accounts

### Business Rules

The check-in system enforces important business logic:

- **Normal Check-in**: Rider completes the ride normally by arriving at checkpoints
  - Standard check-in captured via QR code scanning at each stage
  - Multiple normal check-ins allowed per rider per ride (one at each stage)
  
- **Not Riding**: Rider transported to destination (e.g., via support vehicle)
  - Only one "Not Riding" check-in allowed per rider per ride
  - Once a rider has "Not Riding" for a ride, no further check-ins allowed for that ride
  - Prevents recording normal check-ins after being transported
  
- **Quit Riding**: Rider does not continue the tour
  - Can be recorded at any stage or remotely when rider quits in-between stages.
  - Manual entry supported for remote quitting scenarios
  - Once 'Quit Riding' no further check-ins are allowed.
  
- **Additional Validations**:
  - Rider must be enrolled in the tour
  - Ride must not be closed (ACTIVE or SCHEDULED status)
  - No duplicate check-ins for the same rider/ride/stage combination

## 🚀 Quick Start

### Prerequisites

- Python 3.12+
- AWS CLI configured with appropriate credentials
- AWS SAM CLI ([installation guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html))
- Make (optional, for using Makefile commands)

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd tour-data-api
   ```

2. **Set up virtual environment**
   ```bash
   # Create virtual environment
   python3 -m venv venv
   
   # Activate virtual environment
   source venv/bin/activate
   ```
   
   > **Note**: Always activate the virtual environment before working on the project. On Windows, use `venv\Scripts\activate` instead.

3. **Install dependencies**
   ```bash
   pip install -r requirements-dev.txt
   ```

4. **Verify AWS Configuration**
   
   Check if AWS CLI is configured and accessible:
   ```bash
   aws sts get-caller-identity
   ```
   
   If successful, you should see your AWS account details (Account ID, User ARN, etc.).
   
   **If AWS CLI is not configured**, choose one of these setup options:
   
   ### Option A: Temporary Credentials (Recommended - More Secure)
   
   Temporary credentials are more secure as they expire automatically and don't require long-term access keys.
   
   **Using AWS IAM Identity Center (SSO)**:
   ```bash
   # Configure AWS SSO
   aws configure sso
   ```
   
   You'll be prompted to enter:
   - **SSO start URL**: Your organization's SSO URL
   - **SSO Region**: Region where your SSO is configured
   - **SSO account**: Select your AWS account
   - **SSO role**: Select the role to use
   - **Default region**: e.g., `ap-south-1`, `us-east-1`, etc.
   - **Output format**: `json` (recommended)
   
   After configuration, login to get temporary credentials:
   ```bash
   # Login to SSO (credentials valid for hours, not permanent)
   aws sso login --profile your-profile-name
   
   # Verify access
   aws sts get-caller-identity --profile your-profile-name
   ```
   
   **Using AWS STS Assume Role** (if you have a role to assume):
   ```bash
   # Get temporary credentials (valid for 1-12 hours)
   aws sts assume-role \
     --role-arn arn:aws:iam::ACCOUNT_ID:role/YourRoleName \
     --role-session-name dev-session
   
   # Set temporary credentials as environment variables
   export AWS_ACCESS_KEY_ID=<TemporaryAccessKeyId>
   export AWS_SECRET_ACCESS_KEY=<TemporarySecretAccessKey>
   export AWS_SESSION_TOKEN=<SessionToken>
   ```
   
   ### Option B: Long-term Access Keys (Less Secure)
   
   ```bash
   # Configure AWS CLI with your credentials
   aws configure
   ```
   
   You'll be prompted to enter:
   - **AWS Access Key ID**: Your AWS access key
   - **AWS Secret Access Key**: Your AWS secret key
   - **Default region name**: e.g., `ap-south-1`, `us-east-1`, etc.
   - **Default output format**: `json` (recommended)
   
   > **Note**: If you don't have AWS credentials, create them in the AWS Console:
   > 1. Go to IAM → Users → Your User → Security Credentials
   > 2. Create Access Key → Command Line Interface (CLI)
   > 3. Download and save the credentials securely
   > 
   > **Security Best Practice**: Rotate access keys regularly and use temporary credentials when possible.
   
   **Verify AWS region** (optional but recommended):
   ```bash
   # Check current region
   aws configure get region
   
   # Set region if needed
   aws configure set region ap-south-1
   ```
   
   **SAM CLI configuration**: SAM uses the same AWS credentials as AWS CLI. No separate configuration needed.

5. **Build the application**
   
   This command packages your Lambda functions and dependencies, preparing them for deployment. It creates a `.aws-sam` directory with the built artifacts.
   
   ```bash
   sam build
   # or
   make build
   ```
   
   The build process:
   - Resolves dependencies from `requirements.txt`
   - Packages Lambda functions and layers
   - Validates the SAM template
   - Creates deployment artifacts

6. **Deploy to AWS**
   
   This command deploys your application to AWS by creating/updating a CloudFormation stack with all resources (Lambda functions, API Gateway, DynamoDB tables, IAM roles, etc.).
   
   ```bash
   # First-time deployment (guided)
   # You'll be prompted to configure stack name, region, and deployment preferences
   sam deploy --guided
   
   # Subsequent deployments (uses saved configuration from samconfig.toml)
   sam deploy
   # or
   make deploy
   ```
   
   The deployment process:
   - Uploads artifacts to S3
   - Creates/updates CloudFormation stack
   - Provisions all AWS resources (Lambda, API Gateway, DynamoDB, etc.)
   - **Applies resource tags automatically** for cost tracking and management
   - Outputs the API endpoint URL upon completion
   
   > **Note**: First deployment may take 3-5 minutes. Save the API endpoint URL from the output. All created resources will be tagged with `Project=tour-data-api` and `Environment=<env>` for cost analysis.

### Local Development

> **Remember**: Activate your virtual environment before running any commands:
> ```bash
> source venv/bin/activate
> ```

#### Understanding Local Development Data

**Important**: By default, `sam local start-api` connects to your **real AWS DynamoDB tables** - not local data.

When you run the local API:
- Lambda functions execute on your local machine (using Docker)
- **Data operations go to actual AWS resources** (DynamoDB tables, S3 buckets)
- Uses your AWS credentials from `aws configure`
- **Any data changes affect your AWS environment** (typically dev environment)

**Pros**: Test with realistic data, proper AWS service integration  
**Cons**: Requires AWS credentials, changes affect real environment, incurs minimal AWS costs

#### Local Development Options

**Option 1: Use AWS Resources (Default - Recommended)**

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

**Testing Individual Lambda Functions:**

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

**Option 2: Unit Testing with Mocked AWS Services**

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

See [tests/test_lambda_functions.py](tests/test_lambda_functions.py) for examples.

> **Note**: For local API testing with real AWS resources, use Option 1 above. For unit testing without AWS, use pytest with moto.

## 📁 Project Structure

For detailed project organization and folder structure, see [docs/project-structure.md](docs/project-structure.md).

**Quick Overview:**
- `src/functions/` - Lambda function handlers (checkins, riders, rides, tours, users)
- `src/layers/common/` - Shared utilities and dependencies
- `docs/` - Requirements, architecture, and design documentation
- `tests/` - Unit and integration tests
- `events/` - Sample event payloads for local testing
- `template.yaml` - SAM CloudFormation template
- `.github/workflows/` - CI/CD pipeline configuration

## 🔧 Development

> **Important**: Always ensure your virtual environment is activated before development work:
> ```bash
> source venv/bin/activate  # On Linux/Mac
> # or
> venv\Scripts\activate     # On Windows
> ```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_validation.py

# or use Make
make test
```

### Code Quality

```bash
# Run linter
pylint src/layers/common/python/*.py

# Format code
black src/

# or use Make
make lint
make format
```

### Useful Commands

```bash
# Build and deploy to dev environment
make deploy

# Deploy to test environment
make deploy-test

# Deploy to production (with confirmation)
make deploy-prod

# View CloudWatch logs
make logs FUNCTION=GetActiveTourFunction

# Tail logs in real-time
make logs-tail FUNCTION=CreateCheckinFunction

# Sync code changes (build + deploy)
make sync

# Clean build artifacts
make clean

# Validate SAM template
make validate
```

## 📚 API Documentation

### Base URL

After deployment, your API will be available at:
```
https://<api-id>.execute-api.<region>.amazonaws.com/
```

### Authentication

Most endpoints require JWT authentication via AWS Cognito:
```
Authorization: Bearer <jwt-token>
```

### Endpoints

#### Tours
- `GET /tours/active` - Get currently active tour
- `GET /tours/{tourId}` - Get tour details

#### Riders
- `GET /riders/{riderId}` - Get rider profile
- `PUT /riders/{riderId}` - Update rider profile
- `GET /tours/{tourId}/riders/{riderId}` - Get tour rider details

#### Rides
- `GET /tours/{tourId}/rides/today` - Get today's ride
- `GET /tours/{tourId}/rides` - List all rides for tour
- `GET /tours/{tourId}/rides/{rideId}` - Get ride details
- `POST /tours/{tourId}/rides` - Create a new ride
- `PUT /tours/{tourId}/rides/{rideId}` - Update ride
- `POST /tours/{tourId}/rides/{rideId}/close` - Close ride

#### Check-ins
- `POST /checkins` - Create check-in
- `GET /tours/{tourId}/rides/{rideId}/checkins` - Get ride check-ins
- `GET /dashboard/{rideId}` - Get dashboard data for ride

#### Users
- `GET /users/me` - Get current user
- `GET /tours/{tourId}/users` - List tour users

For detailed API specifications, see [docs/SolutionDesign.md](docs/SolutionDesign.md).

## 🌍 Environments

The project supports three environments:

- **dev** (default): Development environment
- **test**: Testing/staging environment
- **prod**: Production environment

Configure environments in [samconfig.toml](samconfig.toml).

**Environment-Specific Configurations:**
- Each environment has its own CloudFormation stack
- Resources are tagged with `Environment` tag (dev/test/prod)
- Separate AWS accounts recommended for production
- Environment parameter passed during deployment:
  ```bash
  sam deploy --parameter-overrides Environment=prod
  ```

**Cost Tracking by Environment:**
All resources are automatically tagged with their environment, enabling:
- Separate cost analysis per environment in AWS Cost Explorer
- Budget alerts specific to production resources
- Easy identification of development vs production costs

See [Resource Tagging Strategy](#resource-tagging-strategy) for details on using tags for cost tracking.

## 🔐 Security

### Authentication & Authorization

**For Consumer Applications (Check-In App, Rider App, etc.):**
- Consumer apps authenticate users via **AWS Cognito** (username/password, MFA, etc.)
- Upon successful authentication, Cognito issues a **JWT token**
- Consumer apps include this JWT token in the `Authorization` header of API requests
- API Gateway validates the JWT token before allowing access to Lambda functions
- **No need to manage Lambda IAM roles** - this is handled automatically by AWS

**Internal AWS Security (Transparent to Consumer Apps):**
- Each Lambda function has its own **execution role** (IAM role)
- These roles define what AWS resources the function can access (DynamoDB tables, S3 buckets, etc.)
- Follows **least-privilege principle** - each function only has permissions it needs
- Example: `CreateCheckinFunction` can write to CheckIn table but not modify Ride table

**Additional Security Measures:**
- All endpoints (except public ones) require JWT authentication
- IAM roles follow least-privilege principle
- DynamoDB tables use on-demand pricing (no over-provisioning)
- Sensitive data excluded from logs
- CORS configured for specific origins only

### How It Works (End-to-End Security Flow)

1. **User Login**: Consumer app sends credentials to Cognito
2. **Token Issued**: Cognito validates and returns JWT token
3. **API Request**: Consumer app calls API with JWT in `Authorization: Bearer <token>` header
4. **Token Validation**: API Gateway validates JWT with Cognito
5. **Lambda Invocation**: If valid, API Gateway invokes Lambda function
6. **Resource Access**: Lambda uses its execution role to access DynamoDB/S3/etc.
7. **Response**: Result returned to consumer app

> **Key Point**: Consumer apps only need to handle JWT authentication. The Lambda execution roles and AWS resource access are entirely managed by the infrastructure and are not a concern for consumer application developers.

### Setting up Cognito

The API uses AWS Cognito for authentication. To configure:

1. **Create Cognito User Pool** (or update template.yaml to automate):
   ```bash
   aws cognito-idp create-user-pool --pool-name tour-data-api-users
   ```

2. **Create App Client**:
   ```bash
   aws cognito-idp create-user-pool-client \
     --user-pool-id <pool-id> \
     --client-name tour-data-api-client \
     --generate-secret
   ```

3. **Update SAM template** with your User Pool ARN in the `CognitoUserPoolArn` parameter

4. **Create test users**:
   ```bash
   aws cognito-idp admin-create-user \
     --user-pool-id <pool-id> \
     --username admin@example.com \
     --user-attributes Name=email,Value=admin@example.com
   ```

5. **Get JWT token** for testing:
   ```bash
   aws cognito-idp initiate-auth \
     --auth-flow USER_PASSWORD_AUTH \
     --client-id <client-id> \
     --auth-parameters USERNAME=admin@example.com,PASSWORD=<password>
   ```

## 🚀 CI/CD Pipeline

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

1. **Test**:
   - Runs linters (pylint, black)
   - Executes unit tests with coverage
   - Uploads coverage reports to Codecov

2. **Build**:
   - Validates SAM template
   - Builds application

3. **Deploy** (to selected environment):
   - Deploys to the chosen environment (dev, test, or prod)
   - Provisions/updates all AWS resources
   - Outputs API endpoint URL

### Setting up GitHub Actions

Add these secrets to your GitHub repository (Settings → Secrets and variables → Actions):

**For Dev/Test environments:**
- `AWS_ACCESS_KEY_ID` - AWS access key with deployment permissions
- `AWS_SECRET_ACCESS_KEY` - AWS secret key

**For Production environment:**
- `AWS_ACCESS_KEY_ID_PROD` - AWS access key for production account
- `AWS_SECRET_ACCESS_KEY_PROD` - AWS secret key for production

**Create IAM user with required permissions:**
```bash
# Create deployment user
aws iam create-user --user-name github-actions-deployer

# Attach necessary policies (SAM deployment requires multiple permissions)
aws iam attach-user-policy --user-name github-actions-deployer \
  --policy-arn arn:aws:iam::aws:policy/AWSCloudFormationFullAccess

aws iam attach-user-policy --user-name github-actions-deployer \
  --policy-arn arn:aws:iam::aws:policy/IAMFullAccess

aws iam attach-user-policy --user-name github-actions-deployer \
  --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess

aws iam attach-user-policy --user-name github-actions-deployer \
  --policy-arn arn:aws:iam::aws:policy/AWSLambda_FullAccess

# Create access keys
aws iam create-access-key --user-name github-actions-deployer
```

### Workflow File

See [.github/workflows/ci-cd.yml](.github/workflows/ci-cd.yml) for the complete pipeline configuration.
### AWS Resources Created by Deployment

When the CI/CD pipeline (or `sam deploy`) executes, the following AWS resources are automatically created/updated:

#### Compute & API
- **15 Lambda Functions**:
  - Tours: `GetActiveTourFunction`, `GetTourFunction`
  - Riders: `GetRiderProfileFunction`, `UpdateRiderProfileFunction`, `GetTourRiderFunction`
  - Rides: `GetTodaysRideFunction`, `GetRideFunction`, `ListRidesFunction`, `CreateRideFunction`, `UpdateRideFunction`, `CloseRideFunction`
  - Check-ins: `CreateCheckinFunction`, `GetRideCheckinsFunction`, `GetDashboardDataFunction`
  - Users: `GetCurrentUserFunction`, `ListTourUsersFunction`
- **1 Lambda Layer**: CommonLayer (shared utilities and dependencies)
- **1 API Gateway HTTP API**: RESTful API with 15+ endpoints
- **15 Lambda Permissions**: API Gateway invoke permissions for each function

#### Data Storage
- **6 DynamoDB Tables** (On-demand billing mode):
  - `RiderProfile` - Rider master data with GSI for email lookups
  - `Tour` - Tour information with GSI for status queries
  - `TourRider` - Tour enrollment mapping
  - `Ride` - Daily ride details with GSI for date-based queries
  - `CheckIn` - Check-in records with multiple GSIs
  - `User` - Admin/staff user accounts
- **1 S3 Bucket**: Rider photo storage with lifecycle policies

#### Security & Permissions
- **15 IAM Roles**: One execution role per Lambda function (least-privilege security)
  - These roles define what AWS resources each Lambda can access (DynamoDB, S3, CloudWatch)
  - **Consumer apps don't interact with these roles** - they're internal to AWS infrastructure
- **IAM Policies**: Least-privilege policies attached to each execution role
- **API Gateway Authorizer**: JWT authorizer connected to Cognito (validates consumer app requests)

> **How Consumer Apps Access the API**: Consumer applications (Check-In App, Rider App, etc.) authenticate users via AWS Cognito and receive JWT tokens. They send these tokens in API requests. API Gateway validates the token and invokes the appropriate Lambda function. The Lambda function then uses its execution role to access AWS resources. This architecture is **transparent to consumer apps** - they only need to handle JWT authentication, not Lambda execution roles.

#### Monitoring & Logging
- **15 CloudWatch Log Groups**: One per Lambda function with retention policies
- **CloudWatch Alarms** (optional): Can be added for monitoring errors and throttles

#### Networking (if VPC configured)
- **VPC Integration**: Lambda functions can be configured for VPC access
- **Security Groups** and **Subnets**: If VPC deployment is enabled

#### CloudFormation
- **1 CloudFormation Stack**: Named `tour-data-api` (or custom name from samconfig.toml)
- **S3 Bucket**: SAM deployment bucket for storing deployment artifacts

**Total Resources**: ~70+ AWS resources created and managed as infrastructure-as-code

> **Note**: The exact resources depend on your `template.yaml` configuration. All resources are tagged with project identifiers for cost tracking and management.

### Resource Tagging Strategy

All AWS resources created by this project are automatically tagged for cost tracking, management, and compliance.

**Standard Tags Applied to All Resources:**

| Tag Key | Tag Value | Purpose |
|---------|-----------|---------|
| `Project` | `tour-data-api` | Identify all resources belonging to this project |
| `Environment` | `dev` / `test` / `prod` | Distinguish between deployment environments |
| `ManagedBy` | `SAM` or `CloudFormation` | Indicate infrastructure-as-code tool |
| `Application` | `TourManagement` | Logical application grouping |
| `Owner` | (Configurable) | Team or individual responsible for the resources |
| `CostCenter` | (Configurable) | Your organization's cost center code |

**How to Configure Tags:**

Tags are defined in `template.yaml`. Standard tags are applied globally, and you can add custom tags via parameters.

**Standard Tags (Applied Automatically):**
```yaml
Globals:
  Function:
    Tags:
      Project: tour-data-api
      Environment: !Ref Environment
      Application: TourManagement
      ManagedBy: SAM
      Owner: !Ref Owner
      CostCenter: !Ref CostCenter
```

**Adding Custom Tags During Deployment:**

You can provide custom tag values when deploying:

```bash
# Using sam deploy with custom tags
sam deploy --parameter-overrides \
  Environment=prod \
  Owner="DevOps Team" \
  CostCenter="CC-1234"

# Or configure in samconfig.toml for persistent values
```

**Configure in samconfig.toml:**

Edit `samconfig.toml` to set persistent tag values for each environment:

```toml
# Development environment
[default.deploy.parameters]
capabilities = "CAPABILITY_IAM"
confirm_changeset = true
resolve_s3 = true
parameter_overrides = "Environment=dev Owner=\"DevTeam\" CostCenter=\"CC-1234\""

# Test environment
[test.deploy.parameters]
capabilities = "CAPABILITY_IAM"
confirm_changeset = true
resolve_s3 = true
parameter_overrides = "Environment=test Owner=\"QA Team\" CostCenter=\"CC-1234\""

# Production environment
[prod.deploy.parameters]
capabilities = "CAPABILITY_IAM"
confirm_changeset = true
parameter_overrides = "Environment=prod Owner=\"Operations Team\" CostCenter=\"CC-5678\""
```

> **Note**: When updating `samconfig.toml`, uncomment and modify the `parameter_overrides` line with your custom tag values.

**To Add Additional Custom Tags:**

1. Add new parameters in `template.yaml`:
   ```yaml
   Parameters:
     CustomTag1:
       Type: String
       Default: ''
       Description: Custom tag for your specific needs
   ```

2. Add to Globals section:
   ```yaml
   Globals:
     Function:
       Tags:
         CustomTag1: !Ref CustomTag1
   ```

3. Deploy with values:
   ```bash
   sam deploy --parameter-overrides CustomTag1="YourValue"
   ```

**Using Tags for Cost Analysis:**

1. **AWS Cost Explorer**:
   ```bash
   # View costs by environment
   # Go to AWS Console → Cost Explorer → Filters → Tag: Environment
   ```

2. **AWS CLI - Get costs by tag**:
   ```bash
   # Get monthly costs for dev environment
   aws ce get-cost-and-usage \
     --time-period Start=2026-01-01,End=2026-01-31 \
     --granularity MONTHLY \
     --metrics UnblendedCost \
     --filter file://cost-filter.json
   
   # cost-filter.json:
   # {
   #   "Tags": {
   #     "Key": "Environment",
   #     "Values": ["dev"]
   #   }
   # }
   ```

3. **Cost Allocation Tags**:
   - Enable cost allocation tags in AWS Billing Console
   - Go to Billing → Cost Allocation Tags
   - Activate `Project`, `Environment`, `Application` tags
   - Wait 24 hours for tags to appear in Cost Explorer

4. **Generate Cost Reports**:
   ```bash
   # List resources by tag
   aws resourcegroupstaggingapi get-resources \
     --tag-filters Key=Project,Values=tour-data-api \
     --resource-type-filters lambda dynamodb apigateway
   ```

**Benefits of Tagging:**
- **Cost Tracking**: Analyze spending per environment (dev vs prod)
- **Resource Management**: Identify and clean up unused resources
- **Compliance**: Track resources for audit and governance
- **Automation**: Bulk operations on tagged resources (e.g., backup, deletion)
- **Budgeting**: Set budget alerts based on tags

> **Best Practice**: Update tags in `template.yaml` before deployment. Tags are applied during stack creation/update and automatically propagate to all resources.
## �📊 Monitoring

### CloudWatch Logs

Each Lambda function logs to CloudWatch:
```bash
# View logs for a function
make logs FUNCTION=GetActiveTourFunction

# Tail logs in real-time
make logs-tail FUNCTION=CreateCheckinFunction
```

### CloudWatch Metrics

Monitor Lambda invocations, errors, duration, and throttles in CloudWatch Metrics.

## 💰 Cost Estimation

Expected monthly costs (100 riders, 7-8 rides, 5-year retention):

- **DynamoDB**: ~$2-5/month (on-demand pricing)
- **Lambda**: ~$0.50-1/month (free tier covers most usage)
- **API Gateway HTTP API**: ~$0.50-1/month
- **S3**: ~$1-2/month (photo storage)
- **CloudWatch**: ~$1-2/month (logs)

**Total**: ~$5-11/month

**Cost Management:**
- All resources are tagged by environment (dev/test/prod) for granular cost tracking
- Use AWS Cost Explorer with tag filters to analyze spending per environment
- Set up budget alerts using tags: `Project=tour-data-api`
- Enable Cost Allocation Tags in AWS Billing Console for detailed reports

See [docs/SolutionDesign.md](docs/SolutionDesign.md) for detailed cost breakdown and the [Resource Tagging Strategy](#resource-tagging-strategy) section for cost tracking using tags.

## 📖 Additional Documentation

- [Requirements.md](docs/Requirements.md) - Detailed requirements and use cases
- [SolutionDesign.md](docs/SolutionDesign.md) - Architecture, data model, API specs
- [project-structure.md](docs/project-structure.md) - Project organization

## 📈 Project Statistics

- **Lambda Functions**: 15 (tours, riders, rides, check-ins, users)
- **DynamoDB Tables**: 6 (RiderProfile, Tour, TourRider, Ride, CheckIn, User)
- **API Endpoints**: 15+ REST endpoints
- **Common Utilities**: 5 shared modules (models, validation, response, db utils, logger)
- **Test Coverage**: Unit tests for validation, integration tests ready
- **Infrastructure**: Fully automated with SAM and GitHub Actions

## 🤝 Contributing

1. Create a feature branch from `develop`
2. Make your changes
3. Run tests: `make test`
4. Run linter: `make lint`
5. Submit a pull request to `develop`

## 📝 License

[Specify your license here]

## 🐛 Troubleshooting

### SAM Build Fails

```bash
# Clear cache and rebuild
make clean
make build
```

### Deployment Fails

```bash
# Validate template
make validate

# Check AWS credentials
aws sts get-caller-identity

# View CloudFormation events
aws cloudformation describe-stack-events --stack-name tour-data-api
```

### Lambda Function Errors

```bash
# View recent logs
make logs FUNCTION=YourFunctionName

# Tail logs
make logs-tail FUNCTION=YourFunctionName

# Test locally with AWS resources
sam local invoke YourFunctionName -e events/your-event.json

# Or run unit tests with mocked AWS services
pytest tests/test_lambda_functions.py -v
```

### DynamoDB Issues

```bash
# List tables
aws dynamodb list-tables

# Describe table
aws dynamodb describe-table --table-name RiderProfile

# Scan table (dev only!)
aws dynamodb scan --table-name RiderProfile --limit 10
```

## 📞 Support

For issues and questions:
- Review documentation in `docs/` folder
- Check CloudWatch logs for errors
- Review SAM template configuration