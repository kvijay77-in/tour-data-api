# Rider Profile Attributes Design (Phase 1 backend)

## Scope
Configuration-driven rider profile definitions are stored in `AppConfig` and enforced by backend APIs.
Frontend apps (`tour-mgmt-app`, `tour-rider-app`) must integrate against this contract.

## AppConfig model
Shared table columns: `configType` (PK), `configId` (SK), `enabled`, `config`, `description`, `version`, `updatedAt`, `updatedBy`.

### Config types
- `RIDER_PROFILE_SECTION`
  - `config`: `{ label, icon?, order, description? }`
- `RIDER_PROFILE_ATTRIBUTE` (where `configId` is attribute key)
  - `config`: `{ label, helpText?, placeholder?, sectionId, order, type, lovId?, storage, required, adminOnly, sensitive, visibleToAllMgmtUsers, system, validation?, visibleWhen?, dependsOn?, fallbackToText?, fields?, repeatable?, maxItems?, handler?, handlerOptions? }`
- `LOV`
  - `config`: `{ label, parentLovId?, items: [{ value, label, order, enabled, parent?, meta? }] }`

## Attribute field types
- `TEXT`, `TEXTAREA`: string (`minLength`, `maxLength`, `pattern`)
- `EMAIL`: string email
- `PHONE`: E.164 string, 6–15 digits
- `URL`: URL string
- `NUMBER`: number (`min`, `max`, `decimals`, `unit`)
- `DATE`: `YYYY-MM-DD` (`minDate`/`maxDate`, absolute or relative like `-18y`)
- `BOOLEAN`: bool
- `SELECT`: string + `lovId` (`dependsOn`, `fallbackToText`)
- `MULTI_SELECT`: list of strings + `lovId` (`minItems`, `maxItems`)
- `FILE`, `IMAGE`: `{ s3Key, fileName, contentType, sizeBytes, uploadedAt }` (`allowedMimeTypes`, `maxFileSizeBytes`)
- `GROUP`: map or list-of-maps (`fields`, `repeatable`, `maxItems`)

## Immutable rules
- `RIDER_PROFILE_ATTRIBUTE` key (`configId`) and `type` are immutable after create.
- No delete: set `enabled=false`.
- `system=true` attributes cannot be disabled; key/type/storage are immutable.

## Handler registry
Supported handlers:
- `PERSONAL_CODE`: personalCode normalization + uniqueness checks
- `COGNITO_EMAIL`: system-controlled email
- `PROFILE_PHOTO`: profile picture binding (`photoS3Key`)

Unknown handler names are rejected during definition writes.

## Seeded sections/LOVs/attributes
Seed script provides:
- Sections: `personal`, `contact`, `address`, `emergency`, `medical`, `preferences`, `organizer`
- LOVs: `COUNTRY`, `STATE`, `GENDER`, `DIETARY_PREFERENCE`, `BLOOD_GROUP`, `RELATIONSHIP`
- System attributes: `name`, `email`, `phone`, `photo`, `personalCode`
- Additional attributes: `dateOfBirth`, `gender`, `address`, `emergencyContact`, `dietaryPreference`, `bloodGroup`, `hasMedicalCondition`, `medicalConditions`

`dietaryPreference` now writes to `attributes.dietaryPreference`; old top-level values are not auto-migrated.

## Shared profile schema module
`src/layers/common/profile_schema.py`:
- Loads enabled sections/attributes/LOVs with ~60s warm cache
- Computes `definitionsVersion`
- Validates type, LOV membership, dependent LOVs, `visibleWhen`, GROUP/repeatable
- Merge semantics: update only submitted keys (`CORE` paths + `attributes.<key>`), never remove unsent keys
- Unknown/disabled submitted keys -> `422 UNKNOWN_OR_DISABLED_ATTRIBUTE`
- Required checks run on merged profile on save; rider saves skip `adminOnly` required fields
- Response filtering by role, excluding disabled/unknown stored attributes

## Ownership security model
`src/layers/common/ownership.py`:
- Rider API identification via `requestContext.apiId == RIDER_API_ID` (env)
- `require_own_profile(event, profile_id)` enforces rider ownership using `RiderCognitoUser` (`sub -> profileId`)
- Ownership mismatch returns `403 PROFILE_ACCESS_DENIED` **before data reads**
- Link routes enforce path `{cognitoUserName} == JWT sub`

## APIs
### Admin config (TourDataApi, ADMINISTRATOR only)
- `GET /v1/admin/config/{configType}`
  - Allowed types: `RIDER_PROFILE_ATTRIBUTE`, `RIDER_PROFILE_SECTION`, `LOV`
  - Returns enabled + disabled entries
- `PUT /v1/admin/config/{configType}/{configId}`
  - Upsert, version conflict on mismatch -> `409 CONFIG_VERSION_CONFLICT`
  - Updates `version`, `updatedAt`, `updatedBy`
  - Validates schema + references + immutable rules
  - Errors: `SYSTEM_ATTRIBUTE_PROTECTED`, `IMMUTABLE_FIELD`

### Rider profile write APIs
- `POST /v1/riders/profile`
- `POST /v1/riders/profile/{profileId}`
- `PUT /v1/riders/profile/{profileId}`

Request additions:
- `attributes` map
- `definitionsVersion` optimistic definition check (`409 PROFILE_DEFINITIONS_CHANGED`)

Rules:
- `adminOnly` write by rider -> `403 ADMIN_ONLY_ATTRIBUTE`
- Admin write via TourDataApi allowed
- Legacy emergency-contact compatibility retained

### Attribute file routes
- `POST /v1/riders/profile/{profileId}/attributes/{key}/upload`
  - Owner or ADMINISTRATOR
  - Valid only for FILE/IMAGE attributes in `ATTRIBUTES` scope
  - S3 key format: `riders/{profileId}/attributes/{key}/{uuid}.{ext}`
- `GET /v1/riders/profile/{profileId}/attributes/{key}/download`
  - Owner, or staff with role-based visibility

## Staff response filtering
Applied to:
- `GET /v1/tours/{tourId}/riders`
- `GET /v1/tours/{tourId}/riders/{riderId}`
- `GET /v1/tours/{tourId}/rides/{rideId}/riders/{riderId}/details`
- TourDataApi access to `GET /v1/riders/profile/{profileId}`

Rules:
- Attributes with `visibleToAllMgmtUsers=false` visible only to `ADMINISTRATOR` and `SUPER_USER`
- Disabled/unknown stored attributes are never returned
- Sensitive visible attributes listed in `sensitiveKeys`
- Ride details include filtered `profileAttributes`

## Error codes
- `UNKNOWN_OR_DISABLED_ATTRIBUTE`
- `ADMIN_ONLY_ATTRIBUTE`
- `PROFILE_DEFINITIONS_CHANGED`
- `CONFIG_VERSION_CONFLICT`
- `SYSTEM_ATTRIBUTE_PROTECTED`
- `IMMUTABLE_FIELD`
- `PROFILE_ACCESS_DENIED`

## Out of scope
- Migration/cleanup of old profile data
- Frontend implementation
