# Role-based access control
_Last updated: 2026-09-29_

## Source of truth

`src/layers/common/rbac.py` is authoritative for backend permission names, group mappings, and dynamic pit-stop group behavior. Lambda handlers request API-level permissions; they do not authorize by comparing user-facing role names directly. API endpoints and their required permissions are listed in the [API reference](api-reference.md).

## Permission names

Use these exact permission values from the `Permission` enum:

`READ`, `CHECKIN`, `CHECKIN_MANUAL`, `SELF_CHECKIN`, `RIDE_MANAGE`, `PIT_STOP_MANAGE`, `TOUR_MANAGE`, `USER_LIST`, `DASHBOARD`, `NOTIFICATION_MANAGE`, `RIDER_EXIT`, `ARTIFACT_MANAGE`, `RIDER_SELF_UPDATE`, `EVENT_MANAGE`, `EVENT_OCCURRENCE_MANAGE`, `EVENT_SCAN`, `EVENT_REGISTRATION_MANAGE`, `HOTEL_ALLOC_MANAGE`, and `USER_MANAGE`.

## Default group mapping

| Cognito group | Permissions |
|---|---|
| `ADMINISTRATOR` | All permissions listed above |
| `SUPER_USER` | `READ`, `CHECKIN`, `CHECKIN_MANUAL`, `PIT_STOP_MANAGE`, `USER_LIST`, `DASHBOARD`, `RIDER_EXIT`, `EVENT_OCCURRENCE_MANAGE`, `EVENT_SCAN`, `HOTEL_ALLOC_MANAGE` |
| `PS_<n>_USER` | `READ`, `CHECKIN`, `PIT_STOP_MANAGE`, `DASHBOARD`, `EVENT_SCAN` |
| `HOTEL_STAFF` | `READ`, `CHECKIN`, `EVENT_SCAN` |
| `GUEST` | `READ`, `DASHBOARD` |
| `RIDER` | `READ`, `RIDER_SELF_UPDATE`, `SELF_CHECKIN` |

`PS_<n>_USER` is a dynamic group-name pattern. The deployment currently creates `PS_1_USER` through `PS_5_USER`; backend permission resolution recognizes valid numeric suffixes without code changes.

## Pit-stop stage restrictions

For regular check-ins and pit-stop open/close actions, a `PS_<n>_USER` is restricted to pit-stop stage `n`. A matching group does not authorize a `START` or `FINISH` stage. A user can hold multiple pit-stop groups. `ADMINISTRATOR` and `SUPER_USER` can manage any pit-stop stage. Any pit-stop group may submit a `Quit Riding` check-in regardless of its assigned stage.

## Permission resolution

The default effective-group priority is `ADMINISTRATOR`, `SUPER_USER`, the first pit-stop group in the claims, `HOTEL_STAFF`, then `GUEST`. When none of these priority groups is present, mapped non-priority groups use the compatibility union behavior in `get_user_permissions()`. Event scans may also be subject to tour assignment, assigned-activity, and hotel-match checks implemented by `require_event_assignment_access()`.

## Cognito ownership

The backend SAM template creates and manages both platform pools: the management pool and the rider pool. The management pool is configurable to use an existing pool through the template parameters; the rider pool and its `RIDER` group are also defined in `template.yaml`. Cognito group creation and pool ownership are detailed in the [deployment guide](../guides/deployment.md#cognito-pools-test-users-and-groups).
