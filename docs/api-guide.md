# API Guide

[← Back to Solution Design](SolutionDesign.md)

This document contains detailed API design, endpoint contracts, validations, and authorization rules for the Tour Data API.

## API Structure

**Base URL:** `https://api.{domain}`

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
    "message": "Rider R57 not found in tour TOT-2026"
  },
  "timestamp": "2026-02-10T10:30:00Z"
}
```

## API Endpoints

All routes below are shown with the deployed API version prefix (`/v1`).

### Endpoint Catalog

| Domain | Method | Path | Purpose | Contract |
|---|---|---|---|---|
| Tours | GET | `/v1/tours/active` | Get currently active tour | [Tours](#tours) |
| Tours | GET | `/v1/tours/{tourId}` | Get tour details | [Tours](#tours) |
| Tours | GET | `/v1/tours` | List tours | [Tours](#tours) |
| Tours | POST | `/v1/tours` | Create and provision tour | [Tours](#tours) |
| Tours | POST | `/v1/tours/{tourId}/archive` | Archive tour | [Tours](#tours) |
| Riders | POST | `/v1/riders/profile` | Create rider profile | [Riders](#riders) |
| Riders | GET | `/v1/riders/profile/{profileId}` | Get rider profile | [Riders](#riders) |
| Riders | PUT | `/v1/riders/profile/{profileId}` | Update rider profile | [Riders](#riders) |
| Riders | POST | `/v1/riders/profile/{profileId}/picture` | Get profile picture upload URL | [Riders](#riders) |
| Riders | GET | `/v1/tours/{tourId}/riders` | List tour riders | [Riders](#riders) |
| Riders | POST | `/v1/tours/{tourId}/riders` | Register rider for tour | [Riders](#riders) |
| Riders | GET | `/v1/tours/{tourId}/riders/{riderId}` | Get tour rider | [Riders](#riders) |
| Riders | GET | `/v1/tours/{tourId}/riders/{riderId}/statistics` | Get rider statistics | [Riders](#riders) |
| Rides | GET | `/v1/tours/{tourId}/rides/today` | Get today's ride | [Rides](#rides) |
| Rides | GET | `/v1/tours/{tourId}/rides` | List rides | [Rides](#rides) |
| Rides | GET | `/v1/tours/{tourId}/rides/{rideId}` | Get ride | [Rides](#rides) |
| Rides | POST | `/v1/tours/{tourId}/rides` | Create ride | [Rides](#rides) |
| Rides | PUT | `/v1/tours/{tourId}/rides/{rideId}` | Update ride | [Rides](#rides) |
| Rides | POST | `/v1/tours/{tourId}/rides/open` | Open today's ride | [Rides](#rides) |
| Rides | POST | `/v1/tours/{tourId}/rides/start` | Start today's ride | [Rides](#rides) |
| Rides | POST | `/v1/tours/{tourId}/rides/{rideId}/close` | Close ride | [Rides](#rides) |
| Check-Ins | POST | `/v1/tours/{tourId}/checkins` | Create check-in | [Check-Ins](#check-ins) |
| Check-Ins | GET | `/v1/tours/{tourId}/rides/{rideId}/checkins` | List ride check-ins | [Check-Ins](#check-ins) |
| Check-Ins | GET | `/v1/tours/{tourId}/rides/{rideId}/dashboard` | Get dashboard payload | [Check-Ins](#check-ins) |
| Users | GET | `/v1/users/me` | Get current user claims | [Users](#users) |
| Users | GET | `/v1/tours/{tourId}/users` | List tour users | [Users](#users) |
| Admin UserMgmt | GET | `/v1/admin/usermgmt/roles` | List assignable Cognito groups | [Admin User Management](#admin-user-management) |
| Admin UserMgmt | GET | `/v1/admin/usermgmt/users` | List Cognito users with roles | [Admin User Management](#admin-user-management) |
| Admin UserMgmt | POST | `/v1/admin/usermgmt/users` | Create Cognito user and assign roles | [Admin User Management](#admin-user-management) |
| Admin UserMgmt | POST | `/v1/admin/usermgmt/users/{cognitoUserId}/enable` | Enable Cognito user | [Admin User Management](#admin-user-management) |
| Admin UserMgmt | POST | `/v1/admin/usermgmt/users/{cognitoUserId}/disable` | Disable Cognito user | [Admin User Management](#admin-user-management) |
| Admin UserMgmt | DELETE | `/v1/admin/usermgmt/users/{cognitoUserId}` | Delete Cognito user | [Admin User Management](#admin-user-management) |
| Admin UserMgmt | PUT | `/v1/admin/usermgmt/users/{cognitoUserId}` | Update Cognito profile and roles | [Admin User Management](#admin-user-management) |
| Notifications | GET | `/v1/tours/{tourId}/notifications` | List notifications | [Notifications](#notifications) |
| Notifications | POST | `/v1/tours/{tourId}/notifications` | Create notification | [Notifications](#notifications) |
| Notifications | PUT | `/v1/tours/{tourId}/notifications/{notificationId}` | Mark notification as read | [Notifications](#notifications) |

### Request Contract Tables

#### Tours

| Endpoint | Path Params | Query Params | Body Attributes | Validation / Business Rules |
|---|---|---|---|---|
| `GET /v1/tours/active` | None | None | None | No body required |
| `GET /v1/tours/{tourId}` | `tourId` (required) | None | None | `tourId`: 3-50 chars, starts with letter/number, allowed `[a-zA-Z0-9_.-]` |
| `GET /v1/tours` | None | `status` (optional) | None | `status` in `PLANNING, PROVISIONING, ACTIVE, COMPLETED, ARCHIVED` |
| `POST /v1/tours` | None | None | Required: `tourId, name, startDate, endDate`; Optional: `description` | `tourId` format + uniqueness; dates `YYYY-MM-DD`; `endDate >= startDate`; provisions 5 tour tables |
| `POST /v1/tours/{tourId}/archive` | `tourId` (required) | `exportToS3` (optional, default true), `deleteTables` (optional, default true) | None | Tour exists; status must be `ACTIVE` or `COMPLETED`; ARCHIVED cannot be archived again |

#### Riders

| Endpoint | Path Params | Query Params | Body Attributes | Validation / Business Rules |
|---|---|---|---|---|
| `POST /v1/riders/profile` | None | None | Required: `name, email, phone, emergencyContactName, emergencyContactPhone`; Optional: `dateOfBirth, gender, address` | Email format; duplicate email rejected (`EMAIL_ALREADY_EXISTS`) |
| `GET /v1/riders/profile/{profileId}` | `profileId` (required) | None | None | `profileId` must exist |
| `PUT /v1/riders/profile/{profileId}` | `profileId` (required) | None | At least one of: `name, email, phone, emergencyContactName, emergencyContactPhone, photoS3Key` | Email validated when provided |
| `POST /v1/riders/profile/{profileId}/picture` | `profileId` (required) | None | Optional: `contentType` | `profileId` must exist; `contentType` in `image/jpeg, image/png`; default `image/jpeg` |
| `GET /v1/tours/{tourId}/riders` | `tourId` (required) | None | None | `tourId` format rule |
| `POST /v1/tours/{tourId}/riders` | `tourId` (required) | None | Required: `profileId`; Optional: `riderId, experienceLevel, medicalConditions, specialRequirements` | Tour exists with status `PLANNING/ACTIVE`; profile exists; duplicate profile registration rejected (`ALREADY_REGISTERED`); generates temp riderId if omitted |
| `GET /v1/tours/{tourId}/riders/{riderId}` | `tourId, riderId` (required) | None | None | `tourId` format; `riderId` format `R1..R999` |
| `GET /v1/tours/{tourId}/riders/{riderId}/statistics` | `tourId, riderId` (required) | None | None | `tourId` + `riderId` format rules; rider must exist in tour |

#### Rides

| Endpoint | Path Params | Query Params | Body Attributes | Validation / Business Rules |
|---|---|---|---|---|
| `GET /v1/tours/{tourId}/rides/today` | `tourId` (required) | None | None | `tourId` format; 404 `NO_ACTIVE_RIDE` when no ride for current UTC date |
| `GET /v1/tours/{tourId}/rides` | `tourId` (required) | `status` (optional) | None | `tourId` format; `status` in `OPEN, STARTED, PLANNED, ACTIVE, COMPLETED, CLOSED`; date filter not implemented |
| `GET /v1/tours/{tourId}/rides/{rideId}` | `tourId, rideId` (required) | None | None | `tourId` format; `rideId` format `RIDE###` |
| `POST /v1/tours/{tourId}/rides` | `tourId` (required) | None | Required: `rideId, date, rideNo, name, startLocation, finishLocation, totalDistance, flagOffTime, stages`; Optional: `description` | date `YYYY-MM-DD`; `flagOffTime` `HH:MM`; `totalDistance > 0`; `rideNo` positive integer; `stages` non-empty array; tour status `PLANNING/ACTIVE`; duplicate `rideId` rejected |
| `PUT /v1/tours/{tourId}/rides/{rideId}` | `tourId, rideId` (required) | None | At least one of: `name, date, rideNo, startLocation, finishLocation, totalDistance, flagOffTime, stages, description, status` | date/time/number checks when fields present; `status` in `OPEN, STARTED, PLANNED, ACTIVE, COMPLETED, CLOSED` |
| `POST /v1/tours/{tourId}/rides/open` | `tourId` (required) | None | None | Finds ride for current UTC date and sets status to `OPEN`; rejects if already `OPEN`; no `rideId` accepted |
| `POST /v1/tours/{tourId}/rides/start` | `tourId` (required) | None | None | Finds ride for current UTC date and sets status to `STARTED`; rejects if already `STARTED`; no `rideId` accepted |
| `POST /v1/tours/{tourId}/rides/{rideId}/close` | `tourId, rideId` (required) | None | None | Ride must exist and must not already be `CLOSED` |

