# Tour Data API

Backend REST API for cycling tour management system. A serverless application built with AWS SAM, Lambda, and DynamoDB to manage rider check-ins, tour rides, and rider profiles.

## 📋 Overview

This API supports managing cycling tours with approximately 100 riders, 7-8 rides per tour, and multiple staff members. It provides functionality for:

- **Rider Management**: Profile management, tour participation tracking
- **Tour Management**: Tour lifecycle, rider enrollment
- **Ride Management**: Daily ride scheduling, route planning
- **Check-in System**: Recording rider arrivals at checkpoints (Normal/Quick Resume/Does Not Resume)
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

- **Normal Resume (NR)**: Rider completes the ride normally
  - Only one NR check-in allowed per rider per ride
  - Cannot check-in after a Quick Resume (QR)
  
- **Quick Resume (QR)**: Rider transported to destination (e.g., via support vehicle)
  - Once a rider has QR for a ride, no further check-ins allowed for that ride
  - Prevents recording completion after being transported
  
- **Does Not Resume (DNR)**: Rider does not continue the tour
  - No further restrictions after DNR
  
- **Additional Validations**:
  - Rider must be enrolled in the tour
  - Ride must not be closed (ACTIVE or SCHEDULED status)
  - No duplicate check-ins for the same rider/ride/type combination

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- AWS CLI configured with appropriate credentials
- AWS SAM CLI ([installation guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html))
- Make (optional, for using Makefile commands)

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd tour-data-api
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements-dev.txt
   ```

3. **Build the application**
   ```bash
   sam build
   # or
   make build
   ```

4. **Deploy to AWS**
   ```bash
   # First-time deployment (guided)
   sam deploy --guided
   
   # Subsequent deployments
   sam deploy
   # or
   make deploy
   ```

### Local Development

**Start local API**
```bash
sam local start-api
# or
make local-api
```

The API will be available at `http://localhost:3000`

**Test individual Lambda functions**
```bash
sam local invoke GetActiveTourFunction -e events/get-active-tour.json
# or
make invoke FUNCTION=GetActiveTourFunction EVENT=events/get-active-tour.json
```

## 📁 Project Structure

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
├── template.yaml                  # SAM CloudFormation template
├── samconfig.toml                 # SAM CLI configuration
├── Makefile                       # Build and deployment automation
├── requirements-dev.txt           # Development dependencies
├── pytest.ini                     # Test configuration
└── README.md                      # This file
```

## 🔧 Development

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

## 🔐 Security

- All endpoints (except public ones) require JWT authentication
- IAM roles follow least-privilege principle
- DynamoDB tables use on-demand pricing (no over-provisioning)
- Sensitive data excluded from logs
- CORS configured for specific origins only

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

## � CI/CD Pipeline

The project includes a GitHub Actions workflow for continuous integration and deployment.

### Pipeline Stages

1. **Test** (on all pushes and PRs):
   - Runs linters (pylint, black)
   - Executes unit tests with coverage
   - Uploads coverage reports to Codecov

2. **Build** (after tests pass):
   - Validates SAM template
   - Builds application

3. **Deploy to Dev** (on push to `develop` branch):
   - Deploys to development environment
   - Runs smoke tests

4. **Deploy to Test** (on push to `main` branch):
   - Deploys to test environment
   - Runs integration tests

5. **Deploy to Prod** (manual approval after test):
   - Deploys to production environment
   - Runs smoke tests

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

See [docs/SolutionDesign.md](docs/SolutionDesign.md) for detailed cost breakdown.

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

# Test locally
sam local invoke YourFunctionName -e events/your-event.json
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