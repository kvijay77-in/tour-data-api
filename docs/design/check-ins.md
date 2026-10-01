# Ride check-ins
_Last updated: 2026-10-01_

## Stored policy

Tour `selfQuitRidingAllowed` is a boolean that defaults to `false`. A ride may override it; an absent ride setting inherits the tour value. A ride-wide `selfCheckInAllowed` controls all stages unless a stage overrides it. When neither level is set, stage defaults are `START=true`, `FINISH=true`, and `PIT_STOP=false`. Sending `null` for either ride-level setting on create/update leaves it absent (or removes an existing override on update), restoring inheritance. Only a START stage may set `selfNotRidingAllowed`; its default is `false`.

Ride responses expose the calculated configuration as `selfService`:

- `quitRidingAllowed`: ride value, then tour value, then `false`.
- `notRidingAllowed`: START stage `selfNotRidingAllowed`, default `false`.
- `stages`: ordered stage objects containing `stageNumber`, `stageId`, `stageType`, and calculated `checkInAllowed`.

This object describes configuration. Runtime ride and pit-stop state is checked when a rider acts. Ride stage updates must preserve exactly one START first and one FINISH last, with PIT_STOP stages between them. Existing rides without these fields resolve through the defaults without migration.

## Rider self check-in

`POST /v1/tours/{tourId}/rides/{rideId}/self-checkins` is available only on Rider API and requires `SELF_CHECKIN`. The caller's rider ID is resolved from Cognito username through the rider link and profile to the tour's `TourRider` row. Missing link/profile/enrollment and `EXITED`/`WITHDRAWN` participation return `403 RIDER_NOT_IN_TOUR`. A client-supplied `riderId` is rejected.

The body contains exactly one of `stageNumber`, `isNotRiding: true`, or `isQuitRiding: true`, with optional ISO 8601 UTC `timestamp` and `notes`. The rider check-in is stored through the shared check-in create function with `method=SELF_SERVICE`, `checkedInBy=profileId`, and no float flag.

Checks run in this order: tour ACTIVE; caller is active on the tour; ride exists and is dated today in UTC; ride is OPEN or STARTED; no non-cancelled Quit Riding record exists; stage exists and is permitted, with PIT_STOP open; Not Riding is permitted and ride OPEN; Quit Riding is permitted and ride STARTED with no FINISH check-in; then all shared duplicate, sequence, and rider-state checks apply. See the [API reference](api-reference.md#check-ins) for exact error codes.

## Rider cancellation

`POST /v1/tours/{tourId}/rides/{rideId}/self-checkins/{checkInId}/cancel` applies the active tour, active rider, today's ride, and OPEN/STARTED checks. The check-in must belong to the caller; it may have been created by Rider or Management. Stage check-ins and Not Riding can be cancelled only if their calculated permission is still enabled. Cancellation uses the shared check-in cancel function and sets `cancelledBy` to the rider profile ID.

A Quit Riding check-in always returns `403 QUIT_RIDING_CANCEL_NOT_ALLOWED` on Rider API, regardless of configuration. Only Management can cancel it, so organisers can assess a rider before resuming participation. Redo is a new self check-in after cancellation.

## Rider read access

Rider API check-in list routes require the path `riderId` to match the login-resolved rider. A mismatch returns `403 NOT_OWN_DATA`. Management API list behavior is unchanged. Both lists exclude cancelled records, return an empty list when check-in data is absent, and include `method`, `checkedInBy`, stage fields, outcome flags, and timestamp.

See [RBAC](rbac.md), [Data model](data-model.md), [Core requirements](../requirements/core.md), and the [API reference](api-reference.md#check-ins).