#### Check-Ins

| Endpoint | Path Params | Query Params | Body Attributes | Validation / Business Rules |
|---|---|---|---|---|
| `POST /v1/tours/{tourId}/checkins` | `tourId` (required) | None | Required: `riderId, rideId, method`; Conditionally Required: `stageNumber` (normal check-in only); Optional: `isNotRiding, isQuitRiding, timestamp, notes` | `method` in `QR_SCAN, MANUAL, FALLBACK`; MANUAL requires `CHECKIN_MANUAL`; timestamp ISO UTC `Z`; `stageNumber` required only when both `isNotRiding=false` and `isQuitRiding=false`; rider exists in tour; duplicate and status conflict checks enforced (`DUPLICATE_CHECKIN`, `DUPLICATE_NOT_RIDING`, `RIDER_NOT_RIDING`, `RIDER_QUIT_RIDING`, `RIDE_CLOSED`) |
| `GET /v1/tours/{tourId}/rides/{rideId}/checkins` | `tourId, rideId` (required) | None | None | `tourId` + `rideId` format rules; ride must exist |
| `GET /v1/tours/{tourId}/rides/{rideId}/dashboard` | `tourId, rideId` (required) | None | None | `tourId` + `rideId` format rules; ride must exist; supports `If-None-Match` and `304 Not Modified` |

