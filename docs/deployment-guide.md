# Deployment Guide

[← Back to README](../README.md)

This guide covers automated CI/CD deployment using GitHub Actions and multi-environment deployment to AWS. For local development setup and deploying the dev environment from your terminal, see the [Development Guide](development-guide.md).

## Table of Contents

- [Overview](#overview)
- [One-Time Setup: GitHub OIDC](#one-time-setup-github-oidc)
- [Deploying via GitHub Actions](#deploying-via-github-actions)
- [Deploying from Terminal](#deploying-from-terminal)
- [Environments Explained](#environments-explained)
- [What Happens When You Deploy](#what-happens-when-you-deploy)
- [After Deployment: Provisioning a Tour](#after-deployment-provisioning-a-tour)
- [After Deployment: Getting Your API URL](#after-deployment-getting-your-api-url)
- [AWS Resources Reference](#aws-resources-reference)
- [Advanced: Using an Existing Cognito User Pool](#advanced-using-an-existing-cognito-user-pool)
- [FAQ](#faq)
- [Troubleshooting](#troubleshooting)
- [Creating an AWS Deployment User](#creating-an-aws-deployment-user)

---

## Overview

Deploying means publishing the application to Amazon Web Services (AWS) so your apps can connect to it over the internet.

The recommended deployment method is **GitHub Actions** — a CI/CD pipeline that automatically runs tests, builds the application, and deploys it when you trigger a workflow. This works for all environments (dev, test, prod).

**Alternative**: You can also deploy directly from your terminal using SAM CLI. Developers typically use this for the dev environment (see [Development Guide → Deploy to Dev](development-guide.md#deploy-to-dev-environment)). For test and prod from terminal, see [Deploying from Terminal](#deploying-from-terminal).

---

## One-Time Setup: GitHub OIDC

GitHub Actions deploys to AWS using **OIDC (OpenID Connect)** — a secure, industry-standard method that eliminates the need for stored access keys.

### 1. Create the OIDC Connection

Run this command (it prompts for your GitHub username):

```bash
make setup-github-oidc
```

This creates an identity link between your GitHub repository and AWS account. At the end, it prints a **Role ARN** — copy it.

### 2. Add the Role ARN to GitHub

1. Go to your GitHub repository → **Settings**
2. In the left sidebar, click **Secrets and variables** → **Actions**
3. Click **New repository secret**
4. Name: `AWS_DEPLOY_ROLE_ARN`
5. Value: Paste the Role ARN from step 1
6. Click **Add secret**

GitHub Actions can now deploy to your AWS account securely, with no access keys to manage or rotate.

### For Production (Separate AWS Account)

If you use a separate AWS account for production:

1. Run `make setup-github-oidc` while authenticated to the **production** AWS account
2. Add the resulting Role ARN as `AWS_DEPLOY_ROLE_ARN_PROD` in GitHub Secrets

### Alternative: Static Access Keys

If you prefer static access keys instead of OIDC (less secure, not recommended):

| Secret Name | Value | Used For |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | Your AWS access key | Dev and test deployments |
| `AWS_SECRET_ACCESS_KEY` | Your AWS secret key | Dev and test deployments |

See [Creating an AWS Deployment User](#creating-an-aws-deployment-user) for how to create these credentials.

---

## Deploying via GitHub Actions

### Step-by-Step

1. Go to your GitHub repository → **Actions** tab
2. In the left sidebar, click **CI/CD Pipeline**
3. Click **Run workflow**
4. Select options:
   - **Branch**: `main` (latest stable code)
   - **Environment**: `dev`, `test`, or `prod`
5. Click the green **Run workflow** button to start

### Monitoring Progress

The pipeline runs three stages:

| Stage | What It Does | Duration |
|---|---|---|
| **Run Tests** | Code quality checks, linting, and automated unit tests | ~1-2 min |
| **Build Application** | Validates configuration and packages the code | ~1-2 min |
| **Deploy to [env]** | Creates/updates all AWS resources and publishes the API | ~3-5 min |

A green checkmark (✓) means success. A red X means something went wrong — see [Troubleshooting](#troubleshooting).

After successful deployment, the API endpoint URL appears in the deploy job output. See [Getting Your API URL](#after-deployment-getting-your-api-url).

---

## Deploying from Terminal

For deploying test and prod environments from your terminal. Dev environment deployment is covered in the [Development Guide](development-guide.md#deploy-to-dev-environment).

```bash
# Build first
sam build

# Deploy to test
sam deploy --config-env test

# Deploy to production
sam deploy --config-env prod
```

Using Make shortcuts:

```bash
make deploy-test     # Build and deploy to test
make deploy-prod     # Build and deploy to prod (asks for confirmation)
```

> **Prerequisites**: AWS CLI configured with credentials that have permission to deploy. See [AWS Setup Guide](aws-setup-guide.md) for configuration.

---

## Environments Explained

Three independent environments, each with their own AWS resources, databases, and API URL. Changes to one environment do **not** affect the others.

| Environment | Stack Name | Purpose |
|---|---|---|
| **dev** | `dev` | Development and experimentation |
| **test** | `test` | Staging and pre-production verification |
| **prod** | `prod` | Live production system used during tours |

Each environment gets its own API URL:
- Dev: `https://<id>.execute-api.<region>.amazonaws.com/dev/`
- Test: `https://<id>.execute-api.<region>.amazonaws.com/test/`
- Prod: `https://<id>.execute-api.<region>.amazonaws.com/prod/`

> **Recommendation**: Always deploy and verify in **dev** or **test** before deploying to **prod**.

---

## What Happens When You Deploy

### Stage 1: Tests (~1-2 min)

Runs automated checks. If any test fails, deployment **stops** and nothing changes in your live system.
- Code quality checks (linting)
- Code formatting verification
- Automated unit tests

### Stage 2: Build (~1-2 min)

Packages the application code:
- Validates the infrastructure configuration
- Bundles all 20 Lambda functions with their dependencies
- Prepares packages for upload to AWS

### Stage 3: Deploy to AWS (~3-5 min)

Creates or updates all required resources in your AWS account.

**First deployment creates:**

| Resource | Count | Purpose |
|---|---|---|
| API Gateway (HTTP API) | 1 | Receives requests from your apps |
| Cognito User Pool + App Client | 1 | User authentication (auto-created) |
| Lambda Functions | 20 | Business logic for each API endpoint |
| Lambda Layer | 1 | Shared utilities across all functions |
| DynamoDB Tables (shared) | 5 | RiderProfile, RiderTours, RiderCognitoUser, TourMaster, AppConfig |
| S3 Bucket | 1 | Rider photos and archived tour data |
| IAM Roles | 20 | Security permissions per function |
| CloudWatch Log Groups | 20 | Monitoring and debugging logs |
| JWT Authorizer | 1 | Validates user login tokens |

**Tour-specific tables** (created at runtime when a tour is created via `POST /v1/tours`):
- `TourRider-{tourId}` — Rider enrollment
- `Ride-{tourId}` — Daily rides and routes
- `CheckIn-{tourId}` — Check-in records
- `User-{tourId}` — Staff accounts

When a tour is archived, these tables can be exported and deleted to save costs.

**Subsequent deployments**: Only changed resources are updated. Databases and stored data are **never deleted** during updates.

---

## After Deployment: Provisioning a Tour

After the stack is deployed, tour-specific tables must be created before the tour can be used. There are two methods:

### Method 1: CLI Script (Deployment Method)

Use the provisioning script to create a tour and its tables directly from the command line. This is ideal for initial setup or automated deployment pipelines.

```bash
# Using Make target
make provision-tour \
  TOUR_ID=TOT-2026 \
  TOUR_NAME="Tour of Tamilnadu 2026" \
  START_DATE=2026-02-10 \
  END_DATE=2026-02-17

# Using Python script directly (more options available)
python scripts/provision_tour.py \
  --stack-name dev \
  --tour-id TOT-2026 \
  --name "Tour of Tamilnadu 2026" \
  --start-date 2026-02-10 \
  --end-date 2026-02-17 \
  --description "Season 2: Chera Nadu II" \
  --environment dev
```

For production environments:
```bash
make provision-tour \
  STACK_NAME=prod \
  TOUR_ID=TOT-2026 \
  TOUR_NAME="Tour of Tamilnadu 2026" \
  START_DATE=2026-02-10 \
  END_DATE=2026-02-17 \
  ENV=prod
```

The script creates the Tour record in the shared TourMaster table and provisions 5 tour-specific DynamoDB tables (TourRider, Ride, CheckIn, User, Notification).

### Method 2: API Endpoint (Runtime Method)

External applications (such as the Check-In App) can create tours programmatically via the API:

```bash
curl -X POST https://<api-url>/v1/tours \
  -H "Authorization: Bearer <jwt-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "tourId": "TOT-2026",
    "name": "Tour of Tamilnadu 2026",
    "startDate": "2026-02-10",
    "endDate": "2026-02-17",
    "description": "Season 2: Chera Nadu II"
  }'
```

Both methods produce the same result: a Tour record and 5 tour-specific DynamoDB tables.

> **Note**: The API method is designed for use by external apps like the Check-In App. The actual integration from these apps is out of scope for this project — this API capability is provided for their use.

---

## After Deployment: Getting Your API URL

### From GitHub Actions

1. Click on the completed **Deploy to [environment]** job
2. Expand the **Build and Deploy** step
3. Find the `api_endpoint` value in the output

### From Terminal

```bash
# Dev
aws cloudformation describe-stacks \
  --stack-name dev \
  --query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" \
  --output text

# Test
aws cloudformation describe-stacks \
  --stack-name test \
  --query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" \
  --output text

# Prod
aws cloudformation describe-stacks \
  --stack-name prod \
  --query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" \
  --output text
```

### Verify

```bash
curl <api-url>/v1/tours
```

An "Unauthorized" response means the API is running and authentication is working correctly. See [AWS Setup Guide → Get JWT Token](aws-setup-guide.md#3-get-jwt-token-for-testing) for generating test tokens.

---

## AWS Resources Reference

Detailed inventory of everything deployment creates in your AWS account.

### Lambda Functions (All 25)

| Function | Endpoint | Purpose |
|---|---|---|
| GetActiveTourFunction | `GET /v1/tours/active` | Get currently active tour |
| GetTourFunction | `GET /v1/tours/{tourId}` | Get tour details |
| ListToursFunction | `GET /v1/tours` | List all tours |
| CreateTourFunction | `POST /v1/tours` | Create tour and provision tables |
| ArchiveTourFunction | `POST /v1/tours/{tourId}/archive` | Archive completed tour |
| GetRiderProfileFunction | `GET /v1/riders/profile/{profileId}` | Get rider profile |
| ListRiderTourParticipationsFunction | `GET /v1/profile/{profileId}/tours` | List rider participation details across all tours for a profile |
| GetRiderTourParticipationFunction | `GET /v1/profile/{profileId}/tours/{tourId}` | Get rider participation details for one tour |
| UpdateRiderProfileFunction | `PUT /v1/riders/profile/{profileId}` | Update rider profile |
| GetTourRidersFunction | `GET /v1/tours/{tourId}/riders` | List tour riders |
| GetTourRiderNamesFunction | `GET /v1/tours/{tourId}/riders/names` | List tour riders with riderId and name only |
| GetTourRiderByIdFunction | `GET /v1/tours/{tourId}/riders/{riderId}` | Get specific tour rider |
| GetTodaysRideFunction | `GET /v1/tours/{tourId}/rides/today` | Get today's ride |
| GetRideFunction | `GET /v1/tours/{tourId}/rides/{rideId}` | Get ride details |
| ListRidesFunction | `GET /v1/tours/{tourId}/rides` | List all rides |
| CreateRideFunction | `POST /v1/tours/{tourId}/rides` | Create a ride |
| UpdateRideFunction | `PUT /v1/tours/{tourId}/rides/{rideId}` | Update ride details |
| OpenRideFunction | `POST /v1/tours/{tourId}/rides/open` | Open today's ride |
| StartRideFunction | `POST /v1/tours/{tourId}/rides/start` | Start today's ride |
| CloseRideFunction | `POST /v1/tours/{tourId}/rides/{rideId}/close` | Close a ride |
| CreateCheckInFunction | `POST /v1/tours/{tourId}/checkins` | Record check-in |
| GetRideCheckInsFunction | `GET /v1/tours/{tourId}/rides/{rideId}/checkins` | Get ride check-ins |
| GetDashboardDataFunction | `GET /v1/tours/{tourId}/rides/{rideId}/dashboard` | Live dashboard data |
| GetCurrentUserFunction | `GET /v1/users/me` | Current user info |
| ListTourUsersFunction | `GET /v1/tours/{tourId}/users` | List tour staff |

### Database Tables

**Shared tables (created during deployment):**

| Table | Full Table Name | Stores | Persists Across Tours? |
|---|---|---|---|
| RiderProfile | `dev-RiderProfile` | Rider personal info (name, email, emergency contacts) | Yes |
| RiderTours | `dev-RiderTours` | Rider participation lifecycle keyed by profileId + tourId | Yes |
| RiderCognitoUser | `dev-RiderCognitoUser` | Mapping from Cognito username to profileId | Yes |
| TourMaster | `dev-TourMaster` | Tour details (name, dates, status) | Yes |
| AppConfig | `dev-AppConfig` | Shared app configuration values | Yes |

**Tour-specific tables (created per tour via API):**

| Table Pattern | Stores | Example |
|---|---|---|
| TourRider-{tourId} | Rider enrollment | `dev-TourRider-TOT-2026` |
| Ride-{tourId} | Ride schedule and routes | `dev-Ride-TOT-2026` |
| CheckIn-{tourId} | Check-in records | `dev-CheckIn-TOT-2026` |
| User-{tourId} | Staff accounts | `dev-User-TOT-2026` |

---

## Advanced: Using an Existing Cognito User Pool

By default, deployment creates a Cognito User Pool and App Client. To use an existing one instead, add these to `parameter_overrides` in `samconfig.toml`:

```toml
parameter_overrides = "Environment=dev CognitoUserPoolArn=arn:aws:cognito-idp:us-east-1:123456789012:userpool/us-east-1_AbCdEfGhI CognitoAppClientId=1a2b3c4d5e6f7g8h9i0j"
```

When `CognitoUserPoolArn` is provided, auto-creation is skipped and the specified User Pool is used instead.

---

## FAQ

**Q: How long does a deployment take?**
A: About 5-10 minutes total (tests + build + deploy). The first deployment takes slightly longer because everything is created from scratch.

**Q: Will deployment affect my existing data?**
A: No. Deployments only update application code and infrastructure configuration. Tour data, rider profiles, and check-in records are preserved.

**Q: Can I roll back if something goes wrong?**
A: Yes. AWS CloudFormation tracks every deployment. If a deployment fails partway through, it automatically rolls back to the previous working state.

**Q: How much does it cost to run?**
A: The system uses a pay-per-use model. For a typical cycling tour (~100 riders, 7-8 rides), estimated costs are very low (under $5/month). See the [Infrastructure Guide](infrastructure-guide.md) for detailed cost estimates.

**Q: Can I deploy to multiple environments simultaneously?**
A: Yes. Each environment is independent. You can deploy to `dev` and `prod` at the same time without them affecting each other.

**Q: Do I need to deploy every time I create a new tour?**
A: No. Tour creation happens through the API (`POST /v1/tours`) or the CLI provisioning script (`make provision-tour`) — once the system is deployed, you create tours without redeploying. Deployment is only needed when the application code changes.

---

## Troubleshooting

### Deployment Failed at "Run Tests"

An automated test encountered an error.

1. Click on the failed job in GitHub Actions
2. Read the error message — it identifies what failed
3. If code was recently changed, review those changes
4. Run tests locally to reproduce: `make test`

### Deployment Failed at "Build"

The configuration (template.yaml) has an error.

1. Check the error details in the failed job
2. Run locally: `sam validate --lint`
3. Common cause: syntax errors in configuration files

### Deployment Failed at "Deploy"

AWS couldn't create or update a resource.

1. Check the error message in the deploy output
2. Common causes:
   - **Missing permissions**: AWS user or OIDC role needs sufficient permissions
   - **Resource limit**: Hit an AWS service limit — contact AWS support
   - **Region mismatch**: Region in `samconfig.toml` doesn't match AWS configuration

### "Unauthorized" Error When Calling the API

The API is working but requires authentication. Get a JWT token from Cognito and include it in your request. See [AWS Setup Guide → Get JWT Token](aws-setup-guide.md#3-get-jwt-token-for-testing).

### "Stack already exists" Error

This is normal — subsequent deployments update the existing stack. To start completely fresh:

```bash
# Recommended: use make delete (cleans up tour tables + deletes stack)
make delete

# Or manually: first clean tour-specific tables, then delete the stack
python scripts/cleanup_tour_tables.py --stack-name dev --confirm
sam delete --stack-name dev
```

> **Note:** `sam delete` only removes CloudFormation-managed resources. Tour-specific DynamoDB
> tables (TourRider, Ride, CheckIn, User) are created at runtime and must be cleaned up
> separately. The `make delete` target handles both steps automatically.
>
> To preview which tour tables exist without deleting them:
> ```bash
> python scripts/cleanup_tour_tables.py --stack-name dev
> ```

---

## Creating an AWS Deployment User

For GitHub Actions with **static access keys** (alternative to OIDC).

### Create the User

```bash
aws iam create-user --user-name github-actions-deployer
```

### Attach Permissions

```bash
# CloudFormation — create/update deployment stacks
aws iam attach-user-policy --user-name github-actions-deployer \
  --policy-arn arn:aws:iam::aws:policy/AWSCloudFormationFullAccess

# IAM — create execution roles for Lambda functions
aws iam attach-user-policy --user-name github-actions-deployer \
  --policy-arn arn:aws:iam::aws:policy/IAMFullAccess

# S3 — upload deployment packages
aws iam attach-user-policy --user-name github-actions-deployer \
  --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess

# Lambda — create/update functions
aws iam attach-user-policy --user-name github-actions-deployer \
  --policy-arn arn:aws:iam::aws:policy/AWSLambda_FullAccess

# API Gateway — create/update API endpoints
aws iam attach-user-policy --user-name github-actions-deployer \
  --policy-arn arn:aws:iam::aws:policy/AmazonAPIGatewayAdministrator

# DynamoDB — create/update database tables
aws iam attach-user-policy --user-name github-actions-deployer \
  --policy-arn arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess
```

### Generate Access Keys

```bash
aws iam create-access-key --user-name github-actions-deployer
```

Save the `AccessKeyId` and `SecretAccessKey` — the secret is only shown once.

Add to GitHub Secrets:
- `AccessKeyId` → `AWS_ACCESS_KEY_ID`
- `SecretAccessKey` → `AWS_SECRET_ACCESS_KEY`

> **Security**: For production, create a separate deployment user and store credentials as `AWS_ACCESS_KEY_ID_PROD` and `AWS_SECRET_ACCESS_KEY_PROD` in GitHub Secrets.

---

## Related Documentation

- [Development Guide](development-guide.md) — Local development, testing, deploying dev environment
- [AWS Setup Guide](aws-setup-guide.md) — AWS credentials, Cognito setup, JWT tokens
- [Infrastructure Guide](infrastructure-guide.md) — Resource tagging, monitoring, cost estimation

---

[← Back to README](../README.md)
