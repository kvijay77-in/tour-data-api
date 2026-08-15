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

| Domain | Method | Path | Purpose | Contract | Mgmt App | Rider App
|---|---|---|---|---|---|---|
| Config | GET | `/v1/config` | Get enabled app configuration items | [Config](#config) |  ✅ | ✅
| Tours | GET | `/v1/tours/active` | Get currently active tour | [Tours](#tours) | ✅ | ✅
| Tours | GET | `/v1/tours/{tourId}` | Get tour details | [Tours](#tours) | ✅ | ✅
| Tours | GET | `/v1/tours` | List tours | [Tours](#tours) | ✅ | ✅
| Tours | POST | `/v1/tours` | Create and provision tour | [Tours](#tours) | ✅ | ❌
| Tours | POST | `/v1/tours/{tourId}/archive` | Archive tour | [Tours](#tours) | ✅ | ❌
| Riders | POST | `/v1/riders/profile` | Create rider profile | [Riders](#riders) | ❌ | ✅
| Riders | POST | `/v1/riders/profile/{profileId}` | Create rider profile | [Riders](#riders) | ❌ | ✅
| Riders | GET | `/v1/riders/link/{cognitoUserName}` | Get linked profile ID for a Cognito username | [Riders](#riders) | ❌ | ✅
| Riders | POST | `/v1/riders/link/{cognitoUserName}` | Create Cognito username to profile mapping | [Riders](#riders) | ❌ | ✅
| Riders | DELETE | `/v1/riders/link/{cognitoUserName}` | Delete Cognito username to profile mapping | [Riders](#riders) | ❌ | ✅
| Riders | GET | `/v1/riders/profile/{profileId}` | Get rider profile | [Riders](#riders) | ✅ | ✅
| Riders | GET | `/v1/profile/{profileId}/tours` | List rider tour participation info across all tours for a profile | [Riders](#riders) | ✅ | ✅
| Riders | GET | `/v1/profile/{profileId}/tours/{tourId}` | Get rider tour participation info | [Riders](#riders) | ✅ | ✅
| Riders | PUT | `/v1/riders/profile/{profileId}` | Update rider profile | [Riders](#riders) | ❌ | ✅
| Riders | POST | `/v1/riders/profile/{profileId}/picture` | Get profile picture upload URL | [Riders](#riders) | ❌ | ✅
| Riders | GET | `/v1/riders/profile/{profileId}/picture` | Get profile picture download URL | [Riders](#riders) | ❌ | ✅
| Riders | GET | `/v1/tours/{tourId}/riders` | List tour riders | [Riders](#riders) | ✅ | ❌
| Riders | GET | `/v1/tours/{tourId}/riders/names` | List tour riders with riderId, name, and personalCode | [Riders](#riders) | ✅ | ❌
| Riders | POST | `/v1/tours/{tourId}/riders` | Register rider for tour | [Riders](#riders) | ✅ | ❌
| Riders | GET | `/v1/tours/{tourId}/riders/{riderId}` | Get tour rider | [Riders](#riders) | ✅ | ❌
| Riders | POST | `/v1/tours/{tourId}/riders/{riderId}/exit` | Mark rider as exited from tour | [Riders](#riders) | ✅ | ❌
| Riders | POST | `/v1/tours/{tourId}/riders/{riderId}/exit/cancel` | Cancel rider exit and restore previous status | [Riders](#riders) | ✅ | ❌
| Riders | GET | `/v1/tours/{tourId}/riders/{riderId}/statistics` | Get rider statistics | [Riders](#riders) | ✅ | ❌
| Rides | GET | `/v1/tours/{tourId}/rides/today` | Get today's ride | [Rides](#rides) | ✅ | ✅
| Rides | GET | `/v1/tours/{tourId}/rides` | List rides | [Rides](#rides) | ✅ | ✅
| Rides | GET | `/v1/tours/{tourId}/rides/{rideId}` | Get ride | [Rides](#rides) | ✅ | ✅
| Rides | POST | `/v1/tours/{tourId}/rides` | Create ride | [Rides](#rides) | ✅ | ❌
| Rides | PUT | `/v1/tours/{tourId}/rides/{rideId}` | Update ride | [Rides](#rides) | ✅ | ❌
| Rides | POST | `/v1/tours/{tourId}/rides/{rideId}/stages/{stageNumber}/pitstop/open` | Open pit stop stage | [Rides](#rides) | ✅ | ❌
| Rides | POST | `/v1/tours/{tourId}/rides/{rideId}/stages/{stageNumber}/pitstop/close` | Close pit stop stage | [Rides](#rides) | ✅ | ❌
| Rides | POST | `/v1/tours/{tourId}/rides/open` | Open today's ride | [Rides](#rides) | ✅ | ❌
| Rides | POST | `/v1/tours/{tourId}/rides/start` | Start today's ride | [Rides](#rides) | ✅ | ❌
| Rides | POST | `/v1/tours/{tourId}/rides/{rideId}/close` | Close ride | [Rides](#rides) | ✅ | ❌
| Check-Ins | POST | `/v1/tours/{tourId}/checkins` | Create check-in | [Check-Ins](#check-ins) | ✅ | ❌
| Check-Ins | GET | `/v1/tours/{tourId}/rides/{rideId}/checkins` | List ride check-ins | [Check-Ins](#check-ins) | ✅ | ❌
| Check-Ins | GET | `/v1/tours/{tourId}/riders/{riderId}/checkins` | List all check-ins for a rider | [Check-Ins](#check-ins) | ✅ | ✅
| Check-Ins | GET | `/v1/tours/{tourId}/riders/{riderId}/rides/{rideNo}/checkins` | List rider check-ins for a ride number | [Check-Ins](#check-ins) | ✅ | ✅
| Check-Ins | POST | `/v1/tours/{tourId}/rides/{rideId}/checkins/{checkInId}/cancel` | Cancel check-in (special update) | [Check-Ins](#check-ins) | ✅ | ❌
| Check-Ins | GET | `/v1/tours/{tourId}/rides/{rideId}/dashboard` | Get dashboard payload | [Check-Ins](#check-ins) | ✅ | ❌
| Check-Ins | GET | `/v1/tours/{tourId}/rides/{rideId}/dashboard/progress` | Get lightweight dashboard progress payload | [Check-Ins](#check-ins) | ✅ | ❌
| Check-Ins | GET | `/v1/tours/{tourId}/rides/{rideId}/riders/{riderId}/details` | Get rider popup details for selected ride | [Check-Ins](#check-ins) |✅ | ❌
| Users | GET | `/v1/users/me` | Get current user claims | [Users](#users) | ✅ | ✅
| Users | GET | `/v1/users/cognito` | List Cognito users with only `sub` and `name` | [Users](#users) | ✅ | ❌
| Users | GET | `/v1/tours/{tourId}/users` | List tour users | [Users](#users) | ✅ | ❌
| Admin UserMgmt | GET | `/v1/admin/usermgmt/roles` | List assignable Cognito groups | [Admin User Management](#admin-user-management) | ✅ | ❌
| Admin UserMgmt | GET | `/v1/admin/usermgmt/users` | List Cognito users with roles | [Admin User Management](#admin-user-management) | ✅ | ❌
| Admin UserMgmt | POST | `/v1/admin/usermgmt/users` | Create Cognito user and assign roles | [Admin User Management](#admin-user-management) | ✅ | ❌
| Admin UserMgmt | POST | `/v1/admin/usermgmt/users/{cognitoUserId}/enable` | Enable Cognito user | [Admin User Management](#admin-user-management) | ✅ | ❌
| Admin UserMgmt | POST | `/v1/admin/usermgmt/users/{cognitoUserId}/disable` | Disable Cognito user | [Admin User Management](#admin-user-management) | ✅ | ❌
| Admin UserMgmt | DELETE | `/v1/admin/usermgmt/users/{cognitoUserId}` | Delete Cognito user | [Admin User Management](#admin-user-management) | ✅ | ❌
| Admin UserMgmt | PUT | `/v1/admin/usermgmt/users/{cognitoUserId}` | Update Cognito profile and roles | [Admin User Management](#admin-user-management)| ✅ | ❌ |
| Notifications | GET | `/v1/tours/{tourId}/notifications` | List notifications | [Notifications](#notifications) | ✅ | ✅
| Notifications | POST | `/v1/tours/{tourId}/notifications` | Create notification | [Notifications](#notifications) | ✅ | ✅
| Notifications | PUT | `/v1/tours/{tourId}/notifications/{notificationId}` | Mark notification as read | [Notifications](#notifications) | ✅ | ✅

### Request Contract Tables

#### Config

| Endpoint | Path Params | Query Params | Body Attributes | Validation / Business Rules |
|---|---|---|---|---|
| `GET /v1/config` | None | `configType` (optional) | None | `configType` supports `ALL`, `ID_CODE_FORMAT`, `ID_CODE_TYPE`, or comma-separated combination of supported values; returns enabled items only; supports `If-None-Match` and `304 Not Modified`; invalid values return `400 INVALID_CONFIG_TYPE` |

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
| `POST /v1/riders/profile` | None | None | Required: `name, email, phone, emergencyContact`; Optional: `personalCode, dateOfBirth, gender, address` | Creates profile with auto-generated `profileId`; Email format; `emergencyContact` is an object with string fields `name, phone, relation`; `dateOfBirth` must be `YYYY-MM-DD`; `gender` in `Male, Female, Other, Prefer not to say`; `address` is an object with string fields `line1, line2, city, state, country, postalCode`; `personalCode` is normalized to uppercase when provided; duplicate email rejected (`EMAIL_ALREADY_EXISTS`); duplicate personalCode rejected (`PERSONAL_CODE_ALREADY_EXISTS`) |
| `POST /v1/riders/profile/{profileId}` | `profileId` (optional override route) | None | Required: `name, email, phone, emergencyContact`; Optional: `personalCode, dateOfBirth, gender, address` | Same validation as profile create; uses provided path `profileId` instead of auto-generating one; conflict on existing `profileId` returns `PROFILE_ALREADY_EXISTS` |
| `GET /v1/riders/link/{cognitoUserName}` | `cognitoUserName` (required) | None | None | Returns linked `profileId`; `404` if mapping does not exist |
| `POST /v1/riders/link/{cognitoUserName}` | `cognitoUserName` (required) | None | None | Creates mapping row with generated `profileId` UUID; duplicate `cognitoUserName` rejected (`COGNITO_USER_ALREADY_LINKED`) |
| `DELETE /v1/riders/link/{cognitoUserName}` | `cognitoUserName` (required) | None | None | Deletes mapping row; returns `404` if mapping does not exist |
| `GET /v1/riders/profile/{profileId}` | `profileId` (required) | None | None | `profileId` must exist |
| `GET /v1/profile/{profileId}/tours` | `profileId` (required) | None | None | Returns all RiderTours records for the profileId using partition key query (no `tourId` filter) |
| `GET /v1/profile/{profileId}/tours/{tourId}` | `profileId, tourId` (required) | None | None | `tourId` format: 3-50 chars, starts with letter/number, allowed `[a-zA-Z0-9_.-]`; returns one RiderTours record for the key pair |
| `PUT /v1/riders/profile/{profileId}` | `profileId` (required) | None | At least one of: `name, email, phone, emergencyContact, photoS3Key, personalCode, dateOfBirth, gender, address` | Email validated when provided; `emergencyContact` is an object with string fields `name, phone, relation`; `dateOfBirth` must be `YYYY-MM-DD` when provided; `gender` in `Male, Female, Other, Prefer not to say`; `address` is an object with string fields `line1, line2, city, state, country, postalCode`; `personalCode` normalized to uppercase; duplicate personalCode rejected (`PERSONAL_CODE_ALREADY_EXISTS`) |
| `POST /v1/riders/profile/{profileId}/picture` | `profileId` (required) | None | Optional: `contentType` | `profileId` must exist; `contentType` in `image/jpeg, image/png`; default `image/jpeg` |
| `GET /v1/riders/profile/{profileId}/picture` | `profileId` (required) | `expiresIn` (optional) | None | `profileId` must exist and have `photoS3Key` set, else `404`; `expiresIn` is an integer between 60 and 3600 seconds, default 300; returns presigned `downloadUrl` |
| `GET /v1/tours/{tourId}/riders` | `tourId` (required) | None | None | `tourId` format rule |
| `GET /v1/tours/{tourId}/riders/names` | `tourId` (required) | None | None | Returns lightweight list with `riderId`, `name`, and `personalCode`; requires authenticated user with `READ` permission |
| `POST /v1/tours/{tourId}/riders` | `tourId` (required) | None | Required: `profileId`; Optional: `riderId, experienceLevel, medicalConditions, specialRequirements` | Tour exists with status `PLANNING/ACTIVE`; profile exists; duplicate profile registration rejected (`ALREADY_REGISTERED`); generates temp riderId if omitted |
| `GET /v1/tours/{tourId}/riders/{riderId}` | `tourId, riderId` (required) | None | None | `tourId` format; `riderId` format `R1..R999` |
| `POST /v1/tours/{tourId}/riders/{riderId}/exit` | `tourId, riderId` (required) | None | None | Updates existing row only; sets `status=EXITED`, `prevStatus=<previous status>`, `exitedAt`, `exitedBy`, and `updatedAt`; returns `409 RIDER_ALREADY_EXITED` when already exited; requires `RIDER_EXIT` permission (`ADMINISTRATOR` and `SUPER_USER` only) |
| `POST /v1/tours/{tourId}/riders/{riderId}/exit/cancel` | `tourId, riderId` (required) | None | None | Valid only when current status is `EXITED`; restores `status` from `prevStatus`; removes `prevStatus`, `exitedAt`, `exitedBy`; returns `400 INVALID_EXIT_CANCEL_INVOCATION` for non-EXITED status; requires `RIDER_EXIT` permission (`ADMINISTRATOR` and `SUPER_USER` only) |
| `GET /v1/tours/{tourId}/riders/{riderId}/statistics` | `tourId, riderId` (required) | None | None | `tourId` + `riderId` format rules; rider must exist in tour |

#### Rides

| Endpoint | Path Params | Query Params | Body Attributes | Validation / Business Rules |
|---|---|---|---|---|
| `GET /v1/tours/{tourId}/rides/today` | `tourId` (required) | None | None | `tourId` format; 404 `NO_ACTIVE_RIDE` when no ride for current UTC date |
| `GET /v1/tours/{tourId}/rides` | `tourId` (required) | `status` (optional) | None | `tourId` format; `status` in `OPEN, STARTED, PLANNED, ACTIVE, COMPLETED, CLOSED`; date filter not implemented |
| `GET /v1/tours/{tourId}/rides/{rideId}` | `tourId, rideId` (required) | None | None | `tourId` format; `rideId` format `RIDE###` |
| `POST /v1/tours/{tourId}/rides` | `tourId` (required) | None | Required: `rideId, date, rideNo, name, startLocation, finishLocation, totalDistance, flagOffTime, stages`; Optional: `openTime, closeTime, floats, description` | date `YYYY-MM-DD`; `flagOffTime/openTime/closeTime` `HH:MM`; `totalDistance > 0`; `rideNo` positive integer; `stages` must be sequential with `START` first and `FINISH` last; `estimatedOpenTime` and `pitStopDuration` allowed only for `PIT_STOP`; `pitStopStatus/openedAt/closedAt` are system-managed; `floats` must be an array of unique positive `floatNo` values and `floatToStage` values between `1` and the ride's last stage number; tour status `PLANNING/ACTIVE`; duplicate `rideId` rejected |
| `PUT /v1/tours/{tourId}/rides/{rideId}` | `tourId, rideId` (required) | None | At least one of: `name, date, rideNo, startLocation, finishLocation, totalDistance, flagOffTime, openTime, closeTime, stages, floats, description, status` | date/time/number checks when fields present; `status` in `OPEN, STARTED, PLANNED, ACTIVE, COMPLETED, CLOSED`; stage updates preserve live pit-stop runtime state; `floats` follows the same validation rules as create |
| `POST /v1/tours/{tourId}/rides/{rideId}/stages/{stageNumber}/pitstop/open` | `tourId, rideId, stageNumber` (required) | None | None | Caller requires `PIT_STOP_MANAGE`; stage must exist, be `PIT_STOP`, and caller must hold matching `PS_<n>_USER` role unless SUPER_USER/ADMINISTRATOR; ride status must be `STARTED`; sets `pitStopStatus=OPEN` and `openedAt` |
| `POST /v1/tours/{tourId}/rides/{rideId}/stages/{stageNumber}/pitstop/close` | `tourId, rideId, stageNumber` (required) | None | None | Caller requires `PIT_STOP_MANAGE`; same stage rules as open; ride status must be `STARTED`; pit stop must already be `OPEN`; sets `pitStopStatus=CLOSED` and `closedAt` |
| `POST /v1/tours/{tourId}/rides/open` | `tourId` (required) | None | None | Finds ride for current UTC date and sets status to `OPEN`; rejects if already `OPEN`; no `rideId` accepted |
| `POST /v1/tours/{tourId}/rides/start` | `tourId` (required) | None | None | Finds ride for current UTC date and sets status to `STARTED`; rejects if already `STARTED`; no `rideId` accepted |
| `POST /v1/tours/{tourId}/rides/{rideId}/close` | `tourId, rideId` (required) | None | None | Ride must exist and must not already be `CLOSED` |

#### Check-Ins

| Endpoint | Path Params | Query Params | Body Attributes | Validation / Business Rules |
|---|---|---|---|---|
| `POST /v1/tours/{tourId}/checkins` | `tourId` (required) | None | Required: `riderId, rideId, method`; Conditionally Required: `stageNumber` (normal/float check-ins), `floatNo` (when `isFloat=true`); Optional: `isNotRiding, isFloat, isQuitRiding, timestamp, notes` | `method` in `QR_SCAN, MANUAL, FALLBACK`; MANUAL requires `CHECKIN_MANUAL`; timestamp ISO UTC `Z`; `isNotRiding`, `isFloat`, and `isQuitRiding` are mutually exclusive; `floatNo` must be a positive integer when `isFloat=true`; `stageNumber` required unless status is Not Riding or Quit Riding; rider exists in tour; duplicate and status conflict checks enforced (`DUPLICATE_CHECKIN`, `DUPLICATE_NOT_RIDING`, `RIDER_NOT_RIDING`, `RIDER_QUIT_RIDING`, `RIDE_CLOSED`); cancelled check-ins are ignored during these validations |
| `GET /v1/tours/{tourId}/rides/{rideId}/checkins` | `tourId, rideId` (required) | None | None | `tourId` + `rideId` format rules; ride must exist; cancelled check-ins are excluded from the response; each check-in keeps core audit attribute `checkedInBy` |
| `GET /v1/tours/{tourId}/riders/{riderId}/checkins` | `tourId, riderId` (required) | None | None | `tourId` + `riderId` format rules; rider must be registered in tour; cancelled check-ins are excluded from the response |
| `GET /v1/tours/{tourId}/riders/{riderId}/rides/{rideNo}/checkins` | `tourId, riderId, rideNo` (required) | None | None | `tourId` + `riderId` format rules; `rideNo` positive integer; rider must be registered in tour; cancelled check-ins are excluded from the response |
| `POST /v1/tours/{tourId}/rides/{rideId}/checkins/{checkInId}/cancel` | `tourId, rideId, checkInId` (required) | None | Required: `status, prevStatus` | Invocation is valid only when `status` contains `CANCELLED` (case-insensitive); updates only `status`, `prevStatus`, `cancelledBy`, and `cancelledAt`; any non-cancel status returns `INVALID_CANCEL_INVOCATION` |
| `GET /v1/tours/{tourId}/rides/{rideId}/dashboard` | `tourId, rideId` (required) | None | None | `tourId` + `rideId` format rules; ride must exist; supports `If-None-Match` and `304 Not Modified` |
| `GET /v1/tours/{tourId}/rides/{rideId}/dashboard/progress` | `tourId, rideId` (required) | None | None | Lightweight refresh contract with `rideId`, `checkIns`, `cancelled`, `summary`, `dataVersion`; `checkIns` retains active (non-cancelled) entries, `cancelled` contains cancelled check-in entries, and both lists keep core attribute `checkedInBy`; excludes `ride` and `riders`; supports `If-None-Match` and `304 Not Modified` |
| `GET /v1/tours/{tourId}/rides/{rideId}/riders/{riderId}/details` | `tourId, rideId, riderId` (required) | None | None | Returns popup-focused rider fields plus selected-ride `checkInTimeline`; cancelled entries excluded; returns `404` when ride or rider does not exist; supports `If-None-Match` and `304 Not Modified` |

#### Users

| Endpoint | Path Params | Query Params | Body Attributes | Validation / Business Rules |
|---|---|---|---|---|
| `GET /v1/users/me` | None | None | None | Requires valid JWT claims; returns 401 for missing/invalid claims |
| `GET /v1/users/cognito` | None | None | None | Requires a valid authenticated user group; returns only `sub` and `name` per Cognito user from the management user pool |
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
  "emergencyContact": {
    "name": "Jane Doe",
    "phone": "+0987654321",
    "relation": "Spouse"
  },
  "dateOfBirth": "1990-01-15",
  "gender": "Male",
  "address": {
    "line1": "123 Main St",
    "line2": "Apartment 4B",
    "city": "Chennai",
    "state": "Tamil Nadu",
    "country": "India",
    "postalCode": "600001"
  }
}
```

#### Create Rider Profile With Path profileId

Endpoint: `POST /v1/riders/profile/{profileId}`

Example request (path `profileId = CUSTOM-PROFILE-001`):
```json
{
  "name": "John Doe",
  "email": "john.custom@example.com",
  "phone": "+1234567890",
  "emergencyContact": {
    "name": "Jane Doe",
    "phone": "+0987654321",
    "relation": "Spouse"
  },
  "personalCode": "d220"
}
```

Example success response (`201 Created`):
```json
{
  "success": true,
  "data": {
    "profileId": "CUSTOM-PROFILE-001",
    "name": "John Doe",
    "email": "john.custom@example.com",
    "phone": "+1234567890",
    "emergencyContact": {
      "name": "Jane Doe",
      "phone": "+0987654321",
      "relation": "Spouse"
    },
    "personalCode": "D220",
    "createdAt": "2026-02-10T10:30:00Z",
    "updatedAt": "2026-02-10T10:30:00Z"
  },
  "timestamp": "2026-02-10T10:30:00Z"
}
```

Example conflict response when `profileId` already exists (`409`):
```json
{
  "success": false,
  "error": {
    "code": "PROFILE_ALREADY_EXISTS",
    "message": "Rider profile 'CUSTOM-PROFILE-001' already exists"
  },
  "timestamp": "2026-02-10T10:30:00Z"
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
  "openTime": "07:30",
  "flagOffTime": "08:00",
  "closeTime": "13:30",
  "floats": [
    {
      "floatNo": 1,
      "floatToStage": 1
    }
  ],
  "stages": [
    {
      "stageId": "S000",
      "stageNumber": 0,
      "type": "START",
      "name": "Start"
    },
    {
      "stageId": "S001",
      "stageNumber": 1,
      "type": "PIT_STOP",
      "name": "PS1",
      "estimatedOpenTime": 90,
      "pitStopDuration": 45
    },
    {
      "stageId": "S002",
      "stageNumber": 2,
      "type": "FINISH",
      "name": "Finish"
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
  "isFloat": true,
  "floatNo": 1,
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
| GET config | ✅ | ✅ | ✅ | ✅ | ✅ |
| GET tours | ✅ | ✅ | ✅ | ✅ | ✅ |
| GET riders | ✅ | ✅ | ✅ | ✅ | ✅ |
| POST rider exit | ✅ | ✅ | ❌ | ❌ | ❌ |
| POST rider exit cancel | ✅ | ✅ | ❌ | ❌ | ❌ |
| GET rides | ✅ | ✅ | ✅ | ✅ | ✅ |
| GET dashboard | ✅ | ✅ | ✅ | ❌ | ✅ |
| GET dashboard progress | ✅ | ✅ | ✅ | ❌ | ✅ |
| GET rider details popup | ✅ | ✅ | ✅ | ❌ | ✅ |
| GET Cognito users (`/v1/users/cognito`) | ✅ | ✅ | ✅ | ✅ | ✅ |
| POST check-in | ✅ | ✅ | Stage-bound regular PIT_STOP check-ins plus any Quit Riding check-in | ✅ | ❌ |
| POST tours (create/provision) | ✅ | ❌ | ❌ | ❌ | ❌ |
| POST archive tour | ✅ | ❌ | ❌ | ❌ | ❌ |
| POST/PUT rides | ✅ | ❌ | ❌ | ❌ | ❌ |
| POST open/close pit stop | ✅ | ✅ | Assigned stage only | ❌ | ❌ |
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
  - `PIT_STOP_MANAGE`: open/close pit-stop stages
  - `RIDER_EXIT`: mark rider as `EXITED` and cancel rider exit (ADMINISTRATOR and SUPER_USER only)
  - `CHECKIN`: create check-ins, with additional stage-aware enforcement for `PS_<n>_USER` roles on regular pit-stop check-ins

### Pit Stop Role Rules

1. `PS_1_USER` can create a regular check-in only for stage `1` when stage type is `PIT_STOP`.
2. `PS_2_USER`, `PS_3_USER`, and higher follow the same pattern using their numeric suffix.
3. Stage `0` is always `START`, the last stage is always `FINISH`, and pit stop roles cannot create regular check-ins for either of those stage types.
4. A user may hold multiple `PS_<n>_USER` groups and may create regular check-ins for any matching assigned pit-stop stage.
5. Any `PS_<n>_USER` role may create a `Quit Riding` check-in.
6. `PS_<n>_USER` may open or close only pit stop stage `n`; `SUPER_USER` and `ADMINISTRATOR` may manage any pit stop stage.
7. Pit stop open/close is valid only for `PIT_STOP` stages while the ride status is `STARTED`.

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
2. Create Ride enforces positive `totalDistance`, positive integer `rideNo`, and sequential `stages` with `START` first and `FINISH` last.
3. List filters validate enum values (`status`, `role`, `notification type`).
4. Dashboard, dashboard-progress, rider-details, and config endpoints support ETag and conditional `304 Not Modified`.

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
