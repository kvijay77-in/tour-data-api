# AWS Setup Guide

[← Back to README](../README.md)

This guide covers AWS CLI configuration, credential setup, and Cognito authentication configuration for the Tour Data API project.

## Table of Contents
- [Verify AWS Configuration](#verify-aws-configuration)
- [Setting up Cognito](#setting-up-cognito)

---

## Verify AWS Configuration

Check if AWS CLI is configured and accessible:
```bash
aws sts get-caller-identity
```

If successful, you should see your AWS account details (Account ID, User ARN, etc.).

**If AWS CLI is not configured**, choose one of these setup options:

### Option A: Temporary Credentials (Recommended - More Secure)

Temporary credentials are more secure as they expire automatically and don't require long-term access keys.

#### Using AWS IAM Identity Center (SSO)

```bash
# Configure AWS SSO
aws configure sso
```

You'll be prompted to enter:
- **SSO start URL**: Your organization's SSO URL
- **SSO Region**: Region where your SSO is configured
- **SSO account**: Select your AWS account
- **SSO role**: Select the role to use
- **Default region**: e.g., `ap-south-1`, `us-east-1`, etc.
- **Output format**: `json` (recommended)

After configuration, login to get temporary credentials:
```bash
# Login to SSO (credentials valid for hours, not permanent)
aws sso login --profile your-profile-name

# Verify access
aws sts get-caller-identity --profile your-profile-name
```

#### Using AWS STS Assume Role

If you have a role to assume:

```bash
# Get temporary credentials (valid for 1-12 hours)
aws sts assume-role \
  --role-arn arn:aws:iam::ACCOUNT_ID:role/YourRoleName \
  --role-session-name dev-session

# Set temporary credentials as environment variables
export AWS_ACCESS_KEY_ID=<TemporaryAccessKeyId>
export AWS_SECRET_ACCESS_KEY=<TemporarySecretAccessKey>
export AWS_SESSION_TOKEN=<SessionToken>
```

### Option B: Long-term Access Keys (Less Secure)

```bash
# Configure AWS CLI with your credentials
aws configure
```

You'll be prompted to enter:
- **AWS Access Key ID**: Your AWS access key
- **AWS Secret Access Key**: Your AWS secret key
- **Default region name**: e.g., `ap-south-1`, `us-east-1`, etc.
- **Default output format**: `json` (recommended)

> **Note**: If you don't have AWS credentials, create them in the AWS Console:
> 1. Go to IAM → Users → Your User → Security Credentials
> 2. Create Access Key → Command Line Interface (CLI)
> 3. Download and save the credentials securely
> 
> **Security Best Practice**: Rotate access keys regularly and use temporary credentials when possible.

### Verify AWS Region

```bash
# Check current region
aws configure get region

# Set region if needed
aws configure set region ap-south-1
```

### SAM CLI Configuration

SAM uses the same AWS credentials as AWS CLI. No separate configuration needed.

---

## Setting up Cognito

The API uses AWS Cognito for authentication. To configure:

### 1. Create Cognito User Pool

Create a new user pool (or update template.yaml to automate):

```bash
aws cognito-idp create-user-pool --pool-name tour-data-api-users
```

Save the `UserPoolId` from the output.

### 2. Create App Client

```bash
aws cognito-idp create-user-pool-client \
  --user-pool-id <pool-id> \
  --client-name tour-data-api-client \
  --generate-secret
```

Save the `ClientId` from the output.

### 3. Update SAM Template

Update your SAM deployment with the User Pool ARN and App Client ID:

```bash
sam deploy --parameter-overrides \
  CognitoUserPoolArn=arn:aws:cognito-idp:<region>:<account-id>:userpool/<pool-id> \
  CognitoAppClientId=<client-id>
```

Or configure in `samconfig.toml`:
```toml
[default.deploy.parameters]
parameter_overrides = "CognitoUserPoolArn=arn:aws:cognito-idp:... CognitoAppClientId=..."
```

> **Note**: When `CognitoUserPoolArn` is not provided (empty default), the API runs without JWT authentication. This is suitable for local development and testing. For production, always provide both `CognitoUserPoolArn` and `CognitoAppClientId`.

### 4. Create Test Users

Create users for testing:

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <pool-id> \
  --username admin@example.com \
  --user-attributes Name=email,Value=admin@example.com
```

Set a permanent password:

```bash
aws cognito-idp admin-set-user-password \
  --user-pool-id <pool-id> \
  --username admin@example.com \
  --password YourSecurePassword123! \
  --permanent
```

### 5. Get JWT Token for Testing

Retrieve a JWT token for API testing:

```bash
aws cognito-idp initiate-auth \
  --auth-flow USER_PASSWORD_AUTH \
  --client-id <client-id> \
  --auth-parameters USERNAME=admin@example.com,PASSWORD=<password>
```

The response will include:
- `IdToken`: Use this as the Bearer token in API requests
- `AccessToken`: For accessing user information
- `RefreshToken`: To get new tokens when they expire

### Using the JWT Token

Include the token in your API requests:

```bash
curl -H "Authorization: Bearer <IdToken>" \
  https://<api-id>.execute-api.<region>.amazonaws.com/v1/tours/active
```

---

## Additional Resources

- [AWS CLI Configuration Guide](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-configure.html)
- [AWS IAM Identity Center (SSO)](https://docs.aws.amazon.com/singlesignon/latest/userguide/what-is.html)
- [AWS Cognito User Pools](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-identity-pools.html)
- [JWT Authentication](https://jwt.io/introduction)

---

[← Back to README](../README.md)
