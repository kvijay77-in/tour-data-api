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
   - Get all check-ins for a rider (tour scope)
   - Update check-in status (Not Riding, Quit Riding)
   - Cancel check-in (special update of cancellation metadata)
   - Cancelled check-ins are excluded from subsequent validation and read APIs, except dashboard progress where they are returned separately as a `cancelled` list

3. **Ride Management**
   - Get all rides for a tour
   - Get ride by ID
   - Create/update ride details
   - Update ride status (Active/Closed)

4. **Rider Management**
   - Get rider profile by Profile ID
   - Get rider profile by Rider ID (requires TourRider lookup)
   - Get all tour riders for a specific tour
   - Get lightweight rider list (riderId + name) for a specific tour
   - Exit rider from tour (`status=EXITED` with `prevStatus`, `exitedAt`, `exitedBy`)
   - Cancel rider exit (restore `status` from `prevStatus` and remove exit metadata)

5. **Historical Data**
   - Query rides by date range
   - Get historical check-in data

6. **User Authentication**
   - Get user profile for authorization
   - Validate user permissions

# DynamoDB Table Design

## Table Strategy: Shared + Tour-Specific Tables

The system uses a **hybrid table strategy** where platform-level data resides in shared tables managed via SAM, and tour-specific operational data resides in tables dynamically created per tour at runtime.

### Shared Tables (Managed by SAM/CloudFormation)

These tables exist for the lifetime of the deployment and are defined in `template.yaml`:

| Table | Purpose |
|---|---|
| **RiderProfile** | Master rider data, tour-agnostic |
| **RiderCognitoUser** | Mapping between Cognito rider username and generated rider profile ID |
| **TourMaster** | Tour registry — every tour ever created is listed here |
| **AppConfig** | Shared platform configuration for app clients |

### Tour-Specific Tables (Provisioned at Runtime)

These tables are created dynamically when a tour admin provisions a new tour, and can be archived/deleted when a tour is completed:

| Table | Purpose |
|---|---|
| **TourRider-{tourId}** | Rider enrollment for the specific tour |
| **Ride-{tourId}** | Daily ride configurations for the specific tour |
| **CheckIn-{tourId}** | Check-in records for the specific tour |
| **User-{tourId}** | Admin/staff user assignments for the specific tour |
| **Notification-{tourId}** | Notifications for tour riders (announcements, alerts, personal messages) |

### Table Naming Convention

All tables follow the pattern: `{AWS::StackName}-{TableType}` for shared tables and `{AWS::StackName}-{TableType}-{tourId}` for tour-specific tables.

Examples (stack name: `dev`, tour ID: `TOT-2026`):
- Shared: `dev-RiderProfile`, `dev-RiderCognitoUser`, `dev-TourMaster`, `dev-AppConfig`
- Tour-specific: `dev-TourRider-TOT-2026`, `dev-Ride-TOT-2026`, `dev-CheckIn-TOT-2026`, `dev-User-TOT-2026`, `dev-Notification-TOT-2026`

Lambda functions resolve shared table names via environment variables (set by SAM) and tour-specific table names at runtime using a naming convention. The stack name is available to Lambda via the `STACK_NAME` environment variable.

### Tour Lifecycle and Table Management

1. **Provisioning:** Tour-specific tables are created when a new tour is provisioned. Two methods are available:
   - **CLI Script (Deployment Method):** `scripts/provision_tour.py` or `make provision-tour` — runs locally or in CI/CD pipelines, creates Tour record + 4 tables via boto3 directly
   - **API Endpoint (Runtime Method):** `POST /v1/tours` — used by external apps (e.g., Check-In App) to create tours programmatically. The actual integration from external apps is out of scope for this project; this API capability is provided for their use.
2. **Active use:** Lambda functions resolve tour-specific table names using `{STACK_NAME}-{TableType}-{tourId}`
3. **Archival:** Tour admin archives a completed tour → data can be exported to S3 → tour-specific tables can be deleted
4. **De-provisioning:** For one-off usage, the operator can delete tour tables or the entire stack

