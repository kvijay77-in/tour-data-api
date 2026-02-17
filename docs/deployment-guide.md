# Deployment Guide

[← Back to README](../README.md)

This guide walks you through setting up and deploying the Tour Data API — the backend system that powers rider check-ins, tour management, and ride tracking for your cycling tours. Written for tour organizers and non-developer administrators.

## Table of Contents

- [What Is This System?](#what-is-this-system)
- [What You Need Before Starting](#what-you-need-before-starting)
- [One-Time Setup (Do This Once)](#one-time-setup-do-this-once)
  - [Step 1: Run Preflight Check](#step-1-run-preflight-check)
  - [Step 2: Set Up AWS Credentials](#step-2-set-up-aws-credentials)
  - [Step 3: First Deploy from Your Computer](#step-3-first-deploy-from-your-computer)
  - [Step 4: Set Up GitHub Actions (OIDC)](#step-4-set-up-github-actions-oidc)
- [How to Deploy](#how-to-deploy)
  - [Option A: Deploy from GitHub (Recommended)](#option-a-deploy-from-github-recommended)
  - [Option B: Deploy from Your Computer](#option-b-deploy-from-your-computer)
- [Environments Explained](#environments-explained)
- [What Happens When You Deploy](#what-happens-when-you-deploy)
- [After Deployment: Getting Your API URL](#after-deployment-getting-your-api-url)
- [Common Questions](#common-questions)
- [Troubleshooting](#troubleshooting)
- [AWS Resources Reference](#aws-resources-reference)

---

## What Is This System?

The Tour Data API is the **backend server** that your check-in app and other tour applications talk to. It handles:

- **Tour setup** — Creating tours, adding riders, defining daily rides and stages
- **Rider check-ins** — Recording when riders arrive at checkpoints (via QR scan, manual entry, or marking Not Riding / Quit Riding)
- **Live dashboards** — Showing real-time ride status and statistics
- **User access** — Controlling who can use the system (administrators, pit-stop crew, hotel staff)

**"Deploying"** means putting this system live on Amazon Web Services (AWS) so your apps can connect to it over the internet. Think of it like turning on the engine — the code is already written, deployment is what makes it run.

---

## What You Need Before Starting

Before your first deployment, make sure you have:

| Requirement | What It Is | How to Get It |
|---|---|---|
| **AWS Account** | Your Amazon cloud account where the system runs | [Create one at aws.amazon.com](https://aws.amazon.com/) |
| **GitHub Account** | Where the project code is stored | [Create one at github.com](https://github.com/) |
| **AWS CLI** | A command-line tool to talk to AWS | [Install guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) |
| **SAM CLI** | A tool that packages and deploys the system | [Install guide](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) |
| **Python 3.11+** | The programming language the system uses | [Download from python.org](https://www.python.org/downloads/) |

> **Tip**: If you have a technical person helping you, they likely already have AWS CLI, SAM CLI, and Python installed. You mainly need the AWS account and GitHub access.

---

## One-Time Setup (Do This Once)

These steps only need to be done once. After this initial setup, deploying updates is just a few clicks.

### Step 1: Run Preflight Check

Before doing anything else, verify that your computer has all the necessary tools. Run this in your terminal:

```bash
make check-config
```

This checks for AWS CLI, SAM CLI, Python, and valid configuration — and tells you exactly what's missing. Fix any failures before continuing.

### Step 2: Set Up AWS Credentials

Your computer needs permission to create resources in your AWS account. See the [AWS Setup Guide](aws-setup-guide.md) for detailed instructions.

**Quick check** — Run this command in your terminal to see if it's already configured:

```bash
aws sts get-caller-identity
```

If you see your account ID, you're good. If you get an error, follow the [AWS Setup Guide](aws-setup-guide.md).

### Step 3: First Deploy from Your Computer

The first deployment must be done from your computer. It creates all AWS resources including the database, API, and a **Cognito User Pool** (the user login system — this is created automatically, no manual setup needed).

```bash
# Build the application
sam build

# Deploy to dev environment
sam deploy
```

The tool will show you a summary of what it's about to create and ask for confirmation. Type `y` to proceed.

After deployment completes, note the outputs — they include your **API URL** and the auto-created **Cognito User Pool ID** and **App Client ID**.

> **What about Cognito?** The system automatically creates and configures a Cognito User Pool and App Client during deployment. You don't need to create them manually. The IDs appear in the deployment output. If you already have a Cognito User Pool and want to use it instead, see [Advanced: Using an Existing Cognito User Pool](#advanced-using-an-existing-cognito-user-pool).

### Step 4: Set Up GitHub Actions (OIDC)

For ongoing deployments, GitHub Actions can deploy directly to AWS without storing any passwords or access keys. This uses OIDC (OpenID Connect) — a secure, industry-standard way for GitHub to prove its identity to AWS.

#### 4a. Create the OIDC Connection

Run this one command (it asks for your GitHub username):

```bash
make setup-github-oidc
```

This creates an identity link between your GitHub repository and your AWS account. At the end, it prints a **Role ARN** — copy it.

#### 4b. Add the Role ARN to GitHub

1. Go to your GitHub repository in your web browser
2. Click **Settings** (top menu bar, far right)
3. In the left sidebar, click **Secrets and variables** → **Actions**
4. Click **New repository secret**
5. Name: `AWS_DEPLOY_ROLE_ARN`
6. Value: Paste the Role ARN from step 4a
7. Click **Add secret**

That's it. GitHub Actions can now deploy to your AWS account securely, with no access keys to manage or rotate.

#### For Production (separate AWS account)

If you use a separate AWS account for production:

1. Run `make setup-github-oidc` while authenticated to the **production** AWS account
2. Add the resulting Role ARN as `AWS_DEPLOY_ROLE_ARN_PROD` in GitHub Secrets

#### Alternative: Static Access Keys

If you prefer static access keys instead of OIDC (less secure, not recommended):

| Secret Name | Value | Used For |
|---|---|---|
| `AWS_ACCESS_KEY_ID` | Your AWS access key | Dev and test deployments |
| `AWS_SECRET_ACCESS_KEY` | Your AWS secret key | Dev and test deployments |

See [Creating an AWS Deployment User](#creating-an-aws-deployment-user) for how to create these.

---

## How to Deploy

There are two ways to deploy. Option A (GitHub) is recommended for most users.

### Option A: Deploy from GitHub (Recommended)

This is the simplest method — you click a few buttons on GitHub and the system takes care of everything: running tests, building the application, and deploying it to AWS.

#### Step-by-Step Instructions

**1. Open the Actions page**

Go to your GitHub repository and click the **Actions** tab in the top navigation bar.

**2. Select the pipeline**

In the left sidebar, you'll see a list of workflows. Click **CI/CD Pipeline**.

**3. Start the deployment**

Click the **Run workflow** button (blue button on the right side).

A small dropdown will appear with these options:

- **Branch**: Leave as `main` (this is the latest stable code)
- **Environment to deploy to**: Select one of:
  - `dev` — For development and testing
  - `test` — For staging and pre-production verification
  - `prod` — For the live production system

**4. Confirm and run**

Click the green **Run workflow** button to start.

**5. Monitor progress**

The pipeline will appear as a new entry in the workflow runs list. Click on it to watch progress. You'll see three stages:

| Stage | What It Does | Duration |
|---|---|---|
| **Run Tests** | Checks code quality and runs automated tests | ~1-2 minutes |
| **Build Application** | Validates the configuration and packages the code | ~1-2 minutes |
| **Deploy to [environment]** | Creates/updates all AWS resources and publishes the API | ~3-5 minutes |

A green checkmark (✓) means success. A red X means something went wrong — see [Troubleshooting](#troubleshooting).

**6. Get your API URL**

After successful deployment, the API endpoint URL appears in the deploy job output. See [After Deployment: Getting Your API URL](#after-deployment-getting-your-api-url).

### Option B: Deploy from Your Computer

If you prefer to deploy directly from your terminal (or need to deploy without GitHub Actions), you can use the SAM CLI.

#### Deploy to a Specific Environment

```bash
# Build first
sam build

# Deploy to dev (default)
sam deploy

# Deploy to test
sam deploy --config-env test

# Deploy to production
sam deploy --config-env prod
```

#### Using Make Commands (Shortcut)

If you have `make` installed, these shortcuts are available:

```bash
make deploy          # Build and deploy to dev
make deploy-test     # Build and deploy to test
make deploy-prod     # Build and deploy to prod (asks for confirmation)
```

---

## Environments Explained

The system supports three separate environments. Each is completely independent — they have their own databases, their own API URL, and their own resources. Changes to one environment do not affect the others.

| Environment | Purpose | When to Use |
|---|---|---|
| **dev** | Development and experimentation | When building new features or testing changes |
| **test** | Staging and verification | Before going live — verify everything works with realistic data |
| **prod** | Live production system | The real system your tour staff and riders use during a tour |

**How they stay separate**: Each environment creates its own set of AWS resources with a unique name. For example:
- Dev stack: `tour-data-api` → API at `https://abc123.execute-api.us-east-1.amazonaws.com/dev/`
- Test stack: `tour-data-api-test` → API at `https://def456.execute-api.us-east-1.amazonaws.com/test/`
- Prod stack: `tour-data-api-prod` → API at `https://ghi789.execute-api.us-east-1.amazonaws.com/prod/`

> **Recommendation**: Always deploy and verify changes in **dev** or **test** before deploying to **prod**.

---

## What Happens When You Deploy

When you trigger a deployment (whether from GitHub or your computer), the system automatically:

### Stage 1: Tests (automated, ~1-2 min)

Runs all automated checks to make sure nothing is broken:
- Code quality checks (linting)
- Code formatting verification
- Automated unit tests

If any test fails, deployment **stops** and nothing changes in your live system.

### Stage 2: Build (~1-2 min)

Packages the application code:
- Validates the infrastructure configuration
- Bundles all 20 API functions with their dependencies
- Prepares everything for upload to AWS

### Stage 3: Deploy to AWS (~3-5 min)

Creates or updates all the required resources in your AWS account:

**What gets created (first deployment):**

- **1 API Gateway** — The "front door" that receives requests from your apps. This gives you your API URL.
- **1 Cognito User Pool** — The user login system, including an App Client for your check-in app (auto-created unless you provide your own).
- **20 Lambda Functions** — The business logic that processes each request (managing tours, riders, rides, check-ins, and users).
- **1 Shared Code Layer** — Common utilities shared across all functions.
- **2 Database Tables** — `RiderProfile` (rider personal data) and `Tour` (tour details) — these persist across tours.
- **1 S3 Storage Bucket** — For rider photos and archived tour data.
- **20 Security Roles** — Each function gets only the permissions it needs (e.g., the check-in function can write check-in records but can't delete tours).
- **20 Log Groups** — For monitoring and debugging.
- **JWT Authentication** — Connects to your Cognito User Pool so only authorized users can access the API.

**What gets created later (when you create a tour via the API):**

When you use the API to create a new tour (e.g., "India-Coast-2026"), the system automatically creates 4 additional database tables just for that tour:
- `TourRider-India-Coast-2026` — Rider enrollment for this tour
- `Ride-India-Coast-2026` — Daily rides and routes
- `CheckIn-India-Coast-2026` — Check-in records
- `User-India-Coast-2026` — Staff accounts for this tour

When the tour is over and archived, these tables can be exported as a backup and then deleted to save costs.

**What happens on subsequent deployments:**

Only things that changed are updated. If you add a new feature, only the affected functions are updated. Databases and stored data are **never deleted** during updates.

---

## After Deployment: Getting Your API URL

Your API URL is the address your check-in app and other tools use to connect to the system.

### From GitHub Actions

1. After deployment completes, click on the completed **Deploy to [environment]** job
2. Expand the **Build and Deploy** step
3. Look for the `api_endpoint` value in the output

### From Your Terminal

After deploying with `sam deploy`, run:

```bash
# For dev
aws cloudformation describe-stacks \
  --stack-name tour-data-api \
  --query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" \
  --output text

# For test
aws cloudformation describe-stacks \
  --stack-name tour-data-api-test \
  --query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" \
  --output text

# For prod
aws cloudformation describe-stacks \
  --stack-name tour-data-api-prod \
  --query "Stacks[0].Outputs[?OutputKey=='ApiEndpoint'].OutputValue" \
  --output text
```

### Testing the API

Once you have the URL, verify it's working:

```bash
# Replace <api-url> with your actual API URL
curl <api-url>/v1/tours
```

You should get a JSON response. If you get an "Unauthorized" error, that's expected — it means authentication is working. You'll need a JWT token from Cognito to access the API. See [AWS Setup Guide → Get JWT Token for Testing](aws-setup-guide.md#5-get-jwt-token-for-testing).

---

## Common Questions

**Q: How long does a deployment take?**
A: About 5-10 minutes total (tests + build + deploy). The first deployment takes slightly longer because everything is being created from scratch.

**Q: Will deployment affect my existing data?**
A: No. Deployments only update the application code and infrastructure configuration. Your tour data, rider profiles, and check-in records are preserved.

**Q: Can I roll back if something goes wrong?**
A: Yes. AWS CloudFormation keeps track of every deployment. If a deployment fails partway through, it automatically rolls back to the previous working state.

**Q: How much does it cost to run?**
A: The system uses a "pay-per-use" model. For a typical cycling tour (~100 riders, 7-8 rides), estimated costs are very low (under $5/month). See the [Infrastructure Guide](infrastructure-guide.md) for detailed cost estimates.

**Q: Can I deploy to multiple environments at the same time?**
A: Yes. Each environment is independent. You could deploy to `dev` and `prod` simultaneously without them affecting each other.

**Q: Do I need to deploy every time I create a new tour?**
A: No. Tour creation happens through the API itself — once the system is deployed, you create tours by sending a request to `POST /v1/tours`. Deployment is only needed when the application code changes.

---

## Troubleshooting

### Deployment Failed at "Run Tests"

**What it means**: An automated test encountered an error.

**What to do**:
1. Click on the failed job in GitHub Actions
2. Read the error message — it usually tells you exactly what failed
3. If you recently changed code, review your changes
4. Ask your developer to investigate the test failure

### Deployment Failed at "Build"

**What it means**: The configuration file (template.yaml) has an error.

**What to do**:
1. Click on the failed job to see the error details
2. Common cause: syntax errors in configuration files
3. Run `sam validate --lint` locally to check for errors

### Deployment Failed at "Deploy"

**What it means**: AWS couldn't create or update a resource.

**What to do**:
1. Check the error message in the deploy output
2. Common causes:
   - **Missing permissions**: The AWS user or OIDC role needs sufficient permissions
   - **Resource limit**: You may have hit an AWS service limit — contact AWS support
   - **Region mismatch**: Ensure the region in samconfig.toml matches your AWS configuration

### "Unauthorized" Error When Calling the API

**What it means**: The API is working but requires authentication.

**What to do**: Get a JWT token from Cognito and include it in your request. See [AWS Setup Guide → Get JWT Token for Testing](aws-setup-guide.md#5-get-jwt-token-for-testing).

### "Stack already exists" Error

**What it means**: A deployment with the same name already exists.

**What to do**: This is usually fine — subsequent deployments update the existing stack. If you need to completely start over:

```bash
# Delete the existing stack (WARNING: this deletes all resources)
sam delete --stack-name tour-data-api
```

---

## Creating an AWS Deployment User

For the GitHub Actions pipeline (and for manual deployments from your terminal), you need an AWS user that has permission to create and manage the required resources.

### Create the User

```bash
aws iam create-user --user-name github-actions-deployer
```

### Attach Permissions

The deployment user needs permissions for CloudFormation, Lambda, DynamoDB, API Gateway, S3, and IAM. Attach these policies:

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

This outputs an `AccessKeyId` and `SecretAccessKey`. **Save both values immediately** — the secret key is only shown once.

These are the values you add to GitHub Secrets in [Step 4](#step-4-add-secrets-to-github):
- `AccessKeyId` → GitHub secret `AWS_ACCESS_KEY_ID`
- `SecretAccessKey` → GitHub secret `AWS_SECRET_ACCESS_KEY`

> **Security Note**: For production, create a separate deployment user with separate access keys and store them as `AWS_ACCESS_KEY_ID_PROD` and `AWS_SECRET_ACCESS_KEY_PROD` in GitHub Secrets. This way, compromised dev credentials can't affect production.

---

## AWS Resources Reference

This is a detailed inventory of everything the deployment creates in your AWS account. You don't need to understand all of this — it's here for reference and for anyone helping you manage the system.

### Resource Summary

| Resource Type | Count | What It Does |
|---|---|---|
| API Gateway (HTTP API) | 1 | Receives requests from your apps |
| Cognito User Pool | 1 | Manages user authentication (auto-created) |
| Lambda Functions | 20 | Processes each type of request |
| Lambda Layer | 1 | Shared code used by all functions |
| DynamoDB Tables (shared) | 2 | Stores rider profiles and tour info |
| DynamoDB Tables (per tour) | 4 per active tour | Stores tour-specific data (riders, rides, check-ins, users) |
| S3 Bucket | 1 | Stores rider photos and archived tour exports |
| IAM Roles | 20 | Security permissions for each function |
| CloudWatch Log Groups | 20 | Logs for monitoring and debugging |
| JWT Authorizer | 1 | Validates user login tokens |

### Lambda Functions (All 20)

| Function | API Endpoint | What It Does |
|---|---|---|
| GetActiveTourFunction | `GET /v1/tours/active` | Get the currently active tour |
| GetTourFunction | `GET /v1/tours/{tourId}` | Get details for a specific tour |
| ListToursFunction | `GET /v1/tours` | List all tours |
| CreateTourFunction | `POST /v1/tours` | Create a new tour and its database tables |
| ArchiveTourFunction | `POST /v1/tours/{tourId}/archive` | Archive a completed tour |
| GetRiderProfileFunction | `GET /v1/riders/profile/{profileId}` | Get a rider's profile |
| UpdateRiderProfileFunction | `PUT /v1/riders/profile/{profileId}` | Update a rider's profile |
| GetTourRidersFunction | `GET /v1/tours/{tourId}/riders` | List all riders in a tour |
| GetTourRiderByIdFunction | `GET /v1/tours/{tourId}/riders/{riderId}` | Get a specific rider's tour details |
| GetTodaysRideFunction | `GET /v1/tours/{tourId}/rides/today` | Get today's scheduled ride |
| GetRideFunction | `GET /v1/tours/{tourId}/rides/{rideId}` | Get details for a specific ride |
| ListRidesFunction | `GET /v1/tours/{tourId}/rides` | List all rides in a tour |
| CreateRideFunction | `POST /v1/tours/{tourId}/rides` | Create a new daily ride |
| UpdateRideFunction | `PUT /v1/tours/{tourId}/rides/{rideId}` | Update ride details |
| CloseRideFunction | `POST /v1/tours/{tourId}/rides/{rideId}/close` | Close a ride (no more check-ins) |
| CreateCheckInFunction | `POST /v1/tours/{tourId}/checkins` | Record a rider check-in |
| GetRideCheckInsFunction | `GET /v1/tours/{tourId}/rides/{rideId}/checkins` | Get all check-ins for a ride |
| GetDashboardDataFunction | `GET /v1/tours/{tourId}/rides/{rideId}/dashboard` | Get live dashboard data |
| GetCurrentUserFunction | `GET /v1/users/me` | Get current logged-in user info |
| ListTourUsersFunction | `GET /v1/tours/{tourId}/users` | List staff members for a tour |

### Database Tables

**Always present (created during deployment):**

| Table | Stores | Persists Across Tours? |
|---|---|---|
| RiderProfile | Rider personal info (name, email, emergency contacts) | Yes — rider data is shared across all tours |
| Tour | Tour details (name, dates, status) | Yes — all tours are listed here |

**Created per tour (when you create a tour via the API):**

| Table Pattern | Stores | Example Table Name |
|---|---|---|
| TourRider-{tourId} | Which riders are enrolled in this tour | `tour-data-api-TourRider-India-Coast-2026` |
| Ride-{tourId} | Daily ride schedule, routes, and stages | `tour-data-api-Ride-India-Coast-2026` |
| CheckIn-{tourId} | Rider check-in records for each stage | `tour-data-api-CheckIn-India-Coast-2026` |
| User-{tourId} | Staff/admin accounts for this tour | `tour-data-api-User-India-Coast-2026` |

---

## Related Documentation

- [AWS Setup Guide](aws-setup-guide.md) — AWS credentials, Cognito authentication, getting JWT tokens
- [Infrastructure Guide](infrastructure-guide.md) — Resource tagging, monitoring, and cost estimation
- [Development Guide](development-guide.md) — For developers: local testing, code structure, troubleshooting
- [Requirements](Requirements.md) — Detailed feature requirements and business rules

---

## Advanced: Using an Existing Cognito User Pool

By default, the deployment automatically creates a Cognito User Pool and App Client. If you already have a Cognito User Pool (e.g., shared with other applications), you can provide its ARN and App Client ID instead.

Add these to `parameter_overrides` in `samconfig.toml`:

```toml
parameter_overrides = "Environment=dev CognitoUserPoolArn=arn:aws:cognito-idp:us-east-1:123456789012:userpool/us-east-1_AbCdEfGhI CognitoAppClientId=1a2b3c4d5e6f7g8h9i0j"
```

When `CognitoUserPoolArn` is provided, the system skips auto-creation and uses the specified User Pool.

---

## Optional Parameters

You can add these values to `parameter_overrides` in `samconfig.toml` for cost tracking and resource tagging:

| Parameter | Purpose | Example |
|---|---|---|
| `Owner` | Who is responsible for these resources | `Owner=\"Tour Operations Team\"` |
| `CostCenter` | For billing/cost allocation | `CostCenter=\"CC-1234\"` |
| `SubscriptionId` | Your tracking identifier | `SubscriptionId=\"sub-001\"` |

**Example:**

```toml
parameter_overrides = "Environment=prod Owner=\"Tour Ops\" CostCenter=\"CC-5678\" SubscriptionId=\"sub-001\""
```

---

[← Back to README](../README.md)
