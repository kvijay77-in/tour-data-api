# User Management API Requirements (Backend Handoff)

This document is intended for backend team implementation.
It is not part of app end-user documentation.

## Scope

Implement backend APIs to support these Administrator-only app features:
1. New user onboarding
2. Enable/disable existing user
3. Modify user profile (email, phone, name)

## API Base Path

All endpoints must be under:
- `/v1/admin/usermgmt`

## Auth and Authorization

1. Authentication: JWT from Cognito User Pool.
2. Authorization: only `ADMINISTRATOR` users can access these endpoints.
3. Non-admin users must receive `403 FORBIDDEN`.
4. All write actions must be audit logged.

## Required Endpoints

| Feature | Method | Path |
|---|---|---|
| List assignable role groups | GET | `/v1/admin/usermgmt/roles` |
| List users | GET | `/v1/admin/usermgmt/users` |
| Create user | POST | `/v1/admin/usermgmt/users` |
| Enable user | POST | `/v1/admin/usermgmt/users/{cognitoUserId}/enable` |
| Disable user | POST | `/v1/admin/usermgmt/users/{cognitoUserId}/disable` |
| Update user profile | PUT | `/v1/admin/usermgmt/users/{cognitoUserId}` |

## Common Response Envelope

Success:

```json
{
  "success": true,
  "data": {},
  "timestamp": "2026-07-18T12:00:00Z"
}
```

Error:

```json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Human readable message"
  },
  "timestamp": "2026-07-18T12:00:00Z"
}
```

## Data Contract

### ManagedUser object (API response model)

```json
{
  "cognitoUserId": "6b3f8ca7-2f56-4f1a-a4a5-2fd9a29d3f5d",
  "username": "user@example.com",
  "email": "user@example.com",
  "phoneNumber": "+919876543210",
  "name": "User Name",
  "enabled": true,
  "status": "CONFIRMED",
  "roles": ["ADMINISTRATOR", "PS_2_USER"]
}
```

Rules:
1. `cognitoUserId` maps to Cognito `sub` and is the key used by frontend for enable/disable/update.
2. Treat `cognitoUserId` as the raw Cognito `sub` value. Do not enforce RFC UUID version/variant validation on this field.
2. `roles` are Cognito group names.

## Endpoint Specifications

### 1) List Role Groups

- Method: `GET`
- Path: `/v1/admin/usermgmt/roles`
- Purpose: return assignable Cognito group names.

Response `200` example:

```json
{
  "success": true,
  "data": {
    "groups": [
      "ADMINISTRATOR",
      "SUPER_USER",
      "HOTEL_STAFF",
      "GUEST",
      "PS_1_USER",
      "PS_2_USER"
    ]
  },
  "timestamp": "2026-07-18T12:00:00Z"
}
```

Validation/business rules:
1. Include all valid assignable groups.
2. Return groups sorted lexicographically.

### 2) List Users

- Method: `GET`
- Path: `/v1/admin/usermgmt/users`
- Purpose: return users with Name, Email, Roles, enabled flag.

Optional query params:
1. `role` (single group filter)
2. `enabled` (`true` or `false`)
3. `limit` (positive integer)
4. `nextToken` (pagination token)

Response `200` example:

```json
{
  "success": true,
  "data": {
    "users": [
      {
        "cognitoUserId": "6b3f8ca7-2f56-4f1a-a4a5-2fd9a29d3f5d",
        "username": "user@example.com",
        "email": "user@example.com",
        "phoneNumber": "+919876543210",
        "name": "User Name",
        "enabled": true,
        "status": "CONFIRMED",
        "roles": ["SUPER_USER"]
      }
    ],
    "nextToken": null
  },
  "timestamp": "2026-07-18T12:00:00Z"
}
```

Validation/business rules:
1. If `role` is provided, it must match valid role/group patterns.
2. If `enabled` is provided, it must be boolean.

### 3) Create User (Onboarding)

- Method: `POST`
- Path: `/v1/admin/usermgmt/users`
- Purpose: create Cognito user and assign one or more roles.

Request body:

```json
{
  "email": "new.user@example.com",
  "phoneNumber": "+919876543210",
  "name": "New User",
  "roles": ["SUPER_USER", "PS_2_USER"]
}
```

Validation rules:
1. `email` required, valid format.
2. `phoneNumber` optional; if provided must be E.164 (`+` + digits).
3. `name` optional, trimmed string.
4. `roles` required, non-empty array, each value must be a valid Cognito group.

Response `201` example:

```json
{
  "success": true,
  "data": {
    "cognitoUserId": "bb27d38c-3547-4e9d-a334-4f3cd7168d91",
    "username": "new.user@example.com"
  },
  "timestamp": "2026-07-18T12:00:00Z"
}
```