Both provisioning methods create the same resources: a Tour record in the shared TourMaster table and 5 tour-specific DynamoDB tables (TourRider, Ride, CheckIn, User, Notification) with identical schemas and configurations. The shared provisioning logic resides in `src/layers/common/tour_provisioning.py`.

### Key Design Benefits

- **Clean isolation:** Each tour's operational data is fully contained in its own tables
- **Simple archival:** Delete or export entire tour tables — no item-level filtering needed
- **No cross-tour interference:** Queries never touch other tours' data
- **Product-ready:** Supports multiple concurrent tours, sequential tours, or one-off tours
- **Simplified key design:** Tour-specific tables don't need tour prefixes in partition keys since the table itself is tour-scoped

---

## Shared Table 1: RiderProfile

**Purpose:** Master rider data, tour-agnostic

| Attribute | Type | Description |
|-----------|------|-------------|
| profileId | String | UUID (partition key) |
| name | String | Rider's full name |
| email | String | Email address |
| personalCode | String | Optional rider personal code (uppercase, globally unique when present) |
| phone | String | Contact number |
| emergencyContact | Map | Emergency contact map with string fields `name`, `phone`, `relation` |
| address | Map | Optional address map with string fields `Line 1`, `Line 2`, `City`, `State`, `Postal Code` |
| dateOfBirth | String | Optional ISO date (`YYYY-MM-DD`) |
| gender | String | Optional one of `Male`, `Female`, `Other`, `Prefer not to say` |
| photoS3Key | String | S3 object key for photo |
| createdAt | String | ISO 8601 timestamp |
| updatedAt | String | ISO 8601 timestamp |

**Indexes:**
- Primary Key: `profileId` (partition key only)
- GSI1: `email` (partition key) - For email lookup
- GSI2: `personalCode` (partition key) - For case-insensitive uniqueness and lookup

**Notes:**
- Small table (~200-500 profiles over time)
- Simple key-value lookups by profile ID
- Photo stored in S3, only reference stored here

## Shared Table 2: RiderCognitoUser

**Purpose:** Maintains the relationship between rider Cognito username and rider profile ID.

| Attribute | Type | Description |
|-----------|------|-------------|
| cognitoUserName | String | Cognito username (partition key) |
| profileId | String | Auto-generated UUID for rider profile mapping |

**Indexes:**
- Primary Key: `cognitoUserName` (partition key only)

**Notes:**
- One item per Cognito username
- Used by rider-app link API (`GET`/`POST`/`DELETE /v1/riders/link/{cognitoUserName}`)

## Shared Table 3: TourMaster

**Purpose:** Tour registry — master record for every tour ever created

| Attribute | Type | Description |
|-----------|------|-------------|
| tourId | String | Free-form unique identifier (e.g., `TOT-2026`, `TDF2026`, `charity-ride-01`) (partition key) |
| name | String | Tour name |
| startDate | String | ISO 8601 date |
| endDate | String | ISO 8601 date |
| status | String | PLANNING, PROVISIONING, ACTIVE, COMPLETED, ARCHIVED |
| description | String | Tour description |
| provisionedAt | String | ISO 8601 timestamp (when tour tables were created) |
| archivedAt | String | ISO 8601 timestamp (when tour was archived) |
| createdAt | String | ISO 8601 timestamp |
| updatedAt | String | ISO 8601 timestamp |

**Indexes:**
- Primary Key: `tourId` (partition key only)
- GSI1: `status` (partition key) - For querying tours by status (e.g., find active tour)

**Notes:**
- Small table — grows by number of tours created over the deployment's lifetime
- `tourId` is free-form, set by tour admin at creation time
- `tourId` must be unique and valid as a DynamoDB table name suffix (allowed chars: `a-zA-Z0-9_.-`, 3-50 chars, must start with letter or number)
- `PROVISIONING` status indicates tour tables are being created
- `ARCHIVED` status indicates tour data has been exported and/or tour-specific tables deleted
- Status flow: PLANNING → PROVISIONING → ACTIVE → COMPLETED → ARCHIVED

## Shared Table 4: AppConfig

**Purpose:** Shared read-mostly app configuration values used by multiple clients.

