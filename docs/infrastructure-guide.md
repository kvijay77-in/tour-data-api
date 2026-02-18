# Infrastructure Guide

[← Back to README](../README.md)

This guide covers resource tagging strategy, CloudWatch monitoring, cost estimation, and project statistics.

## Table of Contents
- [Resource Tagging Strategy](#resource-tagging-strategy)
- [Monitoring](#monitoring)
- [Cost Estimation](#cost-estimation)
- [Project Statistics](#project-statistics)

---

## Resource Tagging Strategy

All AWS resources created by this project are automatically tagged for cost tracking, management, and compliance.

### Standard Tags Applied to All Resources

| Tag Key | Tag Value | Purpose |
|---------|-----------|---------|
| `Project` | `tour-data-api` | Identify all resources belonging to this project |
| `Environment` | `dev` / `test` / `prod` | Distinguish between deployment environments |
| `ManagedBy` | `SAM` or `CloudFormation` | Indicate infrastructure-as-code tool |
| `Application` | `TourManagement` | Logical application grouping |
| `Owner` | (Configurable) | Team or individual responsible for the resources |
| `CostCenter` | (Configurable) | Your organization's cost center code |

### How to Configure Tags

Tags are defined in `template.yaml`. Standard tags are applied globally, and you can add custom tags via parameters.

#### Standard Tags (Applied Automatically)

```yaml
Globals:
  Function:
    Tags:
      Project: tour-data-api
      Environment: !Ref Environment
      Application: TourManagement
      ManagedBy: SAM
      Owner: !Ref Owner
      CostCenter: !Ref CostCenter
```

#### Adding Custom Tags During Deployment

You can provide custom tag values when deploying:

```bash
# Using sam deploy with custom tags
sam deploy --parameter-overrides \
  Environment=prod \
  Owner="DevOps Team" \
  CostCenter="CC-1234"

# Or configure in samconfig.toml for persistent values
```

#### Configure in samconfig.toml

Edit `samconfig.toml` to set persistent tag values for each environment:

```toml
# Development environment
[default.deploy.parameters]
capabilities = "CAPABILITY_IAM"
confirm_changeset = true
resolve_s3 = true
parameter_overrides = "Environment=dev Owner=\"DevTeam\" CostCenter=\"CC-1234\""

# Test environment
[test.deploy.parameters]
capabilities = "CAPABILITY_IAM"
confirm_changeset = true
resolve_s3 = true
parameter_overrides = "Environment=test Owner=\"QA Team\" CostCenter=\"CC-1234\""

# Production environment
[prod.deploy.parameters]
capabilities = "CAPABILITY_IAM"
confirm_changeset = true
parameter_overrides = "Environment=prod Owner=\"Operations Team\" CostCenter=\"CC-5678\""
```

> **Note**: When updating `samconfig.toml`, uncomment and modify the `parameter_overrides` line with your custom tag values.

### Adding Additional Custom Tags

If you need more tags beyond the standard ones:

#### 1. Add New Parameters in template.yaml

```yaml
Parameters:
  CustomTag1:
    Type: String
    Default: ''
    Description: Custom tag for your specific needs
```

#### 2. Add to Globals Section

```yaml
Globals:
  Function:
    Tags:
      CustomTag1: !Ref CustomTag1
```

#### 3. Deploy with Values

```bash
sam deploy --parameter-overrides CustomTag1="YourValue"
```

### Using Tags for Cost Analysis

#### 1. AWS Cost Explorer

Access via AWS Console:
1. Go to AWS Console → Cost Explorer
2. Click on **Filters**
3. Select **Tag** → Choose your tag (e.g., `Environment`)
4. View costs grouped by tag values

#### 2. AWS CLI - Get Costs by Tag

```bash
# Get monthly costs for dev environment
aws ce get-cost-and-usage \
  --time-period Start=2026-01-01,End=2026-01-31 \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --filter file://cost-filter.json
```

**cost-filter.json:**
```json
{
  "Tags": {
    "Key": "Environment",
    "Values": ["dev"]
  }
}
```

#### 3. Cost Allocation Tags

Enable tags for billing reports:

1. Go to **AWS Billing Console** → **Cost Allocation Tags**
2. Find your tags: `Project`, `Environment`, `Application`
3. Click **Activate** for each tag
4. Wait 24 hours for tags to appear in Cost Explorer

#### 4. Generate Cost Reports

List all resources by tag:

```bash
# List all resources for this project
aws resourcegroupstaggingapi get-resources \
  --tag-filters Key=Project,Values=tour-data-api \
  --resource-type-filters lambda dynamodb apigateway

# List resources by environment
aws resourcegroupstaggingapi get-resources \
  --tag-filters Key=Environment,Values=prod \
  --resource-type-filters lambda dynamodb apigateway s3

# Count resources by type
aws resourcegroupstaggingapi get-resources \
  --tag-filters Key=Project,Values=tour-data-api \
  --query 'ResourceTagMappingList[].ResourceARN' \
  --output text | wc -l
```

### Benefits of Tagging

- **Cost Tracking**: Analyze spending per environment (dev vs prod)
- **Resource Management**: Identify and clean up unused resources
- **Compliance**: Track resources for audit and governance requirements
- **Automation**: Bulk operations on tagged resources (backup, deletion, updates)
- **Budgeting**: Set budget alerts based on tag filters
- **Team Attribution**: Track which team owns which resources
- **Environment Isolation**: Clearly distinguish between dev/test/prod resources

> **Best Practice**: Update tags in `template.yaml` before deployment. Tags are applied during stack creation/update and automatically propagate to all resources.

---

## Monitoring

### CloudWatch Logs

Each Lambda function logs to CloudWatch with its own log group.

#### View Logs for a Function

```bash
# View logs for a specific function
make logs FUNCTION=GetActiveTourFunction

# Tail logs in real-time (alias)
make logs-tail FUNCTION=CreateCheckInFunction

# Alternative using logs-function target
make logs-function FUNCTION=GetRideCheckInsFunction
```

#### Using AWS CLI

```bash
# List log groups
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/tour-data-api

# Get recent log events
aws logs tail /aws/lambda/tour-data-api-GetActiveTourFunction --follow

# Filter logs by pattern
aws logs filter-log-events \
  --log-group-name /aws/lambda/tour-data-api-CreateCheckinFunction \
  --filter-pattern "ERROR"
```

#### Log Retention

Default retention: 7 days (configurable in `template.yaml`)

To change retention:
```yaml
Resources:
  YourFunctionLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: !Sub /aws/lambda/${YourFunction}
      RetentionInDays: 30  # 1, 3, 5, 7, 14, 30, 60, 90, 120, 180, 365, etc.
```

### CloudWatch Metrics

Monitor Lambda performance and API Gateway metrics.

#### Lambda Metrics

Available metrics:
- **Invocations**: Number of times function is invoked
- **Errors**: Number of invocations that resulted in errors
- **Duration**: Execution time
- **Throttles**: Number of throttled invocations
- **ConcurrentExecutions**: Number of concurrent executions

#### View Metrics in AWS Console

1. Go to **CloudWatch** → **Metrics**
2. Select **Lambda** namespace
3. Choose your function
4. View metrics over time

#### Create CloudWatch Alarms

Monitor critical metrics:

```bash
# Create alarm for Lambda errors
aws cloudwatch put-metric-alarm \
  --alarm-name tour-data-api-lambda-errors \
  --alarm-description "Alert when Lambda errors exceed threshold" \
  --metric-name Errors \
  --namespace AWS/Lambda \
  --statistic Sum \
  --period 300 \
  --threshold 5 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 1 \
  --dimensions Name=FunctionName,Value=tour-data-api-CreateCheckinFunction
```

#### API Gateway Metrics

Available metrics:
- **Count**: Total API requests
- **4XXError**: Client errors (authentication, validation)
- **5XXError**: Server errors (Lambda errors, timeouts)
- **Latency**: API response time
- **IntegrationLatency**: Lambda execution time

### X-Ray Tracing (Optional)

Enable AWS X-Ray for detailed tracing:

```yaml
Globals:
  Function:
    Tracing: Active  # Enable X-Ray tracing
```

Benefits:
- Trace request flow across services
- Identify performance bottlenecks
- Debug distributed applications

---

## Cost Estimation

Expected monthly costs for typical usage (100 riders, 7-8 rides per tour, 5-year retention):

### Cost Breakdown by Service

| Service | Monthly Cost | Notes |
|---------|-------------|-------|
| **DynamoDB** | $2-5 | On-demand pricing, shared + tour-specific tables |
| **Lambda** | $0.50-1 | Free tier covers most usage (1M requests/month free) |
| **API Gateway HTTP API** | $0.50-1 | $1 per million requests |
| **S3** | $1-2 | Photo storage + archive exports, ~100 photos @ 500KB each |
| **CloudWatch** | $1-2 | Logs and metrics, 7-day retention |

### Total Estimated Cost

**$5-11 per month**

### Cost Factors

#### DynamoDB Costs
- **On-demand pricing**: Pay only for actual reads/writes
- **Storage**: $0.25/GB per month
- **Typical usage**: 10k reads, 5k writes per month across all tables
- **Hybrid table strategy**: Shared tables (RiderProfile, Tour) are always active; tour-specific tables only exist during active tours, reducing idle costs
- **Cost optimization**: Use on-demand mode for variable workloads; archive completed tours to delete unused tables

#### Lambda Costs
- **Free tier**: 1 million requests + 400,000 GB-seconds per month
- **Beyond free tier**: $0.20 per 1M requests + $0.00001667 per GB-second
- **Memory configuration**: 256-512 MB per function (configurable)
- **Typical usage**: Well within free tier limits

#### API Gateway Costs
- **HTTP API**: $1 per million requests (first million free for 12 months)
- **REST API**: More expensive ($3.50 per million)
- **Cost optimization**: Use HTTP API instead of REST API

#### S3 Costs
- **Storage**: $0.023/GB per month (first 50 TB)
- **Requests**: GET requests $0.0004/1000, PUT requests $0.005/1000
- **Data transfer**: Free within same region, charged for internet transfer
- **Typical usage**: 100 photos @ 500KB = ~50MB storage

#### CloudWatch Costs
- **Log ingestion**: $0.50/GB
- **Log storage**: $0.03/GB per month
- **Metrics**: First 10 custom metrics free
- **Typical usage**: ~1-2 GB logs per month with 7-day retention

### Cost Management Strategies

1. **Use Resource Tags**
   - Tag all resources with `Environment` and `Project`
   - Enable cost allocation tags in AWS Billing Console
   - Track costs per environment in Cost Explorer

2. **Set Up Budget Alerts**
   ```bash
   # Create budget for the project
   aws budgets create-budget \
     --account-id 123456789012 \
     --budget file://budget.json
   ```

3. **Monitor Costs Regularly**
   - Use AWS Cost Explorer with tag filters
   - Set up alerts when costs exceed thresholds
   - Review Cost and Usage Reports monthly

4. **Optimize Resources**
   - Use on-demand pricing for variable workloads
   - Implement CloudWatch log retention policies
   - Delete unused resources in dev/test environments
   - Use S3 lifecycle policies for old data

5. **Environment-Specific Costs**
   - **Dev**: Lower usage, can be shut down when not needed
   - **Test**: Moderate usage, periodic testing
   - **Prod**: Consistent usage, plan for growth

### Cost Tracking Example

```bash
# Get costs for the last 30 days filtered by project tag
aws ce get-cost-and-usage \
  --time-period Start=2026-01-01,End=2026-01-31 \
  --granularity DAILY \
  --metrics UnblendedCost \
  --group-by Type=TAG,Key=Project \
  --filter file://cost-filter.json

# cost-filter.json
{
  "Tags": {
    "Key": "Project",
    "Values": ["tour-data-api"]
  }
}
```

### Cost Optimization Tips

- **Lambda**: Optimize memory allocation (use AWS Lambda Power Tuning)
- **DynamoDB**: Use on-demand mode, optimize queries to reduce RCUs
- **Logs**: Set appropriate retention periods, delete old log groups
- **S3**: Use lifecycle policies, compress photos before upload
- **API Gateway**: Use HTTP API (cheaper than REST API)

For detailed cost tracking using tags, see [Resource Tagging Strategy](#resource-tagging-strategy).

---

## Project Statistics

### Lambda Functions

- **Total Functions**: 20
- **Categories**:
  - Tours: 5 functions (get_active, get_tour, list_tours, create_tour, archive_tour)
  - Riders: 4 functions (get_rider_profile, update_rider_profile, get_tour_riders, get_tour_rider)
  - Rides: 6 functions (get_todays_ride, get_ride, list_rides, create_ride, update_ride, close_ride)
  - Check-ins: 3 functions (create_checkin, get_ride_checkins, get_dashboard_data)
  - Users: 2 functions (get_current_user, list_tour_users)

### Data Storage

- **DynamoDB Tables (Hybrid Strategy)**:
  - **Shared (SAM-managed, 2 tables)**:
    - RiderProfile (with EmailIndex GSI)
    - Tour (with StatusIndex GSI)
  - **Tour-specific (runtime-provisioned per tour, 4 tables each)**:
    - TourRider-{tourId}
    - Ride-{tourId} (with DateIndex, StatusIndex GSIs)
    - CheckIn-{tourId} (with RideIndex GSI)
    - User-{tourId}

### API Endpoints

- **Total Endpoints**: 20
- **HTTP Methods**: GET, POST, PUT
- **Authentication**: JWT via AWS Cognito (conditional, enabled when CognitoUserPoolArn is provided)
- **API Prefix**: `/v1/`

### Shared Components

- **Common Utilities**: 5 modules
  - models.py - Data models and enums
  - validation.py - Input validation
  - response.py - API response utilities
  - dynamodb_utils.py - DynamoDB helpers (shared + tour-specific table support)
  - logger.py - Logging utilities

### Testing

- **Unit Tests**: Comprehensive test coverage
- **Test Framework**: pytest with moto for AWS mocking
- **Coverage Target**: 80%+ code coverage
- **CI/CD Integration**: Automated testing in GitHub Actions

### Infrastructure

- **Infrastructure as Code**: AWS SAM (CloudFormation)
- **Deployment**: Multi-environment (dev/test/prod)
- **CI/CD**: GitHub Actions with manual triggers
- **Monitoring**: CloudWatch Logs and Metrics

### Code Quality

- **Linting**: pylint
- **Formatting**: black
- **Python Version**: 3.11+
- **Package Management**: pip with requirements.txt

### Project Size

- **Source Code**: ~5,000+ lines of Python
- **Tests**: Comprehensive unit test suite
- **Documentation**: 8 markdown files
- **Configuration**: SAM template, samconfig.toml, Makefile

---

## Related Documentation

- [Deployment Guide](deployment-guide.md) - CI/CD pipeline and AWS resources
- [Development Guide](development-guide.md) - Local development and testing
- [AWS Setup Guide](aws-setup-guide.md) - AWS credentials and Cognito setup

---

[← Back to README](../README.md)
