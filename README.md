# Tour Data API

Backend REST API for cycling tour management system. A serverless application built with AWS SAM, Lambda, and DynamoDB to manage rider check-ins, tour rides, rider profiles, event operations, hotel logistics, and tour staff assignments.

## 📋 Overview

This API supports managing cycling tours with approximately 100 riders, 7-8 rides per tour, and multiple staff members. It provides functionality for:

- **Rider Management**: Profile management, tour participation tracking
- **Tour Management**: Tour lifecycle, rider enrollment
- **Ride Management**: Daily ride scheduling, route planning
- **Check-in System**: Recording rider arrivals at checkpoints (Normal/Not Riding/Quit Riding)
- **Event Engine**: Event definitions, occurrences, activity scans, dashboards, and reconciliation
- **Hotel Logistics**: Hotel master data, nightly room allocations, and upload-status tracking
- **Tour Artifacts**: Upload, store, and retrieve tour-level and ride-level artifacts (maps, GPX files, elevation charts, rider booklets) in S3
- **Dashboard**: Real-time ride status and statistics
- **User Management**: Admin and staff access control

## 🏗️ Architecture

- **Platform**: AWS Serverless (Lambda, API Gateway HTTP API, DynamoDB)
- **Runtime[^1]**: Python 3.14*
- **Infrastructure**: AWS SAM (Serverless Application Model)
- **Authentication**: AWS Cognito with JWT tokens
- **Storage**: DynamoDB (5 shared tables + 11 tour-specific tables provisioned at runtime), S3 (rider photos, artifact uploads, archive exports)
- **Functions**: Lambda handlers across tours, riders, rides, check-ins, artifacts, events, hotels, notifications, and users
- **CI/CD**: GitHub Actions with automated testing and multi-environment deployment

[^1]: Supports 3.11 to 3.14. 3.14 is the default.

## Data Model

The system uses a **hybrid table strategy**:

**Shared Tables (SAM-managed):**
- **RiderProfile**: Rider personal information (persists across tours)
- **RiderTours**: Rider participation lifecycle by `profileId + tourId`
- **RiderCognitoUser**: Mapping between Cognito rider username and rider profile ID
- **TourMaster**: Tour details, status, and lifecycle data
- **AppConfig**: Shared platform configuration used by multiple clients

**Tour-Specific Tables (provisioned at runtime per tour, 11 total):**
- **TourRider-{tourId}**: Rider participation in a specific tour
- **Ride-{tourId}**: Daily ride schedule and routes for a tour
- **CheckIn-{tourId}**: Rider check-ins at destinations for a tour
- **User-{tourId}**: Admin/staff user accounts for a tour
- **Notification-{tourId}**: Tour rider notifications
- **Artifacts-{tourId}**: Tour and ride artifact metadata
- **Event-{tourId}**: Event definitions
- **EventOccurrence-{tourId}**: Dated event occurrences
- **EventActivityLogs-{tourId}**: Event activity completion records
- **Hotel-{tourId}**: Tour hotel master data
- **RoomAllocation-{tourId}**: Per-night rider room allocations

Tour-specific tables are created when a tour is provisioned and can be archived/deleted when a tour is complete (`POST /v1/tours/{tourId}/archive`).

### Tour Provisioning

Tour-specific tables can be created through two methods:

1. **CLI Script (Deployment Method):** `make provision-tour` or `python scripts/provision_tour.py` — for initial setup or CI/CD pipelines
2. **API Endpoint (Runtime Method):** `POST /v1/tours` — for external apps (e.g., Check-In App) to create tours programmatically

