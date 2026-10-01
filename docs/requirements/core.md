# Core requirements
_Last updated: 2026-10-01_

This document is the source of truth for the backend's core tour, ride, check-in, and platform requirements. Topic-specific requirements are maintained in the sibling files in this folder.

## Platform and data isolation

- The backend provides shared API access to tour data for the platform's client applications.
- Each deployment is isolated to its AWS account and environment; tour and rider data must not be shared across deployments.
- Tour operational data is isolated in tour-specific DynamoDB tables. Tour-independent rider profile and participation data remains in shared tables.
- Amazon API Gateway HTTP APIs, AWS Lambda, DynamoDB, Amazon S3, and Amazon Cognito provide the backend service.
- The backend repository owns the AWS infrastructure for the entire platform, including management and rider Cognito user pools.

## Tour and ride operations

- A tour has a unique `tourId`, name, date range, lifecycle status, and planned ride count.
- A tour must be provisioned before tour-specific operations are available. Repair provisioning must be safe for already-provisioned tours and must not change their existing `provisionedAt` timestamp.
- A ride belongs to one tour and has a date, schedule, distance, status, and ordered stages.
- Stage numbering starts at zero. Stage `0` is `START`; the final stage is `FINISH`; intermediate pit-stop stages are `PIT_STOP`.
- Tour `selfQuitRidingAllowed` defaults to `false`; a ride-level value overrides it. Ride and stage `selfCheckInAllowed` values inherit stage → ride → stage-type defaults (`START=true`, `FINISH=true`, `PIT_STOP=false`). Ride-level `selfCheckInAllowed` and `selfQuitRidingAllowed` may be set to `null` on create/update to leave them unset and inherit the defaults. Only START may set `selfNotRidingAllowed`, which defaults to `false`.
- Ride create/update requests containing stages require exactly one START first and one FINISH last; all intervening stages are PIT_STOP. Older rides without these settings continue to use the defaults.
- Ride status and stage runtime state are controlled through the backend API. Only applicable pit-stop stages may be opened or closed, and only while the ride is started.

## Ride check-ins

- The backend records rider check-ins against a tour, ride, and stage, with the authenticated actor and timestamp.
- Normal check-ins, `Not Riding`, and `Quit Riding` are distinct outcomes. QR scanning is supported; manual entry is available only to users with the corresponding permission.
- A rider must be enrolled in the tour. A rider may have no more than one `Not Riding` record per ride, and duplicate normal check-ins at the same stage are rejected.
- A rider marked `Not Riding` or `Quit Riding` cannot make later check-ins for that ride, subject to the API's timestamp and cancellation rules.
- A check-in cancellation retains the record and its audit information; cancelled records are excluded from normal check-in validation and read results, except where the dashboard contract returns them separately.
- A pit-stop user may create regular check-ins only for their assigned pit-stop stage. Any `PS_<n>_USER` may record `Quit Riding` at any stage.
- Rider self-check-ins are Rider API only, use the caller's linked tour identity, and reuse normal check-in validation/write logic. They are limited to today's OPEN/STARTED ride and configured stage/type availability. Riders may cancel their own eligible stage or Not Riding check-ins, including staff-created records; Quit Riding is never rider-cancellable.
- Rider API check-in lists are own-rider-only and include method and check-in audit fields. Cancelled records remain excluded.

## Operational scale

The initial operating profile is approximately 100 riders per tour, 7–8 rides, 10–15 concurrent app users, and retention of five past tours. Designs should favor the low, variable workload and avoid unnecessary provisioned capacity.

See [Architecture](../design/architecture.md), [Data model](../design/data-model.md), and the [API reference](../design/api-reference.md) for technical contracts and implementation details.
