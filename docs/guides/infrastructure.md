# Infrastructure guide
_Last updated: 2026-10-04_

## Ownership

This repository owns the backend AWS infrastructure for the Cycling Tour Management Platform, including both Cognito user pools, API Gateway HTTP APIs, Lambda functions and layers, DynamoDB tables, private file buckets, EventBridge rules, SQS dead-letter queues, backend IAM roles, and CloudWatch monitoring. The management app repository owns its separate SAM static web-hosting stack and distinct bootstrap, infrastructure, and publisher identities. The existing account-level GitHub OIDC provider remains under its current stack ownership; the app publisher uses a separate scoped role. The app hosting stack does not replace or own backend resources.

The primary infrastructure definition is `/template.yaml`; the GitHub OIDC bootstrap is `cloudformation/github-oidc.yaml`. Runtime tour-table creation and cleanup are managed by `src/layers/common/tour_provisioning.py` and the scripts in `scripts/`.

### Management web origin inputs

`ManagementWebAllowedOrigins` is an optional comma-separated list of complete browser origins. `scripts/deploy_backend.py` resolves the hosting stack's `SiteUrl` read-only and combines it with explicitly approved additions and origins already stored on the backend stack. Its inputs are the app stack name and region, expected backend account/region, enable/disable approval, and optional additional origins; the default hosting stack names are `tour-mgmt-web-dev` and `tour-mgmt-web-prod`. The `Project` and `Environment` tags and stable stack status are validated before SAM deployment. Origins are scheme/host/port only; paths, wildcards, malformed values, insecure Production origins, and unapproved localhost values are rejected. Empty configuration preserves the existing management API wildcard behavior and does not configure S3 CORS. Enabled configuration applies separately to `TourDataApi` and the private artifact bucket; it does not narrow `RiderApi` or grant API/S3 authorization.

## Tagging

The SAM template defines common tags, including `Project`, `Environment`, `Application`, `ManagedBy`, and `SubscriptionId`, and applies resource-specific tags where declared. `ResourceOwner` is used by selected resources. Runtime-provisioned tour tables are tagged by the provisioning code with project, environment, application, management, and optional subscription metadata. The GitHub OIDC bootstrap stack has its own tags.

Check `template.yaml`, `cloudformation/github-oidc.yaml`, and `src/layers/common/tour_provisioning.py` when changing tagging behavior; not every AWS resource type supports identical stack-level tag propagation. Review newly added resources for the project and environment tags required for cost attribution.

For cost reports, activate the applicable cost-allocation tags in the AWS Billing console. Use the AWS Resource Groups Tagging API to inspect tagged resources:

```bash
aws resourcegroupstaggingapi get-resources \
  --tag-filters Key=Project,Values=tour-data-api
```

## Monitoring and operations

- Lambda logs are available in CloudWatch Logs. Use `make logs FUNCTION=<LambdaFunctionName>` to tail a function's logs.
- Review Lambda `Invocations`, `Errors`, `Duration`, `Throttles`, and concurrent execution metrics, along with API Gateway request, 4xx/5xx, and latency metrics.
- The template defines CloudWatch alarms for notification push sender and hotel-upload processing failures. Inspect those alarms and `PushSenderDlq` when async delivery or processing fails.
- Hotel upload outcomes and row-level validation errors are stored in upload status records; clients poll the upload-status API.
- Notification push credentials are stored as SSM SecureString parameters. Follow the [deployment guide](deployment.md#after-deployment-notification-push-setup) to configure and rotate them.
- Log retention should be reviewed against account requirements and cost. Do not assume a retention period unless it is explicitly configured for the resource.

## Cost management

Costs vary by account, region, traffic, retained data, logging volume, and S3 transfer. Monitor actual usage with AWS Cost Explorer and the Billing console instead of treating an estimate as a fixed charge.

Primary cost controls:

- DynamoDB tables use on-demand billing in the SAM template and runtime provisioning definitions.
- Keep tour-specific tables only while needed; use the tour archive and cleanup workflows deliberately and retain exports according to the data-retention policy.
- Set an appropriate CloudWatch Logs retention policy for deployed environments and avoid verbose or sensitive log output.
- Review S3 object retention, uploads, and data transfer. The artifact and rider-photo buckets are private; hotel allocation uploads also use the artifact bucket.
- Use resource tags to compare usage by project, environment, and subscription where applicable.
- Review Lambda duration/memory, API request volume, and asynchronous retry/DLQ metrics before changing resource settings.

See [Data model](../design/data-model.md) for table scope and [Deployment](deployment.md) for environments and resource setup.