Both methods create the same Tour record and the same 11 tour-specific tables. See [Deployment Guide → After Deployment: Provisioning a Tour](docs/deployment-guide.md#after-deployment-provisioning-a-tour) for details.

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
- `POST /v1/tours` - Create a tour, optionally provisioning tables
- `PUT /v1/tours` - Update a tour and optionally provision it for the first time
- `PUT /v1/tours/{tourId}/provision` - Re-provision missing tour tables
- `POST /v1/tours/{tourId}/archive` - Archive a completed tour

#### Riders
- `POST /v1/riders/profile` - Create rider profile
- `GET /v1/riders/profile/{profileId}` - Get rider profile
- `PUT /v1/riders/profile/{profileId}` - Update rider profile
- `POST /v1/riders/profile/{profileId}/picture` - Generate profile picture upload URL
- `GET /v1/riders/profile/{profileId}/picture` - Generate profile picture download URL
- `GET /v1/tours/{tourId}/riders` - Get all riders for a tour
- `GET /v1/tours/{tourId}/riders/names` - Get all registered riders with riderId and name only
- `POST /v1/tours/{tourId}/riders` - Register rider for a tour
- `GET /v1/tours/{tourId}/riders/{riderId}` - Get tour rider details
- `POST /v1/tours/{tourId}/riders/{riderId}/exit` - Exit rider from tour with baggage disposition
- `POST /v1/tours/{tourId}/riders/{riderId}/exit/cancel` - Cancel rider exit
- `POST /v1/tours/{tourId}/riders/{riderId}/baggage/release` - Mark retained baggage as returned to rider
- `GET /v1/tours/{tourId}/riders/{riderId}/statistics` - Get rider statistics

#### Rides
- `GET /v1/tours/{tourId}/rides/today` - Get today's ride
- `GET /v1/tours/{tourId}/rides` - List all rides for a tour
- `GET /v1/tours/{tourId}/rides/{rideId}` - Get ride details
- `POST /v1/tours/{tourId}/rides` - Create a new ride
- `PUT /v1/tours/{tourId}/rides/{rideId}` - Update ride
- `POST /v1/tours/{tourId}/rides/open` - Open today's ride
- `POST /v1/tours/{tourId}/rides/start` - Start today's ride
- `POST /v1/tours/{tourId}/rides/{rideId}/close` - Close ride

#### Check-ins
- `POST /v1/tours/{tourId}/checkins` - Create check-in
- `GET /v1/tours/{tourId}/rides/{rideId}/checkins` - Get ride check-ins
- `GET /v1/tours/{tourId}/rides/{rideId}/dashboard` - Get dashboard data for ride
- `GET /v1/tours/{tourId}/rides/{rideId}/dashboard/progress` - Get lightweight dashboard refresh payload

#### Users
- `GET /v1/users/me` - Get current user
- `GET /v1/users/cognito` - List Cognito users with only `sub` and `name`
- `GET /v1/tours/{tourId}/users` - List tour users
- `POST /v1/tours/{tourId}/users` - Create a tour-scoped user assignment
- `PUT /v1/tours/{tourId}/users/{userId}` - Update a tour-scoped user assignment

#### Events
- `GET /v1/tours/{tourId}/events` - List event definitions
- `GET /v1/tours/{tourId}/events/{eventId}` - Get event definition
- `POST /v1/tours/{tourId}/events` - Create event definition
- `PUT /v1/tours/{tourId}/events/{eventId}` - Update event definition
- `GET /v1/tours/{tourId}/events/{eventId}/occurrences` - List occurrences for an event
- `GET /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}` - Get occurrence details
- `POST /v1/tours/{tourId}/events/{eventId}/occurrences` - Create occurrence
- `PUT /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}` - Update occurrence
- `GET /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/activity-overrides` - Get activity overrides
- `PUT /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/activity-overrides` - Update activity overrides
- `POST /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/start` - Start occurrence
- `POST /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/complete` - Complete occurrence
- `POST /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/cancel` - Cancel occurrence
- `POST /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/records` - Create activity record
- `POST /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/records/{recordId}/cancel` - Cancel activity record
- `GET /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/dashboard` - Get event dashboard
- `GET /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/dashboard/progress` - Get lightweight event dashboard progress
- `GET /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/reconciliation` - Get reconciliation payload
- `GET /v1/tours/{tourId}/events/bootstrap` - Get offline/bootstrap payload
- `GET /v1/tours/{tourId}/riders/{riderId}/events/progress` - Get rider event progress

#### Hotels
- `GET /v1/tours/{tourId}/hotels` - List hotels
- `POST /v1/tours/{tourId}/hotels` - Create hotel
- `PUT /v1/tours/{tourId}/hotels/{hotelId}` - Update hotel
- `GET /v1/tours/{tourId}/hotelstays?date={date}` - List room allocations for a stay date
- `GET /v1/tours/{tourId}/riders/{riderId}/hotelstays` - List room allocations for a rider
- `GET /v1/tours/{tourId}/hotels/{hotelId}/hotelstays?date={date}` - List room allocations for a hotel/date
- `PUT /v1/tours/{tourId}/hotelstays/{stayDate}/{riderId}` - Upsert a single-night room allocation
- `POST /v1/tours/{tourId}/hotelstays/uploads/presign` - Generate upload URL for hotel allocation CSV
- `GET /v1/tours/{tourId}/hotelstays/uploads/{uploadId}` - Get hotel allocation upload status

#### Notifications
- `GET /v1/tours/{tourId}/notifications` - List notifications (supports optional `?type=` and `?riderId=`)
- `POST /v1/tours/{tourId}/notifications` - Create notification
- `PUT /v1/tours/{tourId}/notifications/{notificationId}` - Mark notification as read

For detailed API specifications, mandatory attributes, and validation rules, see [docs/api-guide.md](docs/api-guide.md).

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
- `src/functions/` - Lambda function handlers (artifacts, checkins, events, hotels, notifications, riders, rides, tours, users)
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
| [API Guide](docs/api-guide.md) | API endpoints, mandatory attributes, validation rules, and authorization matrix |
| [Requirements](docs/Requirements.md) | Detailed requirements and use cases |
| [Solution Design](docs/SolutionDesign.md) | Architecture and data model design decisions |
| [Project Structure](docs/project-structure.md) | Project folder organization |

## 🤝 Contributing

1. Create a feature branch from `develop`
2. Make your changes
3. Run tests: `make test`
4. Run linter: `make lint`
5. Submit a pull request to `develop`

## 📝 License

[Specify your license here]


## Rider profile configuration-driven backend
This repository now supports configuration-driven rider profile attributes backed by AppConfig with Admin APIs, schema validation/merge, role-filtered staff responses, and Rider API ownership enforcement.
See `docs/rider-profile-attributes-design.md`.
