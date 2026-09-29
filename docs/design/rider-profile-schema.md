# Rider profile schema
_Last updated: 2026-09-29_

## Configuration model

Rider profile definitions are stored in the shared `AppConfig` table and read through `GET /v1/config`. The schema is configuration-driven so the profile form and its validation rules can evolve without changing the DynamoDB table shape.

| Config type | Purpose |
|---|---|
| `RIDER_PROFILE_SECTION` | Profile form sections and their display order |
| `RIDER_PROFILE_ATTRIBUTE` | Attribute type, storage location, validation, visibility, and behavior |
| `LOV` | Reusable lists of values, including dependent lists |

Attributes support scalar values and structured groups, including repeatable groups. Supported attribute types include text, email, phone, URL, number, date, boolean, select, multi-select, file, image, and group. File/image attributes store an S3 object reference and upload metadata; the file itself remains in S3.

Definitions identify whether an attribute is required, administrator-only, sensitive, visible to management users, system-controlled, or conditionally visible. System attributes are protected from disabling and key/type/storage changes. Attribute type and identifier are immutable once created; disabling is used instead of deletion.

## Validation and updates

`src/layers/common/profile_schema.py` loads enabled definitions and LOVs with a short warm cache. It validates type, value membership, dependent LOVs, conditional visibility, grouped values, and required attributes. `definitionsVersion` is derived by the backend and returned alongside configuration; clients pass that value on profile writes to detect stale forms.

Profile updates merge submitted values into the existing profile. Unsubmitted values are preserved, optional `null` values clear attributes, and required validation runs against the merged result. Unknown or disabled submitted keys are rejected. Responses omit disabled or unknown stored attributes and apply role-based visibility filtering.

## Identity and access

Rider profiles are keyed by `profileId` and are separate from tour-scoped rider records. On the Rider API, `src/layers/common/ownership.py` resolves the caller's profile through the `RiderCognitoUser` mapping and enforces ownership before reading or writing profile data. Ownership failures return `PROFILE_ACCESS_DENIED`. Staff responses use the configured visibility rules; medical or otherwise sensitive data is not returned to unauthorized staff.

The profile picture is represented by an S3 key on the profile. File/image attribute uploads use a profile-scoped key prefix and presigned URLs.

See [API reference](api-reference.md#riders) and [Data model](data-model.md) for API contracts and table inventory. Product requirements are maintained in [Rider profile requirements](../requirements/rider-profile.md).