Note: `GET /v1/riders/{riderId}/checkins` is not currently implemented.

#### Users

| Endpoint | Path Params | Query Params | Body Attributes | Validation / Business Rules |
|---|---|---|---|---|
| `GET /v1/users/me` | None | None | None | Requires valid JWT claims; returns 401 for missing/invalid claims |
| `GET /v1/tours/{tourId}/users` | `tourId` (required) | `role` (optional) | None | `tourId` format; `role` in `ADMINISTRATOR, SUPER_USER, HOTEL_STAFF, GUEST, RIDER`, or `PS_<n>_USER` |

#### Admin User Management

All endpoints below require caller role `ADMINISTRATOR` and are backed by the management Cognito User Pool.

| Endpoint | Path Params | Query Params | Body Attributes | Validation / Business Rules |
|---|---|---|---|---|
| `GET /v1/admin/usermgmt/roles` | None | None | None | Returns dynamic groups from management user pool, sorted lexicographically |
| `GET /v1/admin/usermgmt/users` | None | `role` (optional), `enabled` (optional), `limit` (optional), `nextToken` (optional) | None | `role` must exist in user-pool groups; `enabled` must be boolean string |
| `POST /v1/admin/usermgmt/users` | None | None | Required: `email, roles`; Optional: `phoneNumber, name` | `email` valid; `phoneNumber` E.164 when present; `roles` non-empty valid groups; role assignment failure triggers rollback + `ROLE_ASSIGNMENT_CONFLICT` |
| `POST /v1/admin/usermgmt/users/{cognitoUserId}/enable` | `cognitoUserId` (required UUID) | None | None | Idempotent success for already enabled users |
| `POST /v1/admin/usermgmt/users/{cognitoUserId}/disable` | `cognitoUserId` (required UUID) | None | None | Idempotent success for already disabled users |
| `DELETE /v1/admin/usermgmt/users/{cognitoUserId}` | `cognitoUserId` (required UUID) | None | None | Deletes the Cognito user directly with `AdminDeleteUser`; SDK/API flow does not require a prior disable |
| `PUT /v1/admin/usermgmt/users/{cognitoUserId}` | `cognitoUserId` (required UUID) | None | At least one of: `email, phoneNumber, name, roles` | `roles` when provided is full replacement set; empty `phoneNumber`/`name` clears Cognito attribute |