Implementation notes:
1. Use Cognito `AdminCreateUser`.
2. Assign roles through group membership APIs.
3. Delivery medium behavior should follow deployment environment policy.

### 4) Enable User

- Method: `POST`
- Path: `/v1/admin/usermgmt/users/{cognitoUserId}/enable`
- Purpose: enable user account.

Path param:
1. `cognitoUserId` required (Cognito `sub` string)

Response `200` example:

```json
{
  "success": true,
  "data": {
    "cognitoUserId": "6b3f8ca7-2f56-4f1a-a4a5-2fd9a29d3f5d",
    "enabled": true
  },
  "timestamp": "2026-07-18T12:00:00Z"
}
```

Business rule:
1. Idempotent: enabling an already enabled user should still return success.

### 5) Disable User

- Method: `POST`
- Path: `/v1/admin/usermgmt/users/{cognitoUserId}/disable`
- Purpose: disable user account.

Path param:
1. `cognitoUserId` required (Cognito `sub` string)

Response `200` example:

```json
{
  "success": true,
  "data": {
    "cognitoUserId": "6b3f8ca7-2f56-4f1a-a4a5-2fd9a29d3f5d",
    "enabled": false
  },
  "timestamp": "2026-07-18T12:00:00Z"
}
```

Business rule:
1. Idempotent: disabling an already disabled user should still return success.

### 6) Update User Profile

- Method: `PUT`
- Path: `/v1/admin/usermgmt/users/{cognitoUserId}`
- Purpose: update existing user fields from Modify User screen.

Path param:
1. `cognitoUserId` required (Cognito `sub` string)

Request body:

```json
{
  "email": "updated.user@example.com",
  "phoneNumber": "+919812345678",
  "name": "Updated User"
}
```

Validation rules:
1. At least one of `email`, `phoneNumber`, `name` must be present.
2. `email` (if present): valid format.
3. `phoneNumber` (if present and non-empty): E.164 format.
4. `name` (if present): trimmed string.
5. Empty `phoneNumber` or `name` should clear corresponding Cognito attribute.

Response `200` example:

```json
{
  "success": true,
  "data": {
    "cognitoUserId": "6b3f8ca7-2f56-4f1a-a4a5-2fd9a29d3f5d"
  },
  "timestamp": "2026-07-18T12:00:00Z"
}
```

## Error Codes

| HTTP | Code | Meaning |
|---|---|---|
| 400 | `VALIDATION_ERROR` | Invalid or missing request data |
| 401 | `UNAUTHORIZED` | Missing/invalid JWT |
| 403 | `FORBIDDEN` | Caller not ADMINISTRATOR |
| 404 | `USER_NOT_FOUND` | Target user not found |
| 409 | `USER_ALREADY_EXISTS` | Create user email already exists |
| 409 | `ROLE_ASSIGNMENT_CONFLICT` | Role assignment failed |
| 429 | `RATE_LIMITED` | Request throttled |
| 500 | `INTERNAL_ERROR` | Unhandled server error |

## Logging and Audit Requirements

For `POST` and `PUT` endpoints:
1. Record actor identity from JWT claims.
2. Record target `cognitoUserId` (where applicable).
3. Record action name (`CREATE_USER`, `ENABLE_USER`, `DISABLE_USER`, `UPDATE_USER`).
4. Record timestamp and result (`SUCCESS`/`FAILURE`).
5. Do not log secrets or sensitive tokens.

## Frontend Mapping (Already Implemented)

- `listAvailableRoleGroups` -> `GET /v1/admin/usermgmt/roles`
- `listCognitoUsersWithRoles` -> `GET /v1/admin/usermgmt/users`
- `createCognitoUser` -> `POST /v1/admin/usermgmt/users`
- `setCognitoUserEnabled(true)` -> `POST /v1/admin/usermgmt/users/{cognitoUserId}/enable`
- `setCognitoUserEnabled(false)` -> `POST /v1/admin/usermgmt/users/{cognitoUserId}/disable`
- `updateCognitoUserProfile` -> `PUT /v1/admin/usermgmt/users/{cognitoUserId}`

## Acceptance Checklist

1. All six endpoints implemented under `/v1/admin/usermgmt`.
2. ADMINISTRATOR-only access enforced.
3. Response envelope format consistent.
4. `cognitoUserId` (sub) used as user key for enable/disable/update.
5. Idempotent enable/disable behavior verified.
6. Role list and user list endpoints support UI requirements.
7. Create/update input validation and clear-attribute behavior verified.
8. Audit logging enabled for write operations.
