# Project structure
_Last updated: 2026-11-11_

The main source folders and application entry points are:

```text
tour-data-api/
├── .github/
│   ├── copilot-instructions.md
│   └── workflows/
│       └── ci-cd.yml
├── cloudformation/
│   ├── deploy-access.yaml
│   └── github-oidc.yaml
├── docs/
│   ├── design/
│   ├── guides/
│   ├── misc/
│   └── requirements/
├── events/
├── scripts/
│   └── simulate/
├── src/
│   ├── functions/
│   │   ├── artifacts/
│   │   ├── checkins/
│   │   ├── config/
│   │   ├── events/
│   │   ├── hotels/
│   │   ├── notifications/
│   │   ├── riders/
│   │   ├── rides/
│   │   ├── tours/
│   │   └── users/
│   └── layers/
│       └── common/
├── tests/
│   └── fixtures/
├── Makefile
├── README.md
├── requirements-dev.txt
├── samconfig.toml
└── template.yaml
```

## Source organization

- `src/functions/` groups Lambda handlers by API domain. `hotels/` also contains asynchronous hotel-upload processing handlers; `notifications/` contains inbox, rule, device, and push-sender handlers.
- `src/layers/common/` contains shared Python modules, including `checkin_service.py`, `event_engine.py`, `event_registration.py`, `event_self_service.py`, `handler_utils.py`, `notification_service.py`, `ownership.py`, `profile_schema.py`, `rbac.py`, `rider_identity.py`, `self_checkin_rules.py`, `self_service_policy.py`, and `tour_provisioning.py`.
- `cloudformation/` holds the manually deployed AWS access stacks (not part of the SAM application): `github-oidc.yaml` (GitHub OIDC provider) and `deploy-access.yaml` (per-environment deploy roles, policies, SAM artifacts bucket, Lambda permissions boundary). See the [AWS Deploy Access Setup](aws-deploy-access-setup.md) guide.
- `template.yaml` defines the API Gateway HTTP APIs, Lambda functions, shared DynamoDB resources, both Cognito pools, S3 buckets, IAM roles, and event-driven processing infrastructure.
- `src/layers/common/tour_provisioning.py` defines tour-specific DynamoDB table schemas; `scripts/provision_tour.py` and the tour API use that shared table specification.
- `events/` contains sample payloads for local Lambda invocation. `scripts/simulate/` contains data-generation tools and scenario files.
- `tests/` contains pytest tests and shared fixtures. See [Testing](../../tests/README.md).
- `docs/` is organized by documentation type. `docs/README.md` is the documentation index; requirements, design, and guides are kept in their respective folders. `docs/misc/` contains historical reference material only.

The tree is based on the current repository layout. Update this page when an approved code or documentation structure change is made.