#### Notifications

| Endpoint | Path Params | Query Params | Body Attributes | Validation / Business Rules |
|---|---|---|---|---|
| `GET /v1/tours/{tourId}/notifications` | `tourId` (required) | `type` (optional), `riderId` (optional) | None | `tourId` format; `type` in `TOUR_ANNOUNCEMENT, RIDE_UPDATE, SAFETY_ALERT, PERSONAL_MESSAGE, CHECKIN_REMINDER, REGISTRATION_STATUS`; without `riderId` returns broadcast only |
| `POST /v1/tours/{tourId}/notifications` | `tourId` (required) | None | Required: `type, title, message`; Optional: `targetRiderId, expiresAt` | `type` enum validation; requires `NOTIFICATION_MANAGE` |
| `PUT /v1/tours/{tourId}/notifications/{notificationId}` | `tourId, notificationId` (required) | None | Required: `profileId` | `notificationId` must exist in tour notification table; idempotent read-marking |

### Sample JSON Payloads

#### Create Tour
```json
{
  "tourId": "TOT-2026",
  "name": "Tour of Tamilnadu 2026",
  "startDate": "2026-02-10",
  "endDate": "2026-02-17",
  "description": "Annual coastal cycling tour"
}
```

#### Create Rider Profile
```json
{
  "name": "John Doe",
  "email": "john@example.com",
  "phone": "+1234567890",
  "emergencyContactName": "Jane Doe",
  "emergencyContactPhone": "+0987654321",
  "dateOfBirth": "1990-01-15",
  "gender": "Male",
  "address": "123 Main St"
}
```

#### Create Ride
```json
{
  "rideId": "RIDE001",
  "date": "2026-06-15",
  "rideNo": 1,
  "name": "Geneva to Lausanne",
  "startLocation": "Geneva Central",
  "finishLocation": "Lausanne",
  "totalDistance": 65.5,
  "flagOffTime": "08:00",
  "stages": [
    {
      "stageId": "S000",
      "stageNumber": 0,
      "type": "START",
      "name": "Start"
    }
  ]
}
```

#### Create Check-In
```json
{
  "riderId": "R57",
  "rideId": "RIDE001",
  "stageNumber": 0,
  "method": "QR_SCAN",
  "isNotRiding": false,
  "isQuitRiding": false,
  "timestamp": "2026-02-11T10:30:00Z",
  "notes": ""
}
```

