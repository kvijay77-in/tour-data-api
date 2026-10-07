# Deployment Guide
_Last updated: 2026-10-01_

[← Back to README](../README.md)

This guide covers AWS access and Cognito setup, GitHub Actions deployment, and the dev/test/prod environments. For local development, see the [Development Guide](development.md).

## Table of Contents

- [Overview](#overview)
- [One-Time Setup: GitHub OIDC](#one-time-setup-github-oidc)
- [Deploying via GitHub Actions](#deploying-via-github-actions)
- [Deploying from Terminal](#deploying-from-terminal)
- [Environments Explained](#environments-explained)
- [What Happens When You Deploy](#what-happens-when-you-deploy)
- [After Deployment: Provisioning a Tour](#after-deployment-provisioning-a-tour)
- [After Deployment: Notification Push Setup](#after-deployment-notification-push-setup)
- [After Deployment: Getting Your API URL](#after-deployment-getting-your-api-url)
- [AWS Resources Reference](#aws-resources-reference)
- [Advanced: Using an existing management Cognito pool](#advanced-using-an-existing-management-cognito-pool)
- [FAQ](#faq)
- [Troubleshooting](#troubleshooting)
- [AWS credentials and region](#aws-credentials-and-region)
- [Cognito pools, test users, and groups](#cognito-pools-test-users-and-groups)

---

## Overview

Deploying means publishing the application to Amazon Web Services (AWS) so your apps can connect to it over the internet.

The recommended deployment method is **GitHub Actions** — a CI/CD pipeline that automatically runs tests, builds the application, and deploys it when you trigger a workflow. This works for all environments (dev, test, prod).

**Alternative**: You can also deploy directly from your terminal using SAM CLI. Developers typically use this for the dev environment (see [Development Guide → Deploy to Dev](development.md#deploy-to-dev-environment)). For test and prod from terminal, see [Deploying from Terminal](#deploying-from-terminal).

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

Use credentials issued through your organization's approved least-privilege process, store them only as GitHub Actions secrets, and continue to prefer OIDC where possible.

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

For deploying test and prod environments from your terminal. Dev environment deployment is covered in the [Development Guide](development.md#deploy-to-dev-environment).

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

> **Prerequisites**: AWS CLI configured for the target account and region with permission to deploy. See [AWS credentials and region](#aws-credentials-and-region).

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

## AWS credentials and region

Use AWS IAM Identity Center (SSO) or another approved short-lived credential mechanism when available. AWS CLI and SAM CLI use the same active credentials:

```bash
aws configure sso
aws sso login --profile <profile-name>
aws sts get-caller-identity --profile <profile-name>
```

For temporary credentials from an assumed role, set the returned `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_SESSION_TOKEN` in the current shell. Do not commit credentials or place secrets directly in command history. GitHub deployments should use OIDC rather than long-lived keys.

The AWS region is pinned to `ap-south-1` in `samconfig.toml` (all config-envs) and in the GitHub Actions workflow (`AWS_REGION`). Verify the active account before deployment.

## Management web CORS

The `ManagementWebAllowedOrigins` parameter (comma-separated origins) restricts CORS on the management HTTP API and the artifacts bucket. Set it per config-env in `samconfig.toml` `parameter_overrides` (`[default]` is the dev stack, plus `[test]` and `[prod]`). Empty keeps the wildcard policy.

- The hosting stack `tour-mgmt-web-<env>` is owned and deployed by `tour-mgmt-app`.
- Redeploy the backend only when the site URL changes (for example, the hosting stack is recreated).
- Dev allows the deployed Dev site origin and `http://localhost:8081` (Expo web dev). Test keeps the wildcard.
- Prod allows https origins only, no localhost.

### Dev verification

After `make deploy-dev`, the changeset must modify only `TourDataApi` and `ArtifactsBucket` (no replacement). Verify with `curl`:

- API preflight (`OPTIONS`) with the site origin, `Access-Control-Request-Method: GET`, and request headers `authorization,content-type,if-none-match` returns that origin in `access-control-allow-origin`; an unlisted origin returns none.
- An authorized `GET` with the site origin exposes `etag` in `access-control-expose-headers`.
- Artifacts bucket preflight with request method `PUT` and header `content-type` is allowed.
- RiderApi preflight is unchanged (wildcard).

Verified 2026-10-07 (dev): all five checks passed (allowed-origin preflight, disallowed-origin preflight, `etag` exposed on an authorized GET, artifacts bucket `PUT` preflight, RiderApi wildcard unchanged).

### TODO Items

#### Hardcoded Origins and Region

Origins are hardcoded in `samconfig.toml` by owner decision (2026-10-07), an exception to the no-hardcoding rule. TODO: move them to a GitHub Environment variable.

The region (`ap-south-1`) is likewise hardcoded in `samconfig.toml` and `ci-cd.yml`. TODO: move it to a GitHub Environment variable.

#### Prod management web CORS

Deferred until the Mgmt App production deployment, which is scheduled only after full user testing succeeds. Then:

1. Get the Prod site origin (https only, no localhost) from the `tour-mgmt-web-prod` hosting stack.
2. In `samconfig.toml` `[prod.deploy.parameters]`, add `ManagementWebAllowedOrigins=\"<Prod site origin>\"` to `parameter_overrides`.
3. Run `make deploy-prod` with the usual approval. The changeset must modify only `TourDataApi` and `ArtifactsBucket`.
4. Repeat the [Dev verification](#dev-verification) checks against prod and record the date and results here.

## Cognito pools, test users, and groups

The backend template owns both Cognito pools:

- **Management pool** (`{stack}-mgmt-users`): used by management APIs. By default, SAM creates the pool and app client. `CognitoUserPoolArn` and `CognitoAppClientId` can instead point the management API at an existing pool/client.
- **Rider pool** (`{stack}-rider-users`): created and managed by this backend for the Rider API. It has its own app client and the `RIDER` group.

When the management pool is created by this stack, it creates `ADMINISTRATOR`, `SUPER_USER`, `HOTEL_STAFF`, `GUEST`, and the initial pit-stop groups `PS_1_USER` through `PS_5_USER`. If you configure an existing management pool, its groups must be managed outside this template. Backend authorization accepts valid `PS_<n>_USER` names even when the numeric suffix is not one of the initial groups. Exact permission mappings are in [RBAC](../design/rbac.md).

After deployment, retrieve the pool and app client IDs from these CloudFormation outputs:

| Purpose | Pool ID output | App client ID output |
|---|---|---|
| Management | `CognitoUserPoolIdOutput` | `CognitoAppClientIdOutput` |
| Rider | `CognitoRiderUserPoolIdOutput` | `CognitoRiderAppClientIdOutput` |

The management outputs are omitted when an existing management pool and app client are configured; use the supplied IDs instead. The rider pool and client are always created by this backend. Create a management test user and set a permanent password:

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <management-pool-id> \
  --username <test-user> \
  --user-attributes Name=email,Value=<test-user-email> \
  --message-action SUPPRESS

read -r -s -p "Test-user password: " TEST_USER_PASSWORD
printf '\n'
aws cognito-idp admin-set-user-password \
  --user-pool-id <management-pool-id> \
  --username <test-user> \
  --password "$TEST_USER_PASSWORD" \
  --permanent
unset TEST_USER_PASSWORD
```

Assign the management user to the appropriate group:

```bash
aws cognito-idp admin-add-user-to-group \
  --user-pool-id <management-pool-id> \
  --username <test-user> \
  --group-name ADMINISTRATOR
```

The rider pool's corresponding group is `RIDER`:

```bash
aws cognito-idp admin-add-user-to-group \
  --user-pool-id <rider-pool-id> \
  --username <test-user> \
  --group-name RIDER
```

Use the matching pool's app client to obtain an ID token for API testing. The app client must allow `USER_PASSWORD_AUTH`; this backend's generated app clients do. For a management test user, set `MANAGEMENT_APP_CLIENT_ID` to the `CognitoAppClientIdOutput` value (or the supplied client ID), then run:

```bash
read -r -p "Test username: " TEST_USER
read -r -s -p "Test password: " TEST_USER_PASSWORD
printf '\n'
ID_TOKEN=$(aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id "$MANAGEMENT_APP_CLIENT_ID" \
  --auth-parameters "USERNAME=$TEST_USER,PASSWORD=$TEST_USER_PASSWORD" \
  --query 'AuthenticationResult.IdToken' \
  --output text)
unset TEST_USER_PASSWORD
```

Send the ID token in the `Authorization` header when calling the API. Do not create a separate rider user pool in an app repository.

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
- Bundles the Lambda functions with their dependencies
- Prepares packages for upload to AWS

### Stage 3: Deploy to AWS (~3-5 min)

Creates or updates all required resources in your AWS account.

**First deployment creates:**

| Resource | Count | Purpose |
|---|---|---|
| API Gateway (HTTP API) | 1 | Receives requests from your apps |
| Cognito User Pools + App Clients | 2 | Management and rider authentication (both managed by this backend) |
| Lambda Functions | Multiple | Business logic for each API endpoint |
| Lambda Layer | 1 | Shared utilities across all functions |
| DynamoDB Tables (shared) | 10 | RiderProfile, RiderTours, RiderCognitoUser, TourMaster, AppConfig, NotificationRule, RiderNotification, MgmtNotification, RiderPushDevice, MgmtPushDevice |
| S3 Buckets | 2 | Private rider photos and tour artifacts/uploads |
| SQS Queue (DLQ) | 1 | Push sender event-source failure destination |
| IAM Roles | Multiple | Security permissions per function |
| CloudWatch Log Groups | Multiple | Monitoring and debugging logs |
| JWT Authorizer | 1 | Validates user login tokens |

**Tour-specific tables** (created at runtime when a tour is provisioned via the CLI script, `PUT /v1/tours`, or `POST /v1/tours` with `"provisioning": true`):
- `TourRider-{tourId}` — Rider enrollment
- `Ride-{tourId}` — Daily rides and routes
- `CheckIn-{tourId}` — Check-in records
- `User-{tourId}` — Staff accounts
- `Notification-{tourId}` — Tour notifications
- `NotificationArchive-{tourId}` — Archived/read tour notifications
- `Artifacts-{tourId}` — Tour and ride artifact metadata
- `Event-{tourId}` — Event definitions
- `EventOccurrence-{tourId}` — Event occurrences
- `EventActivityLogs-{tourId}` — Event activity records
- `Hotel-{tourId}` — Hotel master data
- `RoomAllocation-{tourId}` — Per-night rider room allocations

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
  END_DATE=2026-02-17 \
  RIDE_COUNT=8

# Using Python script directly (more options available)
python scripts/provision_tour.py \
  --stack-name dev \
  --tour-id TOT-2026 \
  --name "Tour of Tamilnadu 2026" \
  --start-date 2026-02-10 \
  --end-date 2026-02-17 \
  --ride-count 8 \
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
  RIDE_COUNT=8 \
  ENV=prod
```

The script creates the Tour record in the shared TourMaster table and provisions 13 tour-specific DynamoDB tables (TourRider, Ride, CheckIn, User, Notification, NotificationArchive, Artifacts, Event, EventOccurrence, EventActivityLogs, EventRegistration, Hotel, RoomAllocation).

It also looks up the stack's `PushSenderFunction` and connects the `Notification-{tourId}` table stream to it so tour notifications are pushed. Your AWS credentials need `cloudformation:DescribeStackResource`, `lambda:ListEventSourceMappings` and `lambda:CreateEventSourceMapping`. If the lookup fails, the script prints a warning; fix it later with `PUT /v1/tours/{tourId}/provision` (see [Notification Push Setup → step 6](#6-connect-existing-tours-to-push-sender)).

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
    "rideCount": 8,
    "description": "Season 2: Chera Nadu II"
  }'
```

By default, `POST /v1/tours` creates only the TourMaster record. To provision the 13 tour-specific DynamoDB tables in the same request, include `"provisioning": true`. The `provisioning` request attribute is not stored in TourMaster.

```bash
curl -X POST https://<api-url>/v1/tours \
  -H "Authorization: Bearer <jwt-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "tourId": "TOT-2026",
    "name": "Tour of Tamilnadu 2026",
    "startDate": "2026-02-10",
    "endDate": "2026-02-17",
    "rideCount": 8,
    "description": "Season 2: Chera Nadu II",
    "provisioning": true
  }'
```

When API provisioning is requested, it uses the same shared provisioning logic as the CLI method.

To update an existing TourMaster item, use `PUT /v1/tours`. By default, `provisioning` is `false`, so only the TourMaster item is updated. Sending `"provisioning": true` provisions tour tables only when `provisionedAt` is absent, then records that timestamp. Repeat provisioning through this endpoint is rejected. To create missing or newly defined table types after the tour has been provisioned, use `PUT /v1/tours/{tourId}/provision`; it reruns provisioning without changing TourMaster or `provisionedAt`.

> **Note**: The API method is designed for use by external apps like the Check-In App. The actual integration from these apps is out of scope for this project — this API capability is provided for their use.

---

## After Deployment: Notification Push Setup

Notification inbox storage works immediately after deployment, but **push delivery** requires extra configuration because Expo access tokens are stored in SSM SecureString parameters.

### 1) Set Expo access tokens in SSM (required for push send)

Use the bootstrap script (or Make target) to create/update both SecureString parameters expected by push sender:

```bash
# Recommended: provide tokens via env vars to avoid shell history leaks
export EXPO_RIDER_ACCESS_TOKEN="your-rider-expo-access-token"
export EXPO_MGMT_ACCESS_TOKEN="your-mgmt-expo-access-token"

make setup-notification-push STACK_NAME=dev OVERWRITE=true
```

Equivalent direct script usage:

```bash
python scripts/setup_notification_push.py \
  --stack-name dev \
  --overwrite
```

Default parameter paths (when not overridden in SAM parameters):
- `/${stackName}/push/expo-token/rider`
- `/${stackName}/push/expo-token/mgmt`

> If you use custom SSM paths in deployment overrides (`ExpoTokenParamRider`, `ExpoTokenParamMgmt`), the value must start with `/` (e.g. `/shared/expo/rider`), and you must pass matching `--rider-param-path` and `--mgmt-param-path` during bootstrap.

> All Make targets in this section default to `REGION=ap-south-1`. If your stack is in another region, add `REGION=<your-region>`.

> **Rotating a token:** the push sender caches the token value in memory. After updating SSM with `OVERWRITE=true`, redeploy (or update any `PushSenderFunction` configuration) so warm instances pick up the new value.

### 2) Seed notification defaults (required for complete framework behavior)

`make deploy` already runs both seed targets automatically after `sam deploy`. Run them manually only when deploying via `make deploy-test`, `make deploy-prod`, plain `sam deploy`, or GitHub Actions (the CI pipeline does not seed). Both seeds are insert-only and safe to re-run; existing rules/config entries are not overwritten.

```bash
make seed-app-config STACK_NAME=dev
make seed-notification-rules STACK_NAME=dev
```

Or run both through bootstrap:

```bash
make setup-notification-push STACK_NAME=dev SEED_APP_CONFIG=true SEED_RULES=true
```

### 3) Expo setup (mobile delivery gateway)

In Expo account/projects used by `tour-rider-app` and `tour-mgmt-app`:
1. Enable Push Notifications for both apps.
2. Create an Expo access token (Account settings → Access tokens; a robot user token is recommended). Access tokens are account-scoped, not project-scoped — if both apps are owned by the same Expo account, the same token can be used for both SSM parameters.
3. Provide those token values to backend SSM parameters above.

### 4) Apple setup (APNs for iOS)

In Apple Developer + Expo/EAS for each iOS app:
1. Enable Push Notifications capability for app bundle ID.
2. Create APNs auth key/certificate (recommended: auth key).
3. Upload/configure credentials in Expo/EAS for the corresponding iOS project.
4. Build and install app with push entitlements enabled.

### 5) Google setup (FCM for Android)

In Firebase/Google Cloud + Expo/EAS for each Android app:
1. Create/select Firebase project for the app and register the Android package name.
2. Add the generated `google-services.json` to the app project config.
3. Create an FCM V1 service account key (JSON) and upload it to EAS for the Android app (the legacy FCM server key is deprecated).
4. Build and install app with updated push config.

### 6) Connect existing tours to push sender

Each `Notification-{tourId}` table needs its own stream connection to `PushSenderFunction`. Tours provisioned through the API or CLI after this setup are connected automatically. Tours provisioned earlier (or where provisioning logged a push sender mapping warning) store notifications in the inbox but do not push. Fix each such tour once:

```bash
curl -X PUT https://<api-url>/v1/tours/<tourId>/provision \
  -H "Authorization: Bearer <jwt-token>"
```

This skips existing tables and creates the missing stream connection. Verify with:

```bash
aws lambda list-event-source-mappings \
  --function-name <PushSenderFunction physical name> \
  --query "EventSourceMappings[].EventSourceArn"
```

### 7) Runtime verification checklist

1. Register a device token using `POST /v1/notifications/devices`.
2. Send a test announcement with `POST /v1/notifications`.
3. Verify:
   - inbox item in `RiderNotification`/`MgmtNotification`/`Notification-{tourId}`,
   - push sender Lambda logs,
   - delivered push on device.
4. If missing, verify SSM parameter names and values, then check `PushSenderDlq` and associated CloudWatch alarm.

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

An "Unauthorized" response means the API is running and the route requires authentication. See [Cognito pools, test users, and groups](#cognito-pools-test-users-and-groups) for test setup.

---

## AWS Resources Reference

Detailed inventory of everything deployment creates in your AWS account.

### Lambda Functions

| Function | Endpoint | Purpose |
|---|---|---|
| GetActiveTourFunction | `GET /v1/tours/active` | Get currently active tour |
| GetTourFunction | `GET /v1/tours/{tourId}` | Get tour details |
| ListToursFunction | `GET /v1/tours` | List all tours |
| CreateTourFunction | `POST /v1/tours` | Create tour and optionally provision tables |
| UpdateTourFunction | `PUT /v1/tours` | Update tour and optionally provision it for the first time |
| ProvisionTourFunction | `PUT /v1/tours/{tourId}/provision` | Re-provision missing tour tables without updating TourMaster |
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
| NotificationRule | `dev-NotificationRule` | Notification rule definitions | Yes |
| RiderNotification | `dev-RiderNotification` | Rider inbox notifications + read-state | Yes |
| MgmtNotification | `dev-MgmtNotification` | Management inbox notifications + read-state | Yes |
| RiderPushDevice | `dev-RiderPushDevice` | Rider device push tokens | Yes |
| MgmtPushDevice | `dev-MgmtPushDevice` | Management device push tokens (+ group fan-out index items) | Yes |

**Tour-specific tables (created per tour via API):**

| Table Pattern | Stores | Example |
|---|---|---|
| TourRider-{tourId} | Rider enrollment | `dev-TourRider-TOT-2026` |
| Ride-{tourId} | Ride schedule and routes | `dev-Ride-TOT-2026` |
| CheckIn-{tourId} | Check-in records | `dev-CheckIn-TOT-2026` |
| User-{tourId} | Staff accounts | `dev-User-TOT-2026` |
| Notification-{tourId} | Tour-scope notification inbox | `dev-Notification-TOT-2026` |
| NotificationArchive-{tourId} | Archived/read tour notifications | `dev-NotificationArchive-TOT-2026` |
| Artifacts-{tourId} | Artifact metadata | `dev-Artifacts-TOT-2026` |
| Event-{tourId} | Event definitions | `dev-Event-TOT-2026` |
| EventOccurrence-{tourId} | Event occurrences | `dev-EventOccurrence-TOT-2026` |
| EventActivityLogs-{tourId} | Event activity logs | `dev-EventActivityLogs-TOT-2026` |
| Hotel-{tourId} | Hotel inventory and metadata | `dev-Hotel-TOT-2026` |
| RoomAllocation-{tourId} | Rider room allocations | `dev-RoomAllocation-TOT-2026` |

---

## Advanced: Using an existing management Cognito pool

The management API can use an existing management Cognito User Pool and App Client instead of creating those two resources. The Rider API pool remains managed by this backend. Configure the management pool and app client in `parameter_overrides` in `samconfig.toml`:

```toml
parameter_overrides = "Environment=dev CognitoUserPoolArn=arn:aws:cognito-idp:us-east-1:123456789012:userpool/us-east-1_AbCdEfGhI CognitoAppClientId=1a2b3c4d5e6f7g8h9i0j"
```

When `CognitoUserPoolArn` is provided, SAM does not create the management pool or its app client. The rider pool and client are still created by this stack.

---

## FAQ

**Q: How long does a deployment take?**
A: About 5-10 minutes total (tests + build + deploy). The first deployment takes slightly longer because everything is created from scratch.

**Q: Will deployment affect my existing data?**
A: No. Deployments only update application code and infrastructure configuration. Tour data, rider profiles, and check-in records are preserved.

**Q: Can I roll back if something goes wrong?**
A: Yes. AWS CloudFormation tracks every deployment. If a deployment fails partway through, it automatically rolls back to the previous working state.

**Q: How much does it cost to run?**
A: Costs depend on API usage, data retention, and AWS region. See the [Infrastructure Guide](infrastructure.md) for cost drivers and monitoring guidance.

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

The API is working but requires authentication. Get an ID token from the appropriate Cognito pool and include it in your request. See [Cognito pools, test users, and groups](#cognito-pools-test-users-and-groups).

### Notifications Saved but Push Not Delivered

1. Confirm Expo access tokens exist in SSM (`/${stack}/push/expo-token/rider` and `/mgmt`, or your custom paths).
2. Confirm stack parameters `ExpoTokenParamRider` and `ExpoTokenParamMgmt` match actual SSM parameter names (if customized).
3. Check `PushSenderFunction` logs and `PushSenderDlq` for failed stream batches.
4. Verify Expo project credentials are complete for both iOS (APNs) and Android (FCM) builds.
5. For tour notifications only: confirm the tour's `Notification-{tourId}` stream is connected to `PushSenderFunction` (see [step 6](#6-connect-existing-tours-to-push-sender)).

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

OIDC is the recommended GitHub Actions authentication method. Avoid long-lived static credentials. If an existing deployment requires static credentials, use an organization-approved least-privilege policy, store them only as GitHub Actions secrets, scope production credentials separately, and rotate them regularly. Do not attach broad administrator policies just to make deployment succeed.

---

## Related Documentation

- [Development Guide](development.md) — Local development, testing, deploying dev environment
- [Infrastructure Guide](infrastructure.md) — Resource ownership, tagging, monitoring, and cost management

---

[← Documentation index](../README.md)


## Deployment note: rider profile config seed
Run the AppConfig seed step (`scripts/seed_app_config.py`) so `RIDER_PROFILE_SECTION`, `RIDER_PROFILE_ATTRIBUTE`, and `LOV` defaults are present before using rider profile APIs.
