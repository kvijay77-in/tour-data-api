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
- **Runtime[^1]**: Python 3.14*
- **Infrastructure**: AWS SAM (Serverless Application Model)
- **Authentication**: AWS Cognito with JWT tokens
- **Storage**: DynamoDB (2 shared tables + tour-specific tables provisioned at runtime), S3 (rider photos, archive exports)
- **Functions**: 20 Lambda functions handling tours, riders, rides, check-ins, and users
- **CI/CD**: GitHub Actions with automated testing and multi-environment deployment

[^1]: Supports 3.11 to 3.14. 3.14 is the default.

## Data Model

The system uses a **hybrid table strategy**:

**Shared Tables (SAM-managed):**
- **RiderProfile**: Rider personal information (persists across tours)
- **Tour**: Tour details, status, and lifecycle data

**Tour-Specific Tables (provisioned at runtime per tour):**
- **TourRider-{tourId}**: Rider participation in a specific tour
- **Ride-{tourId}**: Daily ride schedule and routes for a tour
- **CheckIn-{tourId}**: Rider check-ins at destinations for a tour
- **User-{tourId}**: Admin/staff user accounts for a tour

Tour-specific tables are created when a tour is provisioned and can be archived/deleted when a tour is complete (`POST /v1/tours/{tourId}/archive`).

### Tour Provisioning

Tour-specific tables can be created through two methods:

1. **CLI Script (Deployment Method):** `make provision-tour` or `python scripts/provision_tour.py` — for initial setup or CI/CD pipelines
2. **API Endpoint (Runtime Method):** `POST /v1/tours` — for external apps (e.g., Check-In App) to create tours programmatically

Both methods create the same Tour record and 4 tour-specific tables. See [Deployment Guide → After Deployment: Provisioning a Tour](docs/deployment-guide.md#after-deployment-provisioning-a-tour) for details.

## Business Rules

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
  - Ride must not be closed (ACTIVE or PLANNED status)
  - No duplicate check-ins for the same rider/ride/stage combination

## Getting Started

- **Developers**: See the [Development Guide](docs/development-guide.md) for environment setup, deploying to dev, local testing, and daily workflows.
- **CI/CD & Multi-Environment Deployment**: See the [Deployment Guide](docs/deployment-guide.md) for GitHub Actions setup and deploying to test/prod.

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
- `GET /v1/tours/active` - Get currently active tour
- `GET /v1/tours/{tourId}` - Get tour details
- `GET /v1/tours` - List all tours (optional `?status=` filter)
- `POST /v1/tours` - Create and provision a new tour
- `POST /v1/tours/{tourId}/archive` - Archive a completed tour

#### Riders
- `GET /v1/riders/profile/{profileId}` - Get rider profile
- `PUT /v1/riders/profile/{profileId}` - Update rider profile
- `GET /v1/tours/{tourId}/riders` - Get all riders for a tour
- `GET /v1/tours/{tourId}/riders/{riderId}` - Get tour rider details

#### Rides
- `GET /v1/tours/{tourId}/rides/today` - Get today's ride
- `GET /v1/tours/{tourId}/rides` - List all rides for a tour
- `GET /v1/tours/{tourId}/rides/{rideId}` - Get ride details
- `POST /v1/tours/{tourId}/rides` - Create a new ride
- `PUT /v1/tours/{tourId}/rides/{rideId}` - Update ride
- `POST /v1/tours/{tourId}/rides/{rideId}/close` - Close ride

#### Check-ins
- `POST /v1/tours/{tourId}/checkins` - Create check-in
- `GET /v1/tours/{tourId}/rides/{rideId}/checkins` - Get ride check-ins
- `GET /v1/tours/{tourId}/rides/{rideId}/dashboard` - Get dashboard data for ride

#### Users
- `GET /v1/users/me` - Get current user
- `GET /v1/tours/{tourId}/users` - List tour users

For detailed API specifications, see [docs/SolutionDesign.md](docs/SolutionDesign.md).

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

## 📖 Documentation

| Document | Description |
|----------|-------------|
| [Documentation Index](docs/docs-index.md) | Complete guide to all project documentation |
| [AWS Setup Guide](docs/aws-setup-guide.md) | AWS CLI credentials, Cognito setup, JWT token generation |
| [Development Guide](docs/development-guide.md) | Environment setup, deploy to dev, local testing, unit tests, troubleshooting |
| [Deployment Guide](docs/deployment-guide.md) | CI/CD via GitHub Actions, multi-environment deployment, AWS resources reference |
| [Infrastructure Guide](docs/infrastructure-guide.md) | Resource tagging, CloudWatch monitoring, cost estimation |
| [Requirements](docs/Requirements.md) | Detailed requirements and use cases |
| [Solution Design](docs/SolutionDesign.md) | Architecture, data model, API specifications |
| [Project Structure](docs/project-structure.md) | Project folder organization |

## 🤝 Contributing

1. Create a feature branch from `develop`
2. Make your changes
3. Run tests: `make test`
4. Run linter: `make lint`
5. Submit a pull request to `develop`

## 📝 License

[Specify your license here]