| Attribute | Type | Description |
|-----------|------|-------------|
| configType | String | Config partition type (partition key) |
| configId | String | Config identifier within a type (sort key) |
| enabled | Boolean | Active marker |
| config | Map | Config payload |
| description | String | Human-readable note |
| version | Number | Incremented on updates |
| updatedAt | String | ISO 8601 timestamp |
| updatedBy | String | Actor identifier |

**Indexes:**
- Primary Key: `configType` (partition key), `configId` (sort key)

**Notes:**
- API readers consume enabled entries only.
- Current supported config types: `ID_CODE_FORMAT`, `ID_CODE_TYPE`.

## Tour-Specific Table 1: TourRider-{tourId}

**Purpose:** Rider registration for a specific tour. One table per tour, created at provisioning time.

| Attribute | Type | Description |
|-----------|------|-------------|
| riderId | String | Tour-specific rider ID (R1, R2, etc.) (partition key) |
| profileId | String | Reference to RiderProfile |
| registeredAt | String | ISO 8601 timestamp |
| qrCodeData | String | Encoded QR code data (currently just riderId) |
| status | String | PENDING, REGISTERED, ACTIVE, WITHDRAWN, EXITED |
| prevStatus | String | Previous status captured when rider is marked EXITED |
| exitedAt | String | ISO 8601 timestamp when rider was marked EXITED |
| exitedBy | String | Cognito `sub` of actor who marked rider as EXITED |
| createdAt | String | ISO 8601 timestamp |
| updatedAt | String | ISO 8601 timestamp |

**Indexes:**
- Primary Key: `riderId` (partition key only)
- GSI1: `profileId` (partition key) - For profile-based lookup

