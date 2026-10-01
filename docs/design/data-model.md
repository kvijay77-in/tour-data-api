# Data model
_Last updated: 2026-10-01_

## Table strategy

The backend uses two DynamoDB scopes:

- **Shared tables** are created and managed by the deployed SAM stack. They hold data shared across tours.
- **Tour-specific tables** are created at runtime for each tour using the naming pattern `{stack}-{TableType}-{tourId}`. This keeps operational data isolated by tour.

Tour provisioning creates or repairs the complete set of **13** tour-specific table types. The table inventory is defined by `TOUR_TABLE_TYPES` in `src/layers/common/models.py` and the provisioning specifications in `src/layers/common/tour_provisioning.py`.

## Shared tables

| Table | Key | Purpose |
|---|---|---|
| `RiderProfile` | `profileId` | Tour-independent rider identity and profile attributes |
| `RiderTours` | `profileId` + `tourId`; GSI `TourStatusIndex` on `tourId` + `status` | Rider participation lifecycle for each tour |
| `RiderCognitoUser` | `cognitoUserName` | Maps a rider Cognito identity to a profile |
| `TourMaster` | `tourId`; GSI `StatusIndex` on `status` | Tour registry and lifecycle |
| `AppConfig` | `configType` + `configId` | Shared application, ID-code, artifact, hotel-upload, notification, and profile configuration |
| `NotificationRule` | `ruleId` | Notification rules and message templates |
| `RiderNotification` | `audience` + `sk` | Rider notification inbox and read state |
| `MgmtNotification` | `audience` + `sk` | Management notification inbox and read state |
| `RiderPushDevice` | `profileId` + `token` | Rider push-device registrations |
| `MgmtPushDevice` | `cognitoSub` + `token` | Management push-device registrations and group fan-out data |

The shared table resources and their indexes, billing mode, streams, TTL settings, encryption, and tags are defined in `template.yaml`.

## Tour-specific tables

| Table type | Purpose |
|---|---|
| `TourRider` | Rider enrollment and tour-specific rider state |
| `Ride` | Ride schedules, stages, and ride state |
| `CheckIn` | Ride check-in records |
| `User` | Tour-scoped staff assignments |
| `Notification` | Tour-scoped notification inbox |
| `NotificationArchive` | Archived tour-scoped notification records |
| `Artifacts` | Metadata for tour and ride files stored in S3 |
| `Event` | Event definitions, including embedded activity definitions |
| `EventOccurrence` | Dated event instances and occurrence-level overrides |
| `EventActivityLogs` | Event activity scan and completion records |
| `EventRegistration` | Occurrence/rider registrations; partition key `occurrenceId`, sort key `riderId`, GSI `RiderIdIndex` |
| `Hotel` | Tour hotel records |
| `RoomAllocation` | One rider's room allocation for one stay date |

The stack name and tour ID are part of each physical table name. The tour-specific partition keys do not need a redundant tour ID because each table belongs to one tour. Event, notification, artifact, and profile-specific details are documented in their respective [design pages](events.md), [notifications](notifications.md), [artifacts](artifacts.md), and [rider profile schema](rider-profile-schema.md).

## Provisioning and lifecycle

Tour tables are provisioned by `scripts/provision_tour.py` / `make provision-tour` or by the tour APIs. `PUT /v1/tours/{tourId}/provision` idempotently repairs a provisioned tour by creating missing table types, including `EventRegistration`, without changing the tour record's `provisionedAt` value. Archive export and deletion iterate the same table inventory. Provisioning and cleanup behavior is implemented in `src/layers/common/tour_provisioning.py`, `scripts/provision_tour.py`, and `scripts/cleanup_tour_tables.py`.

See the [API reference](api-reference.md#tours) for provisioning request semantics and the [deployment guide](../guides/deployment.md#after-deployment-provisioning-a-tour) for operator steps.
