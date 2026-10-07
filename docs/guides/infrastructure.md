# Infrastructure guide
_Last updated: 2026-09-29_

## Ownership

This repository owns and manages **all AWS infrastructure for the entire Cycling Tour Management Platform**, including resources used by both the management and rider apps. This includes both Cognito user pools, API Gateway HTTP APIs, Lambda functions and layers, DynamoDB tables, S3 buckets, EventBridge rules, SQS dead-letter queues, IAM roles, and CloudWatch monitoring. App repositories do not own platform AWS infrastructure.

The primary infrastructure definition is `/template.yaml`; the GitHub OIDC bootstrap is `cloudformation/github-oidc.yaml`. Runtime tour-table creation and cleanup are managed by `src/layers/common/tour_provisioning.py` and the scripts in `scripts/`.

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