**Notes:**
- Table is tour-scoped — no need for tourId in keys
- Max ~100 items per table (one tour's riders)
- GSI1 for looking up rider enrollment by profile ID
- `riderId` lookup is a direct get_item on partition key

## Tour-Specific Table 2: Ride-{tourId}

**Purpose:** Daily ride configurations for a specific tour. One table per tour, created at provisioning time.

| Attribute | Type | Description |
|-----------|------|-------------|
| rideId | String | Unique ride identifier (e.g., RIDE001) (partition key) |
| date | String | ISO 8601 date (YYYY-MM-DD) |
| rideNo | Number | Sequence number for the day |
| name | String | Short name (e.g., Day1, Day2) |
| startLocation | String | Starting place |
| finishLocation | String | Finishing place |
| description | String | Optional description |
| totalDistance | Number | Distance in km |
| openTime | String | Planned ride opening time for start / not-riding check-ins |
| flagOffTime | String | Planned flag-off time |
| closeTime | String | Planned ride closing time |
| status | String | OPEN, STARTED, PLANNED, ACTIVE, COMPLETED, CLOSED |
| stages | List | Array of stage objects (see below) |
| floats | List | Optional array of float objects (see below) |
| createdAt | String | ISO 8601 timestamp |
| updatedAt | String | ISO 8601 timestamp |
| openedAt | String | Ride open timestamp |
| startedAt | String | Actual start timestamp |
| completedAt | String | Completion timestamp |
| closedAt | String | Closed/locked timestamp |

**Stage Object Structure (embedded in stages array):**
```json
{
   "stageId": "S000",
   "stageNumber": 0,
  "type": "START|PIT_STOP|FINISH",
  "name": "Start|PS1|PS2|Finish",
  "location": "Location name",
  "distanceFromStart": 0,
   "estimatedOpenTime": 90,
   "pitStopDuration": 45,
   "pitStopStatus": "OPEN|CLOSED",
   "openedAt": "2026-02-11T09:30:00Z",
   "closedAt": "2026-02-11T10:15:00Z"
}
```

**Float Object Structure (embedded in floats array):**
```json
{
   "floatNo": 1,
   "floatToStage": 1
}
```

Notes:
- `estimatedOpenTime` and `pitStopDuration` apply only to `PIT_STOP` stages.
- `pitStopStatus`, `openedAt`, and `closedAt` are runtime-managed and remain empty when a ride is created.
- `estimatedTimeFromStart` is removed from the stage contract.
- `floats` is optional; when present, each `floatNo` must be unique and each `floatToStage` must refer to a non-start stage number in the ride.

**Indexes:**
- Primary Key: `rideId` (partition key only)
- GSI1: `date` (partition key) - For date-based lookup (today's ride)
- GSI2: `status` (partition key), `date` (sort key) - For querying active/completed rides

**Notes:**
- Table is tour-scoped — no need for tourId in keys
- Stages embedded as array (max ~5-6 stages per ride)
- GSI1 critical for "get today's ride" query
- Max ~8 rides per tour table

## Tour-Specific Table 3: CheckIn-{tourId}

**Purpose:** Check-in records for all riders across stages for a specific tour. One table per tour, created at provisioning time.

| Attribute | Type | Description |
|-----------|------|-------------|
| rideId | String | Ride ID (partition key) |
| checkInId | String | `<riderId>#<stageNumber>#<timestamp>` (sort key) |
| riderId | String | Rider ID |
| stageNumber | Number | Stage number (0-based) |
| stageId | String | Stage ID reference |
| timestamp | String | ISO 8601 timestamp of check-in |
| checkedInBy | String | User ID who performed check-in |
| method | String | QR_SCAN, MANUAL, FALLBACK |
| isNotRiding | Boolean | True if Not Riding |
| isFloat | Boolean | True if Float check-in |
| floatNo | Number | Float number when isFloat is true |
| isQuitRiding | Boolean | True if Quit Riding |
| isManualEntry | Boolean | True if manual entry |
| notes | String | Optional notes |
| location | Map | {latitude: Number, longitude: Number} (optional) |
| prevStatus | String | Previous status supplied when a check-in is cancelled |
| cancelledBy | String | User ID who cancelled the check-in |
| cancelledAt | String | ISO 8601 timestamp when cancelled |
| createdAt | String | ISO 8601 timestamp |

**Indexes:**
- Primary Key: `rideId` (partition key), `checkInId` (sort key)
- GSI1: `riderId` (partition key), `timestamp` (sort key) - For rider history within the tour

**Notes:**
- Table is tour-scoped — no need for tourId in keys or GSIs
- Partition by ride for efficient dashboard queries
- All check-ins for a ride retrieved in single query
- Sort key design allows sorting by rider, then stage, then time
- Max ~600 items per partition (100 riders × 6 stages)
- GSI1 for rider-specific check-in history within this tour

## Tour-Specific Table 4: User-{tourId}

**Purpose:** User profile and role assignments for a specific tour. One table per tour, created at provisioning time. Only created if Cognito data is insufficient.

| Attribute | Type | Description |
|-----------|------|-------------|
| userId | String | Cognito user sub (partition key) |
| username | String | Username |
| email | String | Email |
| name | String | Full name |
| role | String | ADMINISTRATOR, SUPER_USER, HOTEL_STAFF, GUEST, RIDER, or PS_<n>_USER |
| assignedStage | Number | Optional display metadata for pit stop users; authorization is enforced from Cognito groups + request stage |
| status | String | ACTIVE, INACTIVE, SUSPENDED |
| createdAt | String | ISO 8601 timestamp |
| updatedAt | String | ISO 8601 timestamp |

**Indexes:**
- Primary Key: `userId` (partition key only)
- GSI1: `email` (partition key) - For email lookup

**Notes:**
- Table is tour-scoped — no need for tourId in keys
- Small table (~15 users per tour)
- Each tour has its own user assignments (team composition can change between tours)

## Tour-Specific Table 5: Notification-{tourId}

**Purpose:** Notifications sent to tour riders by organizers. Includes announcements, ride updates, safety alerts, and personal messages. One table per tour, created at provisioning time.

| Attribute | Type | Description |
|-----------|------|-------------|
| notificationId | String | UUID (partition key) |
| type | String | TOUR_ANNOUNCEMENT, RIDE_UPDATE, SAFETY_ALERT, PERSONAL_MESSAGE, CHECKIN_REMINDER, REGISTRATION_STATUS |
| title | String | Notification title |
| message | String | Notification content |
| createdBy | String | Cognito user sub of creator |
| targetRiderId | String | Optional: rider ID for personal notifications. Omitted for broadcast notifications |
| readBy | List | List of profileIds who have read the notification |
| createdAt | String | ISO 8601 timestamp |
| expiresAt | String | Optional: ISO 8601 expiry timestamp |

**Indexes:**
- Primary Key: `notificationId` (partition key only)
- GSI1: `type` (partition key) + `createdAt` (sort key) - For type-filtered queries sorted by date

# Data Model Details

## Identifier Formats

| Entity | Format | Example |
|--------|--------|---------|
| Profile ID | UUID | `550e8400-e29b-41d4-a716-446655440000` |
| Tour ID | Free-form (configurable by tour admin) | `TOT-2026`, `TDF2026`, `charity-ride-01` |
| Rider ID | R + Number (no padding) | `R1`, `R57`, `R102` |
| Ride ID | RIDE + 3-digit padded | `RIDE001`, `RIDE008` |
| Stage ID | S + 3-digit padded | `S000`, `S001` |
| Check-In ID | UUID | `660e8400-e29b-41d4-a716-446655440000` |
| Notification ID | UUID | `770e8400-e29b-41d4-a716-446655440000` |

### Tour ID Rules

The `tourId` is a free-form identifier set by the tour administrator at tour creation time. It must satisfy the following rules since it becomes part of DynamoDB table names:

| Rule | Detail |
|------|--------|
| Allowed characters | `a-z`, `A-Z`, `0-9`, `_`, `-`, `.` |
| Length | 3–50 characters |
| Must start with | A letter or number |
| Uniqueness | Must be unique across all tours in the deployment |
| Case-sensitive | `Tour2026` and `tour2026` are different |

Examples of valid Tour IDs: `TOT-2026`, `TDF2026`, `summer-ride-2026.01`, `2026-charity-ride`, `test-tour-01`

## Check-In Status Derivation

Status is derived from flags, not stored directly:

| Condition | Status |
|-----------|--------|
| `isFloat = true` | FLOAT |
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
   - **Offline sync:** If client provides a `timestamp` that predates the quit-riding record, the check-in is accepted (captured before rider quit)

3. **Ride Status:**
   - PLANNED: Ride created but not started
   - OPEN: Ride opened for start / not-riding check-ins
   - STARTED: Ride flagged off and pit-stop opening time becomes relative to `startedAt` when available
   - ACTIVE: Ride in progress
   - COMPLETED: All riders finished
   - CLOSED: Locked, no more check-ins allowed
   - **Late-sync for closed rides:** If client provides a `timestamp` that predates the `closedAt` value, the check-in is accepted (captured before ride was closed)

4. **Pit Stop Window Management:**
   - Only `PIT_STOP` stages support pit-stop open and close operations.
   - Stage `pitStopStatus` transitions from empty to `OPEN` to `CLOSED`.
   - Pit-stop open/close operations are permitted only while ride status is `STARTED`.
   - Opening a pit stop stamps the stage `openedAt` time and closing it stamps `closedAt`.

4. **Duplicate Check-In Detection:**
   - Same rider + same stage (normal check-ins only) returns 409 with `DUPLICATE_CHECKIN`
   - Not Riding and Quit Riding check-ins are exempt from this check

4. **Stage Numbering:**
   - Start: stageNumber = 0
   - Pit Stops: stageNumber = 1, 2, 3, ...
   - Finish: stageNumber = (total stages - 1)

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
   - Archival is per-tour: export tour-specific tables to S3 and delete
   - Shared tables (RiderProfile, RiderCognitoUser, TourMaster) persist for deployment lifetime
   - No TTL needed — tour table deletion handles cleanup

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

Detailed API contracts, endpoint validations, status/error behavior, and RBAC matrix are documented in [API Guide](api-guide.md).

This section was intentionally moved out to keep this solution-design document focused on architecture and data-model decisions.

# Infrastructure as Code

## AWS SAM Template Structure

```yaml
tour-data-api/
├── template.yaml              # Main SAM template
├── samconfig.toml             # SAM CLI config
├── src/
│   ├── layers/
│   │   └── common/            # Shared utilities
│   └── functions/
│       ├── tours/
│       ├── riders/
│       ├── rides/
│       ├── checkins/
│       └── users/
└── events/                    # Test events
```

## Key Resources

### Managed by SAM (template.yaml)
1. **Shared DynamoDB Tables:** RiderProfile, RiderCognitoUser, TourMaster (with GSIs where applicable)
2. **Lambda Functions:** One per API endpoint
3. **Lambda Layer:** Common utilities shared across all functions (`dynamodb_utils`, `logger`, `models`, `rbac`, `response`, `tour_provisioning`, `validation`)
4. **API Gateway (tour-mgmt-app):** HTTP API (`TourDataApi`) with JWT authorizer for the management User Pool
5. **API Gateway (tour-rider-app):** HTTP API (`RiderApi`) with JWT authorizer for the rider User Pool — exposes rider-facing endpoints
6. **Cognito User Pool (tour-mgmt-app):** `{stack}-users` — for tour organizers, pit stop users, hotel staff, guests. Groups: `ADMINISTRATOR`, `SUPER_USER`, `PS_1_USER`, `PS_2_USER`, `PS_3_USER`, `PS_4_USER`, `PS_5_USER`, `HOTEL_STAFF`, `GUEST`
7. **Cognito User Pool (tour-rider-app):** `{stack}-rider-users` — dedicated pool for riders, isolated from management users. Groups: `RIDER`. A person can exist in both pools with separate identities.
8. **S3 Bucket:** Rider photos
9. **IAM Roles:** Lambda execution roles with least privilege
10. **CloudWatch Logs:** For monitoring and debugging

### Managed at Runtime (Tour Provisioning)
1. **Tour-Specific DynamoDB Tables:** TourRider-{tourId}, Ride-{tourId}, CheckIn-{tourId}, User-{tourId}, Notification-{tourId} (with GSIs)
2. Created by the shared tour provisioning utility (`src/layers/common/tour_provisioning.py`) via boto3
3. Follow the same naming convention, tagging, and billing mode as SAM-managed tables

### Tour Provisioning

Tour-specific tables can be created through two methods:

**Method 1: CLI Script (Deployment Method)**

For use during initial setup, CI/CD pipelines, or by operators:
1. Run `make provision-tour` or `python scripts/provision_tour.py` with tour parameters
2. Script resolves the TourMaster table name from CloudFormation stack outputs
3. Creates a Tour record in the shared TourMaster table (status: PROVISIONING)
4. Creates 5 DynamoDB tables: `{STACK_NAME}-TourRider-{tourId}`, `{STACK_NAME}-Ride-{tourId}`, `{STACK_NAME}-CheckIn-{tourId}`, `{STACK_NAME}-User-{tourId}`, `{STACK_NAME}-Notification-{tourId}`
5. Tables are created with on-demand billing, encryption, and standard tags
6. Once all tables are active, Tour status is updated to PLANNING

**Method 2: API Endpoint (Runtime Method)**

For use by external applications (e.g., Check-In App):
1. **POST /tours** → Creates a Tour record in the shared TourMaster table (status: PROVISIONING)
2. Lambda creates 5 DynamoDB tables using the same shared provisioning logic
3. Tables are created with on-demand billing, encryption, and standard tags
4. Once all tables are active, Tour status is updated to PLANNING
5. The provisioning Lambda requires `dynamodb:CreateTable`, `dynamodb:DescribeTable`, and `dynamodb:TagResource` permissions

> **Note:** The API method is provided for external app integration (e.g., Check-In App creating new tours). The actual integration from these external apps is out of scope for this project.

Both methods use the same provisioning logic from `src/layers/common/tour_provisioning.py`, ensuring identical table schemas and configurations.

When a tour admin archives a tour:
1. **POST /tours/{tourId}/archive** → Optionally exports data to S3, then deletes tour-specific tables
2. Tour status updated to ARCHIVED in the shared TourMaster table
3. The de-provisioning Lambda requires `dynamodb:DeleteTable` and optionally `dynamodb:ExportTableToPointInTime` permissions

## Deployment Tags

All resources must be tagged:
```yaml
Tags:
  Project: tour-data-api
  Environment: dev|test|prod
  ManagedBy: SAM          # For SAM-managed resources
  ManagedBy: Lambda        # For runtime-provisioned tour tables
  SubscriptionId: <value>  # Unique identifier for this deployment/subscription
  CostCenter: tour-management
```

### SubscriptionId

A `SubscriptionId` parameter is included in the SAM template as a deployment-level tag. It uniquely identifies this deployment instance and is used exclusively for tracking and cost attribution — not for resource naming or data isolation (each deployment is in its own AWS account).

Configured in `samconfig.toml`:
```toml
parameter_overrides = "Environment=dev SubscriptionId=client-abc-123"
```

Runtime-provisioned tour tables must also be tagged with the same `SubscriptionId` value, available to Lambda via the `SUBSCRIPTION_ID` environment variable.

# Security Considerations

## Authentication & Authorization

1. **JWT Validation:** All API requests validated via Cognito authorizer
2. **Token Expiration:** Access tokens expire in 1 hour
3. **Refresh Tokens:** Valid for 30 days
4. **Permission-Based RBAC:** Enforced in Lambda functions via `src/layers/common/rbac.py`

### RBAC Design

Lambda handlers check API-level **permissions** (what action is being performed) rather than Cognito group names (who the caller is). Standard groups are mapped through `GROUP_PERMISSIONS` in `rbac.py`, while pit stop groups are resolved dynamically from the `PS_<stage>_USER` naming pattern. This allows additional pit stop groups to be introduced without changing backend code.

When a user has multiple roles, permission resolution uses a single effective role with priority `ADMINISTRATOR` > `SUPER_USER` > first `PS_<n>_USER` in claim order > `HOTEL_STAFF` > `GUEST`. If none of these roles are present, the legacy union of mapped non-priority groups continues to apply. This keeps role behavior deterministic while preserving compatibility for other role combinations.

For regular check-ins, pit stop access is stage-aware. A user with `PS_1_USER` may create a normal check-in only for stage `1` when that ride stage type is `PIT_STOP`; `PS_2_USER` behaves the same for stage `2`, and so on. `START` is always stage `0`, the last stage is always `FINISH`, and pit stop roles must never authorize regular check-ins for `START` or `FINISH`. A user may belong to multiple pit stop groups, and any `PS_<n>_USER` role may still create `Quit Riding` check-ins.

**Permissions and group mapping:**

| Permission | ADMINISTRATOR | SUPER_USER | PS_<n>_USER | HOTEL_STAFF | GUEST | RIDER |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| READ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| CHECKIN | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| CHECKIN_MANUAL | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| RIDE_MANAGE | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| PIT_STOP_MANAGE | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| TOUR_MANAGE | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| USER_LIST | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ |
| DASHBOARD | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ |

API Gateway HTTP API serialises the `cognito:groups` claim as a comma-separated string when forwarding it to Lambda — this is handled transparently by `rbac.get_user_groups()`.

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

If volume increases significantly (1000+ riders or many concurrent tours):
1. Consider caching layer (ElastiCache) for frequently accessed data
2. Use DynamoDB Streams for real-time processing
3. Add read replicas for historical data
4. The tour-specific table strategy already scales naturally — each tour's tables are independent

# Glossary

| Term | Definition |
|------|------------|
| Tour | A cycling tour event (can occur at any frequency, not limited to yearly) |
| Tour ID | Free-form unique identifier for a tour, set by tour admin |
| Ride | Single day's cycling route |
| Stage | Checkpoint in a ride (Start, Pit Stop, Finish) |
| Rider ID | Tour-specific identifier (R1, R2, etc.) |
| Profile ID | Persistent rider identifier (UUID) |
| Check-In | Recording a rider at a stage |
| Not Riding (NR) | Rider not participating in a specific ride |
| Quit Riding (QR) | Rider stopping mid-ride |
| QR Code | Quick Response code for rider identification |