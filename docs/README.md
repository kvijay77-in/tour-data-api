# Documentation index
_Last updated: 2026-10-01_

This index links to the current backend requirements, designs, and operating guides.

## Requirements

| Document | Scope |
|---|---|
| [Core](requirements/core.md) | Tour, ride, check-in, isolation, and operating requirements |
| [Events and hotel logistics](requirements/events.md) | Event activities, baggage custody, and room allocations |
| [User management](requirements/user-management.md) | Cognito users and tour-scoped staff assignments |
| [Rider profile](requirements/rider-profile.md) | Profile definitions, ownership, and participation |
| [Notifications](requirements/notifications.md) | Inbox, announcements, reminders, and push |
| [Tour artifacts](requirements/artifacts.md) | Configurable tour- and ride-level files |
| [Dashboard API](requirements/dashboard.md) | Initial dashboard load, progress refresh, and rider details |

Requirements are maintained only in `docs/requirements/`. Their implementation contracts are linked from the relevant design documents.

## Design

| Document | Scope |
|---|---|
| [Architecture](design/architecture.md) | System boundaries, data flow, and AWS service roles |
| [Data model](design/data-model.md) | Shared and tour-specific DynamoDB tables |
| [Check-ins](design/check-ins.md) | Ride check-in policy, Rider self-service, and cancellation safety |
| [API reference](design/api-reference.md) | Single source of truth for backend API contracts |
| [RBAC](design/rbac.md) | Permission names, Cognito groups, and authorization rules |
| [Events and hotel logistics](design/events.md) | Event, baggage, hotel, and allocation design |
| [Notifications](design/notifications.md) | Inbox routing, notification persistence, and push delivery |
| [Tour artifacts](design/artifacts.md) | Private S3 storage and metadata design |
| [Rider profile schema](design/rider-profile-schema.md) | Configurable profile attributes and access control |
| [Dashboard API](design/dashboard-api.md) | Dashboard endpoint responsibilities and refresh design |

Frontend screen designs are maintained in the management and rider app repositories. The platform glossary is maintained in the [platform repository](https://github.com/kvijay77-in/cycling-tour-platform/blob/main/docs/glossary.md).

## Guides

| Document | Scope |
|---|---|
| [Development](guides/development.md) | Environment setup, local development, tests, and commands |
| [Deployment](guides/deployment.md) | AWS setup, Cognito, GitHub OIDC, environments, and deployment |
| [Infrastructure](guides/infrastructure.md) | AWS ownership, tags, monitoring, and cost management |
| [Project structure](guides/project-structure.md) | Current repository folders and code organization |

## Historical references

Archived handoffs, proposals, change requests, and the prior TODO log are in [misc](misc/). For current behavior, use the requirements, design, and guide pages above.

## Application testing references

- [Simulation scripts](../scripts/simulate/README.md)
- [Test suite](../tests/README.md)
