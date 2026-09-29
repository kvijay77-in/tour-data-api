# Tour Data API
_Last updated: 2026-09-29_

Backend API and infrastructure for the Cycling Tour Management Platform. This repository is the source of truth for API contracts, permissions, the data model, and all AWS resources used by the platform, including the management and rider Cognito user pools.

## Technology

- Python Lambda functions on AWS SAM and CloudFormation
- API Gateway HTTP APIs, DynamoDB, S3, Cognito, EventBridge, and CloudWatch
- GitHub Actions for tests, builds, and environment deployments

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
make check-config
make test
make build
```

See [Development](docs/guides/development.md) for local setup and [Deployment](docs/guides/deployment.md) for AWS configuration and deployment.

## Documentation

- [Documentation index](docs/README.md)
- [Requirements](docs/requirements/)
- [Architecture and design](docs/design/)
- [Development, deployment, and infrastructure guides](docs/guides/)
- [Historical reference material](docs/misc/)

## Related projects

- [Cycling Tour Management Platform](https://kvijay77-in.github.io/cycling-tour-platform/) · [repository](https://github.com/kvijay77-in/cycling-tour-platform)
- [Management app](https://github.com/kvijay77-in/tour-mgmt-app)
- [Rider app](https://github.com/kvijay77-in/tour-rider-app)
