# User management requirements
_Last updated: 2026-09-29_

This document is the source of truth for backend user and staff management requirements.

## Cognito identities

- The backend manages the platform Cognito infrastructure, including separate management and rider user pools.
- Management administrators must be able to create, list, update, enable, disable, and delete management Cognito users through protected APIs.
- User-management operations must enforce administrator authorization and must not expose passwords, tokens, or other credentials in API responses or logs.
- Cognito groups identify the user's platform role. Exact group and permission names are defined in [RBAC](../design/rbac.md).

## Tour-scoped staff assignments

- Tour staff assignments are stored separately from Cognito identities in the tour's `User` table.
- Authorized administrators must be able to create and update an assignment for a tour, including its role and applicable event, activity, stage, or hotel assignments.
- The backend validates referenced users and tour data when saving assignments.
- Event scan authorization may require both an API permission and a matching tour assignment.

See [API reference](../design/api-reference.md#users) for current management API contracts. Cognito setup and user provisioning are described in the [deployment guide](../guides/deployment.md#cognito-pools-test-users-and-groups).
