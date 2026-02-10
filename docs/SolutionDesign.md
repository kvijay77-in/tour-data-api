This document covers the solution design aspects of the Data models and related API that will be used in other mobile and web apps to access and update data. This document must be adhered to at all times when doing any development work. If there is any conflict between the copilot-instructions.md and this document, it must be flagged for resolution.

This is an evolving document and hence latest info must be referred to at all times.

# Design Principles:  

- DynamoDB tables must be used to allow cost saving.
- API must be built to be usable for all apps that will access and manage data. 
- Zero trust authentication must be implemented to ensure data is secured.
- Authorization should also implemented for Need to know basis.

# Data access flow 
At high level this is the flow expected for the end-user. Scope for this project is limited to flow HTTP API to DynamoDB.
```
Mobile App
    ↓
  [Cognito User Pool]
    ↓ (JWT tokens)
Mobile App makes API call
    ↓ (Authorization: Bearer <JWT>)
  [API Gateway HTTP API]
    ↓ (JWT Authorizer validates)
  [Lambda Functions]
    ↓
  [DynamoDB]
  ```
# Access Patterns

Based on Check-In App requirements, the following access patterns are critical:

## Primary Access Patterns

1. **Dashboard Data**
   - Get all riders for current tour
   - Get ride details by date (today's ride)
   - Get all check-ins for a specific ride
   - Get rider profile information by Rider ID

2. **Check-In Operations**
   - Create check-in record (QR scan or manual)
   - Get existing check-ins for a rider in a ride
   - Update check-in status (Not Riding, Quit Riding)

3. **Ride Management**
   - Get all rides for a tour
   - Get ride by ID
   - Create/update ride details
   - Update ride status (Active/Closed)

4. **Rider Management**
   - Get rider profile by Profile ID
   - Get rider profile by Rider ID (requires TourRider lookup)
   - Get all tour riders for a specific tour

5. **Historical Data**
   - Query rides by date range
   - Get historical check-in data

6. **User Authentication**
   - Get user profile for authorization
   - Validate user permissions

# DynamoDB Table Design

Given the small data volume (~100 riders, ~40 rides over 5 years, ~3,200 check-ins per ride max), we'll use **multiple tables** for clarity, maintainability, and optimal access patterns.

## Table 1: RiderProfile

**Purpose:** Master rider data, tour-agnostic

| Attribute | Type | Description |
|-----------|------|-------------|
| PK | String | `PROFILE#<uuid>` |
| profileId | String | UUID |
| name | String | Rider's full name |
| email | String | Email address |
| phone | String | Contact number |
| emergencyContactName | String | Emergency contact name |
| emergencyContactPhone | String | Emergency contact number |
| photoS3Key | String | S3 object key for photo |
| createdAt | String | ISO 8601 timestamp |
| updatedAt | String | ISO 8601 timestamp |

**Indexes:**
- Primary Key: `PK` (partition key only)
- GSI1: `email` (PK), `profileId` (SK) - For email lookup

**Notes:**
- Small table (~200-500 profiles over time)
- Simple key-value lookups by profile ID
- Photo stored in S3, only reference stored here

## Table 2: Tour

**Purpose:** Tour definitions (yearly tours)

| Attribute | Type | Description |
|-----------|------|-------------|
| PK | String | `TOUR#<year>` |
| tourId | String | Unique tour identifier (e.g., TOUR2026) |
| year | Number | Tour year |
| name | String | Tour name |
| startDate | String | ISO 8601 date |
| endDate | String | ISO 8601 date |
| status | String | PLANNING, ACTIVE, COMPLETED, ARCHIVED |
| description | String | Tour description |
| createdAt | String | ISO 8601 timestamp |
| updatedAt | String | ISO 8601 timestamp |

**Indexes:**
- Primary Key: `PK` (partition key only)

**Notes:**
- Very small table (~6 tours over 5 years)
- Lookup by year or tourId
- Status helps identify active tour

## Table 3: TourRider

**Purpose:** Rider registration for specific tours

| Attribute | Type | Description |
|-----------|------|-------------|
| PK | String | `TOUR#<tourId>` |
| SK | String | `RIDER#<riderId>` |
| tourId | String | Tour identifier |
| riderId | String | Tour-specific rider ID (R1, R2, etc.) |
| profileId | String | Reference to RiderProfile |
| registeredAt | String | ISO 8601 timestamp |
| qrCodeData | String | Encoded QR code data (currently just riderId) |
| status | String | REGISTERED, ACTIVE, WITHDRAWN |
| createdAt | String | ISO 8601 timestamp |
| updatedAt | String | ISO 8601 timestamp |

**Indexes:**
- Primary Key: `PK` (partition), `SK` (sort)
- GSI1: `riderId` (PK), `tourId` (SK) - For riderId lookup across tours
- GSI2: `profileId` (PK), `tourId` (SK) - For profile lookup

**Notes:**
- Partition by tour for efficient tour-scoped queries
- GSI1 allows quick rider lookup when scanning QR code
- Max ~100 items per partition (one tour)

## Table 4: Ride

**Purpose:** Daily ride configurations

| Attribute | Type | Description |
|-----------|------|-------------|
| PK | String | `TOUR#<tourId>` |
| SK | String | `RIDE#<rideId>` |
| rideId | String | Unique ride identifier (e.g., RIDE001) |
| tourId | String | Tour identifier |
| date | String | ISO 8601 date (YYYY-MM-DD) |
| rideNo | Number | Sequence number for the day |
| name | String | Short name (e.g., Day1, Day2) |
| startLocation | String | Starting place |
| finishLocation | String | Finishing place |
| description | String | Optional description |
| totalDistance | Number | Distance in km |
| flagOffTime | String | Planned flag-off time |
| status | String | PLANNED, ACTIVE, COMPLETED, CLOSED |
| stages | List | Array of stage objects (see below) |
| createdAt | String | ISO 8601 timestamp |
| updatedAt | String | ISO 8601 timestamp |
| startedAt | String | Actual start timestamp |
| completedAt | String | Completion timestamp |
| closedAt | String | Closed/locked timestamp |

**Stage Object Structure (embedded in stages array):**
```json
{
  "stageId": "S001",
  "stageNumber": 1,
  "type": "START|PIT_STOP|FINISH",
  "name": "Start|PS1|PS2|Finish",
  "location": "Location name",
  "distanceFromStart": 0,
  "estimatedTimeFromStart": 0
}
```

**Indexes:**
- Primary Key: `PK` (partition), `SK` (sort)
- GSI1: `date` (PK), `tourId` (SK) - For date-based lookup (today's ride)
- GSI2: `status` (PK), `date` (SK) - For querying active/completed rides

**Notes:**
- Partition by tour for efficient tour-scoped queries
- Stages embedded as array (max ~5-6 stages per ride)
- GSI1 critical for "get today's ride" query
- Max ~8 rides per tour partition

## Table 5: CheckIn

**Purpose:** Check-in records for all riders across stages

| Attribute | Type | Description |
|-----------|------|-------------|
| PK | String | `RIDE#<rideId>` |
| SK | String | `CHECKIN#<riderId>#<stageNumber>#<timestamp>` |
| checkInId | String | Unique check-in ID (UUID) |
| riderId | String | Rider ID |
| rideId | String | Ride ID |
| tourId | String | Tour ID (for cross-reference) |
| stageNumber | Number | Stage number (1-based) |
| stageId | String | Stage ID reference |
| timestamp | String | ISO 8601 timestamp of check-in |
| checkedInBy | String | User ID who performed check-in |
| method | String | QR_SCAN, MANUAL, FALLBACK |
| isNotRiding | Boolean | True if Not Riding |
| isQuitRiding | Boolean | True if Quit Riding |
| isManualEntry | Boolean | True if manual entry |
| notes | String | Optional notes |
| location | Map | {latitude: Number, longitude: Number} (optional) |
| createdAt | String | ISO 8601 timestamp |

**Indexes:**
- Primary Key: `PK` (partition), `SK` (sort)
- GSI1: `riderId` (PK), `timestamp` (SK) - For rider history
- GSI2: `tourId#riderId` (PK), `timestamp` (SK) - For rider + tour queries

**Notes:**
- Partition by ride for efficient dashboard queries
- All check-ins for a ride retrieved in single query
- SK design allows sorting by rider, then stage, then time
- Max ~600 items per partition (100 riders × 6 stages)
- GSI1 for rider-specific check-in history

## Table 6: User (Optional)

**Purpose:** User profile data if Cognito insufficient

| Attribute | Type | Description |
|-----------|------|-------------|
| PK | String | `USER#<userId>` |
| SK | String | `TOUR#<tourId>` |
| userId | String | Cognito user sub |
| username | String | Username |
| email | String | Email |
| name | String | Full name |
| role | String | ADMINISTRATOR, SUPER_USER, PIT_STOP_CREW, HOTEL_STAFF, GUEST |
| assignedStage | Number | For pit stop crew (optional) |
| tourId | String | Tour ID |
| status | String | ACTIVE, INACTIVE, SUSPENDED |
| createdAt | String | ISO 8601 timestamp |
| updatedAt | String | ISO 8601 timestamp |

**Indexes:**
- Primary Key: `PK` (partition), `SK` (sort)
- GSI1: `email` (PK), `tourId` (SK) - For email lookup

**Notes:**
- Only created if Cognito data insufficient
- Partition by user, sort by tour (tour-specific assignments)
- Small table (~15 users per tour)

# Data Model Details

## Identifier Formats

| Entity | Format | Example |
|--------|--------|---------|
| Profile ID | UUID | `550e8400-e29b-41d4-a716-446655440000` |
| Tour ID | TOUR + Year | `TOUR2026` |
| Rider ID | R + Number (no padding) | `R1`, `R57`, `R102` |
| Ride ID | RIDE + 3-digit padded | `RIDE001`, `RIDE008` |
| Stage ID | S + 3-digit padded | `S001`, `S002` |
| Check-In ID | UUID | `660e8400-e29b-41d4-a716-446655440000` |

## Check-In Status Derivation

Status is derived from flags, not stored directly:

| Condition | Status |
|-----------|--------|
| `isNotRiding = true` | NOT_RIDING |
| `isQuitRiding = true` | QUIT_RIDING |
| Both false/null | CHECKED_IN |

## Business Rules

1. **Not Riding:**
   - Only 1 check-in per rider per ride
   - `isNotRiding = true`
   - Created at Start stage before ride begins

2. **Quit Riding:**
   - Can have multiple check-ins (normal check-ins + final quit)
   - Latest check-in with `isQuitRiding = true` indicates quit status
   - Previous check-ins remain as normal (CHECKED_IN)

3. **Ride Status:**
   - PLANNED: Ride created but not started
   - ACTIVE: Ride in progress
   - COMPLETED: All riders finished
   - CLOSED: Locked, no more check-ins allowed

4. **Stage Numbering:**
   - Start: stageNumber = 1
   - Pit Stops: stageNumber = 2, 3, 4, ...
   - Finish: stageNumber = (total stages)

# Cost Optimization Strategies

Given the small data volume, costs will be minimal. However, following best practices:

## DynamoDB Optimization

1. **On-Demand Pricing:**
   - Recommended for this use case
   - No minimum capacity charges
   - Pay only for actual reads/writes
   - Expected cost: <$5/month during tour, <$1/month off-season

2. **Efficient Queries:**
   - Partition by tour to limit scan scope
   - Use GSIs for alternate access patterns
   - Batch operations where possible

3. **Data Retention:**
   - Keep 5 years of data as specified
   - Archive older data to S3 if needed (future)
   - No TTL needed for this use case

## API Gateway Optimization

1. **HTTP API vs REST API:**
   - ✅ Use HTTP API (already planned)
   - 70% cheaper than REST API
   - Sufficient for this use case

2. **Request Optimization:**
   - Batch read operations in single Lambda call
   - Return only needed fields
   - Use query parameters for filtering

3. **Caching:**
   - Not needed for this low-volume use case
   - Real-time data more important than caching

## Lambda Optimization

1. **Memory Configuration:**
   - Start with 512MB
   - Monitor and adjust based on actual usage
   - Lower memory = lower cost

2. **Connection Reuse:**
   - Reuse DynamoDB client across invocations
   - Use AWS SDK v3 for smaller bundle size

3. **Cold Start Optimization:**
   - Acceptable for this use case (<15 concurrent users)
   - Provisioned concurrency not needed

## S3 Optimization

1. **Storage Class:**
   - Standard class for rider photos
   - Infrequent access for old tour data

2. **Lifecycle Policies:**
   - Not critical for this volume
   - Consider after multiple years

## Expected Costs (Estimates)

**During Tour (7-8 days):**
- DynamoDB: $3-5
- API Gateway: $1-2  
- Lambda: $1-2
- S3: <$1
- **Total: ~$5-10/month**

**Off-Season:**
- DynamoDB: <$1
- API Gateway: <$0.50
- Lambda: <$0.50
- S3: <$1
- **Total: <$3/month**

**Annual estimate: $20-40/year** (well within free tier for most services)

# API Design

## API Structure

**Base URL:** `https://api.{domain}/v1`

**Authentication:** JWT tokens from Cognito User Pool

**Authorization:** Role-based access control (RBAC) enforced in Lambda

## Core Principles

1. **RESTful Design:** Standard HTTP methods and status codes
2. **Consistent Response Format:** All responses follow same structure
3. **Error Handling:** Descriptive error messages with proper status codes
4. **Versioning:** URI versioning (/v1/)
5. **Pagination:** For list operations (though not critical for this volume)

## Response Format

### Success Response
```json
{
  "success": true,
  "data": { ... },
  "timestamp": "2026-02-10T10:30:00Z"
}
```

### Error Response
```json
{
  "success": false,
  "error": {
    "code": "RIDER_NOT_FOUND",
    "message": "Rider R57 not found in tour TOUR2026"
  },
  "timestamp": "2026-02-10T10:30:00Z"
}
```

## API Endpoints

### Tours

#### Get Active Tour
```
GET /tours/active
Response: Tour object
```

#### Get Tour by ID
```
GET /tours/{tourId}
Response: Tour object
```

#### List Tours
```
GET /tours?year={year}&status={status}
Response: Array of Tour objects
```

### Riders

#### Get Rider Profile
```
GET /riders/profile/{profileId}
Response: RiderProfile object
```

#### Update Rider Profile
```
PUT /riders/profile/{profileId}
Body: RiderProfile fields
Response: Updated RiderProfile
```

#### Get Tour Riders
```
GET /tours/{tourId}/riders
Response: Array of TourRider objects with embedded profile data
```

#### Get Tour Rider by Rider ID
```
GET /tours/{tourId}/riders/{riderId}
Response: TourRider object with embedded profile data
```

### Rides

#### Get Today's Ride
```
GET /rides/today?tourId={tourId}
Response: Ride object with stages
```

#### Get Ride by ID
```
GET /rides/{rideId}
Response: Ride object with stages
```

#### List Rides
```
GET /tours/{tourId}/rides?date={date}&status={status}
Response: Array of Ride objects
```

#### Create Ride
```
POST /tours/{tourId}/rides
Body: Ride details with stages
Response: Created Ride object
Permissions: ADMINISTRATOR
```

#### Update Ride
```
PUT /rides/{rideId}
Body: Ride fields to update
Response: Updated Ride object
Permissions: ADMINISTRATOR
```

#### Close Ride
```
POST /rides/{rideId}/close
Response: Updated Ride object with CLOSED status
Permissions: ADMINISTRATOR
```

### Check-Ins

#### Create Check-In
```
POST /checkins
Body: {
  "riderId": "R57",
  "rideId": "RIDE001",
  "stageNumber": 2,
  "method": "QR_SCAN",
  "isNotRiding": false,
  "isQuitRiding": false,
  "notes": ""
}
Response: Created CheckIn object
Permissions: All except GUEST
```

#### Get Check-Ins for Ride
```
GET /rides/{rideId}/checkins
Response: Array of CheckIn objects
```

#### Get Check-Ins for Rider
```
GET /riders/{riderId}/checkins?rideId={rideId}
Response: Array of CheckIn objects
```

#### Get Dashboard Data
```
GET /rides/{rideId}/dashboard
Response: {
  "ride": Ride object,
  "riders": Array of TourRider with profiles,
  "checkIns": Array of CheckIn objects,
  "summary": {
    "totalRiders": 100,
    "checkedIn": 75,
    "notRiding": 5,
    "quitRiding": 2
  }
}
```

### Users

#### Get Current User Profile
```
GET /users/me
Response: User object
```

#### List Tour Users
```
GET /tours/{tourId}/users
Response: Array of User objects
Permissions: ADMINISTRATOR, SUPER_USER
```

## HTTP Status Codes

| Code | Usage |
|------|-------|
| 200 | Success (GET, PUT) |
| 201 | Created (POST) |
| 204 | No Content (DELETE) |
| 400 | Bad Request (validation errors) |
| 401 | Unauthorized (missing/invalid token) |
| 403 | Forbidden (insufficient permissions) |
| 404 | Not Found |
| 409 | Conflict (duplicate check-in) |
| 500 | Internal Server Error |

## Authorization Matrix

| Endpoint | Administrator | Super User | Pit Stop Crew | Hotel Staff | Guest |
|----------|--------------|------------|---------------|-------------|-------|
| GET tours | ✅ | ✅ | ✅ | ✅ | ✅ |
| GET riders | ✅ | ✅ | ✅ | ✅ | ✅ |
| GET rides | ✅ | ✅ | ✅ | ✅ | ✅ |
| GET dashboard | ✅ | ✅ | ✅ | ❌ | ✅ |
| POST check-in | ✅ | ✅ | ✅ | ✅ | ❌ |
| POST/PUT rides | ✅ | ❌ | ❌ | ❌ | ❌ |
| POST close ride | ✅ | ❌ | ❌ | ❌ | ❌ |
| Manual check-in | ✅ | ✅ | ❌ | ❌ | ❌ |

## Request Validation

All requests will be validated for:
1. **Authentication:** Valid JWT token
2. **Authorization:** User has required permission
3. **Input Validation:** Required fields present and valid format
4. **Business Rules:** Request doesn't violate business constraints

Example validations:
- Rider ID format: `R[1-999]`
- Tour ID format: `TOUR[YYYY]`
- Date format: ISO 8601 (YYYY-MM-DD)
- Check-in not allowed if ride is CLOSED
- No duplicate Not Riding check-ins
- Stage number must exist in ride

## Rate Limiting

Not critical for initial implementation given low volume, but consider:
- Per-user limits: 100 requests/minute
- API-wide limits: 1000 requests/minute
- Burst capacity: 200 requests

## API Development Phases

### Phase 1: Core Operations (MVP)
- ✅ Get today's ride
- ✅ Get tour riders
- ✅ Create check-in
- ✅ Get dashboard data
- ✅ Get rider by Rider ID

### Phase 2: Management
- Create/update rides
- Close ride
- User management

### Phase 3: Historical & Analytics
- Historical ride queries
- Check-in analytics
- Export to Excel

# Infrastructure as Code

## AWS SAM Template Structure

```yaml
tour-data-api/
├── template.yaml              # Main SAM template
├── samconfig.toml             # SAM CLI config
├── src/
│   ├── layers/
│   │   └── common/            # Shared utilities
│   ├── functions/
│   │   ├── tours/
│   │   ├── riders/
│   │   ├── rides/
│   │   ├── checkins/
│   │   └── users/
│   └── authorizer/            # JWT authorizer
└── events/                    # Test events
```

## Key Resources

1. **DynamoDB Tables:** All 6 tables with GSIs
2. **Lambda Functions:** One per endpoint group
3. **API Gateway:** HTTP API with JWT authorizer
4. **Cognito User Pool:** User authentication
5. **S3 Bucket:** Rider photos
6. **IAM Roles:** Lambda execution roles with least privilege
7. **CloudWatch Logs:** For monitoring and debugging

## Deployment Tags

All resources must be tagged:
```yaml
Tags:
  Project: tour-data-api
  Environment: dev|test|prod
  ManagedBy: SAM
  CostCenter: tour-management
```

# Security Considerations

## Authentication & Authorization

1. **JWT Validation:** All API requests validated via Cognito authorizer
2. **Token Expiration:** Access tokens expire in 1 hour
3. **Refresh Tokens:** Valid for 30 days
4. **Role-Based Access:** Enforced in Lambda functions

## Data Protection

1. **Encryption at Rest:** DynamoDB encryption enabled
2. **Encryption in Transit:** HTTPS only (TLS 1.2+)
3. **S3 Security:** Pre-signed URLs for photo access, bucket not public
4. **Secrets Management:** No credentials in code, use AWS Secrets Manager if needed

## API Security

1. **CORS:** Configured for specific origins only
2. **Input Validation:** All inputs sanitized and validated
3. **SQL Injection:** Not applicable (NoSQL)
4. **Rate Limiting:** Implemented to prevent abuse

## Audit Trail

1. **CloudWatch Logs:** All API calls logged
2. **Check-In Audit:** checkedInBy captured in every check-in
3. **Data Modifications:** createdAt/updatedAt timestamps on all records

# Monitoring & Logging

## CloudWatch Metrics

1. **API Gateway:**
   - Request count
   - Latency (p50, p95, p99)
   - 4xx/5xx errors

2. **Lambda:**
   - Invocations
   - Duration
   - Errors
   - Concurrent executions

3. **DynamoDB:**
   - Read/write capacity usage
   - Throttled requests
   - Consumed capacity

## CloudWatch Alarms

1. **High Error Rate:** >5% 5xx errors in 5 minutes
2. **High Latency:** p95 > 2 seconds
3. **Lambda Errors:** Any errors during check-in operations
4. **DynamoDB Throttling:** Any throttled requests

## Logging Strategy

1. **Structured Logs:** JSON format for easy parsing
2. **Log Levels:** DEBUG, INFO, WARN, ERROR
3. **Correlation IDs:** Track requests across services
4. **Log Retention:** 30 days for recent logs, archive to S3 for historical

# Testing Strategy

## Unit Tests

- Lambda function logic
- Data validation functions
- Business rule enforcement
- Authorization logic

## Integration Tests

- API endpoint tests
- DynamoDB operations
- Error handling
- Authorization flows

## Load Tests

- Not critical given low volume
- Baseline: 100 concurrent users
- Peak: 200 requests/minute

## Test Data

- Sample tour with 20 test riders
- Multiple rides with various stages
- Check-in scenarios (normal, NR, QR)
- Mock Cognito tokens for different roles

# Development Workflow

## Environment Strategy

1. **Dev:** Individual developer environments
2. **Test:** Shared testing environment
3. **Prod:** Production environment

## CI/CD Pipeline (GitHub Actions)

1. **On Pull Request:**
   - Run linters (pylint, flake8)
   - Run unit tests
   - Build SAM application
   - Run integration tests

2. **On Merge to Main:**
   - Deploy to test environment
   - Run smoke tests
   - Manual approval for prod
   - Deploy to prod
   - Run smoke tests

## Local Development

```bash
# Start local API
sam local start-api

# Invoke function locally
sam local invoke FunctionName -e events/event.json

# Run tests
pytest tests/
```

# Future Enhancements

## Phase 2 Features

1. **Real-time Updates:** WebSockets for live dashboard
2. **Notifications:** Push notifications for check-in events
3. **Photo Upload:** Direct upload from Check-In App
4. **Mobile Offline Sync:** Conflict resolution for offline check-ins

## Phase 3 Features

1. **Analytics Dashboard:** Ride statistics and trends
2. **Excel Export API:** Generate formatted Excel reports
3. **Rider App Integration:** Pre-registration and self-service
4. **Advanced Querying:** Complex filters and searching

## Scalability Considerations

If volume increases significantly (1000+ riders):
1. Consider single-table design for DynamoDB
2. Implement caching layer (ElastiCache)
3. Use DynamoDB Streams for real-time processing
4. Add read replicas for historical data

# Glossary

| Term | Definition |
|------|------------|
| Tour | Yearly cycling tour event |
| Ride | Single day's cycling route |
| Stage | Checkpoint in a ride (Start, Pit Stop, Finish) |
| Rider ID | Tour-specific identifier (R1, R2, etc.) |
| Profile ID | Persistent rider identifier (UUID) |
| Check-In | Recording a rider at a stage |
| Not Riding (NR) | Rider not participating in a specific ride |
| Quit Riding (QR) | Rider stopping mid-ride |
| QR Code | Quick Response code for rider identification |