#### Create Notification
```json
{
  "type": "TOUR_ANNOUNCEMENT",
  "title": "Route Change",
  "message": "Tomorrow's ride route has been updated due to road construction.",
  "targetRiderId": "R57",
  "expiresAt": "2026-02-20T00:00:00Z"
}
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

| Endpoint | Administrator | Super User | PS_<n>_User | Hotel Staff | Guest |
|----------|--------------|------------|-------------|-------------|-------|
| GET tours | ✅ | ✅ | ✅ | ✅ | ✅ |
| GET riders | ✅ | ✅ | ✅ | ✅ | ✅ |
| GET rides | ✅ | ✅ | ✅ | ✅ | ✅ |
| GET dashboard | ✅ | ✅ | ✅ | ❌ | ✅ |
| POST check-in | ✅ | ✅ | Stage-bound regular PIT_STOP check-ins plus any Quit Riding check-in | ✅ | ❌ |
| POST tours (create/provision) | ✅ | ❌ | ❌ | ❌ | ❌ |
| POST archive tour | ✅ | ❌ | ❌ | ❌ | ❌ |
| POST/PUT rides | ✅ | ❌ | ❌ | ❌ | ❌ |
| POST open ride | ✅ | ❌ | ❌ | ❌ | ❌ |
| POST start ride | ✅ | ❌ | ❌ | ❌ | ❌ |
| POST close ride | ✅ | ❌ | ❌ | ❌ | ❌ |
| Manual check-in | ✅ | ✅ | ❌ | ❌ | ❌ |
| POST notification (create) | ✅ | ✅ | ❌ | ❌ | ❌ |
| POST riders/profile (create) | Any authenticated user | | | | |
| POST tours/{tourId}/riders (register) | Any authenticated user | | | | |
| GET rider statistics | Any authenticated user | | | | |
| POST profile picture | Any authenticated user | | | | |
| GET notifications | Any authenticated user | | | | |
| PUT notification (mark read) | Any authenticated user | | | | |

## Request Validation

All requests are validated at three levels: API Gateway auth, Lambda RBAC, and handler-level schema/business validation.

### Common Validation Rules

1. **Authentication**
   - All API routes are JWT-authorized via Cognito User Pool authorizers.

2. **Authorization (RBAC permissions in Lambda)**
   - `TOUR_MANAGE`: create/archive tours
  - `RIDE_MANAGE`: create/update/open/start/close rides
  - `CHECKIN`: create check-ins, with additional stage-aware enforcement for `PS_<n>_USER` roles on regular pit-stop check-ins

### Pit Stop Role Rules

1. `PS_1_USER` can create a regular check-in only for stage `1` when stage type is `PIT_STOP`.
2. `PS_2_USER`, `PS_3_USER`, and higher follow the same pattern using their numeric suffix.
3. Stage `0` is always `START`, the last stage is always `FINISH`, and pit stop roles cannot create regular check-ins for either of those stage types.
4. A user may hold multiple `PS_<n>_USER` groups and may create regular check-ins for any matching assigned pit-stop stage.
5. Any `PS_<n>_USER` role may create a `Quit Riding` check-in.
   - `CHECKIN`: create check-ins
   - `CHECKIN_MANUAL`: required in addition to CHECKIN for `method=MANUAL`
   - `DASHBOARD`: read dashboard aggregation endpoint
   - `USER_LIST`: list tour users
   - `NOTIFICATION_MANAGE`: create notifications

3. **Identifier and format validators**
   - Rider ID: `R1` to `R999` (`^R([1-9]\d{0,2})$`)
   - Tour ID: 3-50 chars, starts with letter/number, allowed chars `[a-zA-Z0-9_.-]`
   - Ride ID: `RIDE###` (for example `RIDE001`)
  - Stage ID: `S###` (for example `S000`)
   - Date: `YYYY-MM-DD`
   - Datetime: ISO 8601 UTC with `Z` suffix only
   - Time: `HH:MM` 24-hour format

4. **General body requirements**
   - `validate_required_fields` rejects missing fields and fields explicitly set to `null`.
   - Invalid JSON request body returns `400`.

### Implemented Check-In Business Validation

1. Stage number must be within ride stage range (0 to total stages - 1).
2. Rider must be registered in the tour.
3. Duplicate normal check-in at same stage is rejected (`DUPLICATE_CHECKIN`).
4. Duplicate Not Riding is rejected (`DUPLICATE_NOT_RIDING`).
5. Rider marked Not Riding cannot create normal check-in (`RIDER_NOT_RIDING`).
6. Rider with previous Quit Riding cannot check in again (`RIDER_QUIT_RIDING`), except offline timestamp pre-dating quit timestamp.
7. Ride in CLOSED status rejects check-ins (`RIDE_CLOSED`), except offline timestamp pre-dating `closedAt`.
8. `stageNumber` is mandatory only for normal check-ins; Not Riding and Quit Riding entries can be created without stage attributes.

### Additional Endpoint-Specific Validation Highlights

1. Create Tour enforces `endDate >= startDate` and unique `tourId`.
2. Create Ride enforces positive `totalDistance`, positive integer `rideNo`, and non-empty `stages`.
3. List filters validate enum values (`status`, `role`, `notification type`).
4. Dashboard endpoint supports ETag and conditional `304 Not Modified`.

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
