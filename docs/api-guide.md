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
| Tours | POST | `/v1/tours` | Create tour, optionally provision tables | [Tours](#tours) | ✅ | ❌
| Tours | PUT | `/v1/tours` | Update tour and optionally provision it for the first time | [Tours](#tours) | ✅ | ❌
| Tours | PUT | `/v1/tours/{tourId}/provision` | Re-provision missing tour tables | [Tours](#tours) | ✅ | ❌
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
| Riders | POST | `/v1/tours/{tourId}/riders/{riderId}/baggage/release` | Mark retained baggage as released back to the rider | [Riders](#riders) | ✅ | ❌
| Riders | GET | `/v1/tours/{tourId}/riders/{riderId}/statistics` | Get rider statistics | [Riders](#riders) | ✅ | ❌
| Artifacts | POST | `/v1/artifacts/tour/presign-upload` | Generate presigned upload URL for a tour artifact | [Artifacts](#artifacts) | ✅ | ❌
| Artifacts | POST | `/v1/artifacts/ride/presign-upload` | Generate presigned upload URL for a ride artifact | [Artifacts](#artifacts) | ✅ | ❌
| Artifacts | DELETE | `/v1/artifacts/tour/{tourId}/{artifactId}` | Delete a tour artifact | [Artifacts](#artifacts) | ✅ | ❌
| Artifacts | DELETE | `/v1/artifacts/ride/{tourId}/{rideId}/{artifactId}` | Delete a ride artifact | [Artifacts](#artifacts) | ✅ | ❌
| Artifacts | GET | `/v1/tours/{tourId}/artifacts` | Get tour artifacts manifest | [Artifacts](#artifacts) | ✅ | ✅
| Artifacts | GET | `/v1/tours/{tourId}/rides/{rideId}/artifacts` | Get ride artifacts manifest | [Artifacts](#artifacts) | ✅ | ✅
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
| Events | GET | `/v1/tours/{tourId}/events` | List event definitions | [Events](#events) | ✅ | ❌ |
| Events | GET | `/v1/tours/{tourId}/events/{eventId}` | Get event definition | [Events](#events) | ✅ | ❌ |
| Events | POST | `/v1/tours/{tourId}/events` | Create event definition | [Events](#events) | ✅ | ❌ |
| Events | PUT | `/v1/tours/{tourId}/events/{eventId}` | Update event definition | [Events](#events) | ✅ | ❌ |
| Events | GET | `/v1/tours/{tourId}/events/{eventId}/occurrences` | List occurrences | [Events](#events) | ✅ | ❌ |
| Events | GET | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}` | Get occurrence | [Events](#events) | ✅ | ❌ |
| Events | POST | `/v1/tours/{tourId}/events/{eventId}/occurrences` | Create occurrence | [Events](#events) | ✅ | ❌ |
| Events | PUT | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}` | Update occurrence | [Events](#events) | ✅ | ❌ |
| Events | GET | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/activity-overrides` | Get activity overrides | [Events](#events) | ✅ | ❌ |
| Events | PUT | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/activity-overrides` | Update activity overrides | [Events](#events) | ✅ | ❌ |
| Events | POST | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/start` | Start occurrence | [Events](#events) | ✅ | ❌ |
| Events | POST | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/complete` | Complete occurrence | [Events](#events) | ✅ | ❌ |
| Events | POST | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/cancel` | Cancel occurrence | [Events](#events) | ✅ | ❌ |
| Events | POST | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/records` | Create activity record | [Events](#events) | ✅ | ❌ |
| Events | POST | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/records/{recordId}/cancel` | Cancel activity record | [Events](#events) | ✅ | ❌ |
| Events | GET | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/dashboard` | Get event dashboard | [Events](#events) | ✅ | ❌ |
| Events | GET | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/dashboard/progress` | Get event dashboard progress | [Events](#events) | ✅ | ❌ |
| Events | GET | `/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/reconciliation` | Get event reconciliation payload | [Events](#events) | ✅ | ❌ |
| Events | GET | `/v1/tours/{tourId}/events/bootstrap` | Get event bootstrap payload | [Events](#events) | ✅ | ✅ |
| Events | GET | `/v1/tours/{tourId}/riders/{riderId}/events/progress` | Get rider event progress | [Events](#events) | ✅ | ✅ |
| Hotels | GET | `/v1/tours/{tourId}/hotels` | List hotels | [Hotels](#hotels) | ✅ | ❌ |
| Hotels | POST | `/v1/tours/{tourId}/hotels` | Create hotel | [Hotels](#hotels) | ✅ | ❌ |
| Hotels | PUT | `/v1/tours/{tourId}/hotels/{hotelId}` | Update hotel | [Hotels](#hotels) | ✅ | ❌ |
| Hotels | GET | `/v1/tours/{tourId}/hotelstays` | List hotel stays by date | [Hotels](#hotels) | ✅ | ❌ |
| Hotels | GET | `/v1/tours/{tourId}/riders/{riderId}/hotelstays` | List hotel stays for a rider | [Hotels](#hotels) | ✅ | ✅ |
| Hotels | GET | `/v1/tours/{tourId}/hotels/{hotelId}/hotelstays` | List hotel stays for a hotel/date | [Hotels](#hotels) | ✅ | ❌ |
| Hotels | PUT | `/v1/tours/{tourId}/hotelstays/{stayDate}/{riderId}` | Upsert a single-night room allocation | [Hotels](#hotels) | ✅ | ❌ |
| Hotels | POST | `/v1/tours/{tourId}/hotelstays/uploads/presign` | Generate upload URL for hotel allocations CSV | [Hotels](#hotels) | ✅ | ❌ |
| Hotels | GET | `/v1/tours/{tourId}/hotelstays/uploads/{uploadId}` | Get hotel allocation upload status | [Hotels](#hotels) | ✅ | ❌ |
| Users | GET | `/v1/users/me` | Get current user claims | [Users](#users) | ✅ | ✅
| Users | GET | `/v1/users/cognito` | List Cognito users with only `sub` and `name` | [Users](#users) | ✅ | ❌
| Users | GET | `/v1/tours/{tourId}/users` | List tour users | [Users](#users) | ✅ | ❌
| Users | POST | `/v1/tours/{tourId}/users` | Create a tour-scoped user assignment | [Users](#users) | ✅ | ❌ |
| Users | PUT | `/v1/tours/{tourId}/users/{userId}` | Update a tour-scoped user assignment | [Users](#users) | ✅ | ❌ |
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
| `POST /v1/tours` | None | None | Required: `tourId, name, startDate, endDate, rideCount`; Optional: `description, provisioning` | `tourId` format + uniqueness; dates `YYYY-MM-DD`; `endDate >= startDate`; `rideCount` must be a positive integer (total rides planned for the tour, may exceed the number of tour days); `provisioning` is boolean, defaults to `false`, is not stored in TourMaster, and provisions 11 tour tables only when `true`; successful provisioning sets `provisionedAt` |
| `PUT /v1/tours` | None | None | Required: `tourId`; Optional: `name, startDate, endDate, description, rideCount, status, provisioning` | Tour must exist; `tourId` format; dates `YYYY-MM-DD`; `endDate >= startDate`; `rideCount` must be a positive integer; `status` in `PLANNING, PROVISIONING, ACTIVE, COMPLETED, ARCHIVED`; `provisioning` is boolean and defaults to `false`; when `provisioning=false`, only TourMaster is updated; when `provisioning=true`, provisioning is allowed only when `provisionedAt` is absent, then it creates 11 tables and sets `provisionedAt`; repeat provisioning is rejected |
| `PUT /v1/tours/{tourId}/provision` | `tourId` (required) | None | None | Tour must exist and have `provisionedAt`; reruns idempotent provisioning to create only missing or newly defined table types; does not modify TourMaster, including `provisionedAt` |
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
| `POST /v1/tours/{tourId}/riders/{riderId}/exit` | `tourId, riderId` (required) | None | Required: `baggageDisposition` | Updates existing row only; sets `status=EXITED`, `prevStatus=<previous status>`, `exitedAt`, `exitedBy`, and `updatedAt`; `baggageDisposition` must be `RETAINED` or `WITH_RIDER`; returns `409 RIDER_ALREADY_EXITED` when already exited; requires `RIDER_EXIT` permission (`ADMINISTRATOR` and `SUPER_USER` only) |
| `POST /v1/tours/{tourId}/riders/{riderId}/exit/cancel` | `tourId, riderId` (required) | None | None | Valid only when current status is `EXITED`; restores `status` from `prevStatus`; removes `prevStatus`, `exitedAt`, `exitedBy`, and associated baggage-exit metadata; returns `400 INVALID_EXIT_CANCEL_INVOCATION` for non-EXITED status; requires `RIDER_EXIT` permission (`ADMINISTRATOR` and `SUPER_USER` only) |
| `POST /v1/tours/{tourId}/riders/{riderId}/baggage/release` | `tourId, riderId` (required) | None | Optional: `note` | Valid only when the rider's baggage status is `RETAINED`; transitions baggage state to `WITH_RIDER`, stores `note` as `baggageExitNote`, and records release audit metadata; requires `RIDER_EXIT` permission (`ADMINISTRATOR` and `SUPER_USER` only) |
| `GET /v1/tours/{tourId}/riders/{riderId}/statistics` | `tourId, riderId` (required) | None | None | `tourId` + `riderId` format rules; rider must exist in tour |

#### Events

| Endpoint | Path Params | Query Params | Body Attributes | Validation / Business Rules |
|---|---|---|---|---|
| `GET /v1/tours/{tourId}/events` | `tourId` (required) | None | None | Requires `READ`; returns all event definitions for the tour |
| `GET /v1/tours/{tourId}/events/{eventId}` | `tourId, eventId` (required) | None | None | Requires `READ`; `eventId` format `EVT-...`; returns `404 EVENT_NOT_FOUND` when absent |
| `POST /v1/tours/{tourId}/events` | `tourId` (required) | None | Required: `eventId, eventName, eventType, location, activities`; Optional: `sequenceEnforced, defaultAllowedTypeCodes, allowSelfService` | Requires `EVENT_MANAGE`; validates event/activity IDs, allowed type codes, and ascending `sequenceNo`; duplicate event IDs rejected |
| `PUT /v1/tours/{tourId}/events/{eventId}` | `tourId, eventId` (required) | None | Optional: `eventName, eventType, location, sequenceEnforced, allowSelfService, defaultAllowedTypeCodes, activities` | Requires `EVENT_MANAGE`; same event/activity validations as create for supplied fields |
| `GET /v1/tours/{tourId}/events/{eventId}/occurrences` | `tourId, eventId` (required) | `date` (optional), `status` (optional) | None | Requires `READ`; lists occurrences for the event, filterable by date and status |
| `GET /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}` | `tourId, eventId, occurrenceId` (required) | None | None | Requires `READ`; `occurrenceId` format `EVT-...#YYYY-MM-DD#seq` |
| `POST /v1/tours/{tourId}/events/{eventId}/occurrences` | `tourId, eventId` (required) | None | Required: `date, seq`; Optional: `selfServiceEnabled, linkedOccurrenceRef` | Requires `EVENT_OCCURRENCE_MANAGE`; duplicate occurrence rejected; `activityOverrides` cannot be set on create — use the activity-overrides endpoint below after the occurrence exists |
| `PUT /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}` | `tourId, eventId, occurrenceId` (required) | None | Optional: `selfServiceEnabled, linkedOccurrenceRef` only | Requires `EVENT_OCCURRENCE_MANAGE`; rejects with `409 OCCURRENCE_CLOSED` when the occurrence is `COMPLETED`/`CANCELLED`; does not accept `date`, `seq`, or `activityOverrides` |
| `GET/PUT /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/activity-overrides` | `tourId, eventId, occurrenceId` (required) | None | For PUT: `activityId` (required); Optional: `enabled, selfServiceEnabled, allowedTypeCodes, note` | GET requires `READ`; PUT is a single-activity upsert (not a full-list replace) requiring `EVENT_OCCURRENCE_MANAGE`; omitting all optional fields removes the override entry |
| `POST /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/start` | `tourId, eventId, occurrenceId` (required) | None | None | Requires `EVENT_OCCURRENCE_MANAGE`; occurrence transitions to `ACTIVE`; `startedAt` is always server-set, no client override |
| `POST /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/complete` | `tourId, eventId, occurrenceId` (required) | None | None | Requires `EVENT_OCCURRENCE_MANAGE`; occurrence transitions to `COMPLETED`; `completedAt` is always server-set, no client override |
| `POST /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/cancel` | `tourId, eventId, occurrenceId` (required) | None | Optional: `cancelReason` | Requires `EVENT_OCCURRENCE_MANAGE`; occurrence transitions to `CANCELLED`; `cancelledAt` is always server-set, no client override |
| `POST /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/records` | `tourId, eventId, occurrenceId` (required) | None | Required: `activityId, riderId, method, timestamp`; Optional: `typeCode, outcome, variantSelected` | Requires `EVENT_SCAN`; occurrence must be `ACTIVE`; `typeCode` is required unless `outcome=OPTED_OUT`; sequence and activity restrictions enforced |
| `POST /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/records/{recordId}/cancel` | `tourId, eventId, occurrenceId, recordId` (required) | None | Optional: `cancelReason` | Requires `EVENT_SCAN`; retains the record and marks it cancelled with audit fields |
| `GET /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/dashboard` | `tourId, eventId, occurrenceId` (required) | None | None | Requires `DASHBOARD`; aggregated occurrence dashboard payload (response shape: §Event Engine & Hotel Response Shapes) |
| `GET /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/dashboard/progress` | `tourId, eventId, occurrenceId` (required) | None | None | Requires `DASHBOARD`; lightweight progress refresh payload |
| `GET /v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}/reconciliation` | `tourId, eventId, occurrenceId` (required) | None | None | Requires `DASHBOARD`; returns `loadedCount`, `unloadedCount`, and `missingRiderIds` (riders present in the loading occurrence but absent from the linked unloading occurrence); `400 NO_LINKED_OCCURRENCE` when the occurrence has no `linkedOccurrenceRef` |
| `GET /v1/tours/{tourId}/events/bootstrap` | `tourId` (required) | None | None | Requires `READ`; bootstrap payload for event definitions, upcoming occurrences, and supporting lookup data |
| `GET /v1/tours/{tourId}/riders/{riderId}/events/progress` | `tourId, riderId` (required) | None | None | Requires `READ`; rider-centric event progress summary |

#### Hotels

| Endpoint | Path Params | Query Params | Body Attributes | Validation / Business Rules |
|---|---|---|---|---|
| `GET /v1/tours/{tourId}/hotels` | `tourId` (required) | None | None | Requires `READ`; lists hotel master records only |
| `POST /v1/tours/{tourId}/hotels` | `tourId` (required) | None | Required: `hotelId, name, city, address`; Optional: `contact, notes` | Requires `HOTEL_ALLOC_MANAGE`; `hotelId` format `HTL-AAA-99`; duplicate hotel rejected |
| `PUT /v1/tours/{tourId}/hotels/{hotelId}` | `tourId, hotelId` (required) | None | Optional: `name, city, address, contact, notes` | Requires `HOTEL_ALLOC_MANAGE`; updates supplied fields only |
| `GET /v1/tours/{tourId}/hotelstays` | `tourId` (required) | `date` (required) | None | Requires `READ`; returns `RoomAllocation` rows for one stay date |
| `GET /v1/tours/{tourId}/riders/{riderId}/hotelstays` | `tourId, riderId` (required) | None | None | Requires `READ`; returns hotel stays for a rider |
| `GET /v1/tours/{tourId}/hotels/{hotelId}/hotelstays` | `tourId, hotelId` (required) | `date` (required) | None | Requires `READ`; returns hotel stays for one hotel/date |
| `PUT /v1/tours/{tourId}/hotelstays/{stayDate}/{riderId}` | `tourId, stayDate, riderId` (required) | None | Required: `hotelId, roomNo`; Optional: `roomCapacity, sharingWith, checkInDate, checkOutDate` | Requires `HOTEL_ALLOC_MANAGE`; validates reciprocal sharing and room-capacity constraints |
| `POST /v1/tours/{tourId}/hotelstays/uploads/presign` | `tourId` (required) | None | None | Requires `HOTEL_ALLOC_MANAGE`; returns `uploadId`, presigned CSV upload URL, and S3 key |
| `GET /v1/tours/{tourId}/hotelstays/uploads/{uploadId}` | `tourId, uploadId` (required) | None | None | Requires `HOTEL_ALLOC_MANAGE`; returns upload processing status |

#### Users

| Endpoint | Path Params | Query Params | Body Attributes | Validation / Business Rules |
|---|---|---|---|---|
| `GET /v1/users/me` | None | None | None | Returns current JWT claims as seen by the API |
| `GET /v1/users/cognito` | None | None | None | Requires `READ`; returns Cognito users with minimal fields |
| `GET /v1/tours/{tourId}/users` | `tourId` (required) | None | None | Requires `USER_LIST`; lists tour-scoped user assignments |
| `GET /v1/tours/{tourId}/users/me` | `tourId` (required) | None | None | Requires `READ`; returns the caller's own `User-{tourId}` record (keyed by JWT `sub`); `404 USER_NOT_FOUND` if the caller has no tour-scoped record |
| `POST /v1/tours/{tourId}/users` | `tourId` (required) | None | Required: `userId, role`; Optional: `status, assignedStage, hotelId, eventAssignments, assignedActivityIds` | Requires `USER_MANAGE`; `userId` must be a valid Cognito sub and an existing managed user (`404 USER_NOT_FOUND` otherwise); `username`/`email`/`name` are snapshotted from the Cognito profile, not taken from the request body; validates referenced hotels/events |
| `PUT /v1/tours/{tourId}/users/{userId}` | `tourId, userId` (required) | None | Optional: `username, email, name, role, status, assignedStage, hotelId, eventAssignments, assignedActivityIds` | Requires `USER_MANAGE`; validates supplied referenced hotels/events and updates only provided fields |

#### Artifacts

| Endpoint | Path Params | Query Params | Body Attributes | Validation / Business Rules |
|---|---|---|---|---|
| `POST /v1/artifacts/tour/presign-upload` | None | None | Required: `tourId, artifactId, contentType`; optional `fileName` | Requires `ARTIFACT_MANAGE`; `tourId` must exist; artifact type must be configured under `ARTIFACTS` with `category=tour`; `contentType` must be in the allow-list; returns presigned S3 `put_object` URL and persisted metadata item |
| `POST /v1/artifacts/ride/presign-upload` | None | None | Required: `tourId, rideId, artifactId, contentType`; optional `fileName` | Requires `ARTIFACT_MANAGE`; `tourId` and `rideId` must exist; artifact type must be configured with `category=ride`; `contentType` must be in the allow-list; returns presigned `put_object` URL and metadata item |
| `DELETE /v1/artifacts/tour/{tourId}/{artifactId}` | `tourId, artifactId` (required) | None | None | Requires `ARTIFACT_MANAGE`; deletes the S3 object and corresponding `Artifacts-{tourId}` table record; returns `404` when not found |
| `DELETE /v1/artifacts/ride/{tourId}/{rideId}/{artifactId}` | `tourId, rideId, artifactId` (required) | None | None | Requires `ARTIFACT_MANAGE`; deletes the ride-scoped S3 object and metadata; returns `404` when not found |
| `GET /v1/tours/{tourId}/artifacts` | `tourId` (required) | `artifactId` (optional), `expiresIn` (optional) | None | Requires `READ`; `tourId` must exist; returns list of artifacts with presigned download URLs; `artifactId` filters to single artifact; `expiresIn` is integer between 60 and 3600 seconds (default 900); empty list if no artifacts found |
| `GET /v1/tours/{tourId}/rides/{rideId}/artifacts` | `tourId, rideId` (required) | `artifactId` (optional), `expiresIn` (optional) | None | Requires `READ`; `tourId` and `rideId` must exist; returns list of ride artifacts with presigned download URLs; `artifactId` filters to single artifact; `expiresIn` is integer between 60 and 3600 seconds (default 900); empty list if no artifacts found |

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
  "description": "Annual coastal cycling tour",
  "provisioning": true
}
```

#### Update Tour
```json
{
  "tourId": "TOT-2026",
  "name": "Tour of Tamilnadu 2026 - Updated",
  "startDate": "2026-02-10",
  "endDate": "2026-02-18",
  "status": "PLANNING",
  "provisioning": true
}
```

#### Re-provision Tour Tables
```json
PUT /v1/tours/TOT-2026/provision
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

## Event Engine & Hotel Response Shapes

Response shapes for the event engine and hotel endpoints introduced alongside `docs/cycling-tour-events-design.md`, verified against the implementation.

#### GET .../occurrences/{occurrenceId}/dashboard
```json
{
  "success": true,
  "data": {
    "occurrence": { "eventId": "EVT-BAGLOAD", "dateSeq": "2026-02-12#1", "status": "ACTIVE" },
    "riders": [
      { "riderId": "R57", "activities": [ { "activityId": "ACT-001", "status": "PENDING" } ] }
    ],
    "cancelled": [ ]
  },
  "timestamp": "2026-02-12T05:42:15Z"
}
```

#### GET .../occurrences/{occurrenceId}/dashboard/progress
```json
{
  "success": true,
  "data": {
    "totalRiders": 100,
    "completedCount": 42,
    "outstandingMandatoryCount": 3,
    "optedOutCount": 5,
    "flaggedCount": 0
  },
  "timestamp": "2026-02-12T05:42:15Z"
}
```

#### GET /v1/tours/{tourId}/riders/{riderId}/events/progress
```json
{
  "success": true,
  "data": {
    "items": [
      { "eventId": "EVT-BAGLOAD", "occurrenceId": "EVT-BAGLOAD#2026-02-12#1", "activityId": "ACT-003", "status": "COMPLETED" }
    ]
  },
  "timestamp": "2026-02-12T05:42:15Z"
}
```
Cancelled records are excluded. Optional `eventId` query param filters the list.

#### GET .../occurrences/{occurrenceId}/reconciliation
```json
{
  "success": true,
  "data": {
    "loadedCount": 98,
    "unloadedCount": 96,
    "missingRiderIds": ["R12", "R57"]
  },
  "timestamp": "2026-02-12T05:42:15Z"
}
```
`400 NO_LINKED_OCCURRENCE` when the occurrence has no `linkedOccurrenceRef`.

#### GET /v1/tours/{tourId}/events/bootstrap
```json
{
  "success": true,
  "data": {
    "events": [ { "eventId": "EVT-REG", "activities": [ ] } ],
    "activeOccurrences": [ { "eventId": "EVT-BAGLOAD", "dateSeq": "2026-02-12#1", "status": "ACTIVE" } ],
    "riderBaggageStatus": [ { "riderId": "R57", "baggageStatus": "ACTIVE", "baggageReleasedAt": null } ],
    "hotelStaysToday": [ { "stayDate": "2026-02-12", "riderId": "R57", "hotelId": "HTL-MDU-01", "roomNo": "204" } ]
  },
  "timestamp": "2026-02-12T05:42:15Z"
}
```
Supports `If-None-Match` / `304 Not Modified`.

#### GET /v1/tours/{tourId}/hotelstays/uploads/{uploadId}
```json
{
  "success": true,
  "data": {
    "uploadId": "UPL-000042",
    "status": "APPLIED",
    "rowCount": 200,
    "errorCount": 0,
    "errors": [],
    "appliedCount": 200,
    "processedAt": "2026-02-01T10:05:00Z"
  },
  "timestamp": "2026-02-01T10:05:00Z"
}
```
`status` is one of `PENDING`, `VALIDATING`, `REJECTED`, `APPLIED`; per D21, `APPLIED` only occurs when `errorCount=0` for the whole file (no partial apply).

#### New error codes

In addition to the standard `400`/`401`/`403`/`404`/`409`/`500` statuses above, the event engine and hotel endpoints introduce the codes below. See `docs/cycling-tour-events-design.md` §8.25 for the complete reference table.

| Code | HTTP | Meaning |
|---|---|---|
| `EVENT_NOT_FOUND` / `EVENT_ALREADY_EXISTS` | 404 / 409 | Event definition lookup/create conflict |
| `OCCURRENCE_NOT_FOUND` / `OCCURRENCE_ALREADY_EXISTS` / `OCCURRENCE_CLOSED` | 404 / 409 / 409 | Occurrence lookup/create/edit conflicts |
| `INVALID_OCCURRENCE_TRANSITION` | 409 | Start/complete/cancel called from an invalid status |
| `NO_LINKED_OCCURRENCE` | 400 | Reconciliation requested with no `linkedOccurrenceRef` |
| `ACTIVITY_NOT_FOUND` | 404 | `activityId` not present/disabled on the event or occurrence |
| `SCAN_TYPE_NOT_ALLOWED` | 400 | Scanned `typeCode` not in the activity's effective `allowedTypeCodes` |
| `DUPLICATE_ACTIVITY_RECORD` | 409 | Rider already has a non-cancelled record for this activity+occurrence |
| `PREREQUISITE_NOT_MET` | 409 | Sequence/prerequisite activity not yet completed |
| `OCCURRENCE_NOT_ACTIVE` | 409 | Scan against a non-`ACTIVE` occurrence outside the late-sync grace window |
| `BAGGAGE_NOT_IN_TOUR` | 409 | Rider's `baggageStatus=WITH_RIDER`, scan rejected |
| `RIDER_NOT_ASSIGNED` / `HOTEL_MISMATCH` | 403 / 403 | Second-layer authorisation failures (`eventAssignments`, hotel match) |
| `HOTEL_NOT_FOUND` / `HOTEL_ALREADY_EXISTS` | 404 / 409 | Hotel lookup/create conflict |
| `ROOM_CLASH` / `NON_RECIPROCAL_SHARING` / `ROOM_CAPACITY_EXCEEDED` | 409 | Room allocation validation failures |
| `UPLOAD_NOT_FOUND` | 404 | `uploadId` unknown |
| `BAGGAGE_DISPOSITION_REQUIRED` / `BAGGAGE_NOT_RETAINED` | 400 / 409 | Rider exit/baggage release validation |
| `RECORD_NOT_FOUND` / `RECORD_ALREADY_CANCELLED` | 404 / 409 | Activity record cancel conflicts |
| `USER_NOT_FOUND` / `USER_ALREADY_EXISTS` / `INVALID_EVENT_ASSIGNMENT` | 404 / 409 / 400 | Tour user assignment validation |

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
| POST rider baggage release | ✅ | ✅ | ❌ | ❌ | ❌ |
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
| GET event/hotel read APIs | ✅ | ✅ | ✅ | ✅ | ✅ |
| POST/PUT event definitions | ✅ | ❌ | ❌ | ❌ | ❌ |
| POST/PUT/start/complete/cancel occurrences | ✅ | ✅ | ❌ | ❌ | ❌ |
| POST event activity record / cancel event record | ✅ | ✅ | ✅ | ✅ | ❌ |
| POST/PUT hotels and hotel stays | ✅ | ✅ | ❌ | ❌ | ❌ |
| POST/PUT tour users | ✅ | ❌ | ❌ | ❌ | ❌ |
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
  - `RIDER_EXIT`: mark rider as `EXITED`, release retained baggage, and cancel rider exit (ADMINISTRATOR and SUPER_USER only)
  - `CHECKIN`: create check-ins, with additional stage-aware enforcement for `PS_<n>_USER` roles on regular pit-stop check-ins
  - `EVENT_MANAGE`: create/update event definitions
  - `EVENT_OCCURRENCE_MANAGE`: create/update/start/complete/cancel event occurrences
  - `EVENT_SCAN`: create/cancel event activity records
  - `HOTEL_ALLOC_MANAGE`: manage hotels and room allocations
  - `USER_MANAGE`: create/update tour-scoped user assignments

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
