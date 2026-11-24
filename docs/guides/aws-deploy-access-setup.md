# AWS Deploy Access Setup
_Last updated: 2026-11-24_

[← Back to README](../README.md)

This guide is the **manual, one-time setup** of the AWS side of deployment: who may deploy, from where, and with what permissions. It is run by an AWS administrator. Nothing here is automated, and the CI/CD pipeline never creates or changes these resources. For day-to-day deployment see the [Deployment Guide](deployment.md).

## Table of Contents

- [How it works](#how-it-works)
- [Prerequisites](#prerequisites)
- [Step 1: Branches and branch protection](#step-1-branches-and-branch-protection)
- [Step 2: GitHub OIDC provider](#step-2-github-oidc-provider)
- [Step 3: Deploy-access stacks](#step-3-deploy-access-stacks)
- [Step 4: GitHub secrets](#step-4-github-secrets)
- [Step 5: Terminal profile](#step-5-terminal-profile)
- [Step 6: First deployment](#step-6-first-deployment)
- [Step 7: Retire the old access](#step-7-retire-the-old-access)
- [Step 8: Client app config read access](#step-8-client-app-config-read-access)
- [Verification](#verification)
- [What the deploy roles can and cannot do](#what-the-deploy-roles-can-and-cannot-do)
- [Keeping the policies in sync](#keeping-the-policies-in-sync)
- [Known limits and residual risk](#known-limits-and-residual-risk)
- [Troubleshooting](#troubleshooting)

---

## How it works

| Environment | Deployed from | AWS account | Role used |
|---|---|---|---|
| **dev** | GitHub Actions, run on branch `develop` or a terminal | non-prod | `tour-data-api-github-deploy-dev` or `tour-data-api-terminal-deploy-dev` |
| **test** | Terminal only (ad hoc) | non-prod | `tour-data-api-terminal-deploy-test` |
| **prod** | GitHub Actions, run on branch `main` only | **separate prod account** | `tour-data-api-github-deploy-prod` |

- The GitHub workflow is **manual** (`Run workflow`). The environment comes from the branch it is run on: `develop` → dev, `main` → prod. Any other branch is rejected. Nothing deploys on merge.
- Each GitHub role trusts exactly one branch (`sub = repo:<org>/<repo>:ref:refs/heads/<branch>`, exact match). A run on `develop` cannot assume the prod role and a run on `main` cannot assume the dev role, even if the workflow file is edited.
- Deploy roles hold **control-plane permissions only**, scoped to the stack's resource names. They cannot read or write application data and cannot create an IAM role that is more powerful than the **permissions boundary** attached to every Lambda role.
- Production is never deployed from a terminal: no terminal role exists in the prod account.

Each environment has one CloudFormation stack, `tour-data-api-deploy-access-<env>`, from [`cloudformation/deploy-access.yaml`](../../cloudformation/deploy-access.yaml):

| Resource | Purpose |
|---|---|
| `tour-data-api-sam-<env>-<account-id>` S3 bucket | Holds packaged code for `sam deploy --s3-bucket`. Encrypted, private, TLS-only, objects expire after 30 days. |
| `tour-data-api-<env>-lambda-boundary` policy | Permissions boundary for all Lambda roles (set by `Globals.Function.PermissionsBoundary` in `template.yaml`). |
| `tour-data-api-<env>-deploy-core` / `-deploy-compute` policies | The deploy permissions (two policies to stay under the 6,144-character limit). |
| `tour-data-api-github-deploy-<env>` role | Optional. Only when `GitHubBranch` is set. |
| `tour-data-api-terminal-deploy-<env>` role | Optional. Only when `TerminalPrincipalArn` is set. |

Layout per account:

| Account | Stacks |
|---|---|
| Non-prod | `tour-data-api-github-oidc` (only if no GitHub provider exists), `tour-data-api-deploy-access-dev`, `tour-data-api-deploy-access-test`, `tour-data-api-mgmt-config-read-dev`, `tour-data-api-rider-config-read-dev` |
| Prod | `tour-data-api-github-oidc` (only if no GitHub provider exists), `tour-data-api-deploy-access-prod`, `tour-data-api-mgmt-config-read-prod`, `tour-data-api-rider-config-read-prod` |

The `*-config-read-*` stacks give the app repositories read-only access to the client configuration parameters ([Step 8](#step-8-client-app-config-read-access)).

## Prerequisites

- Administrator access (IAM, CloudFormation, S3) to **each** AWS account, as an AWS CLI profile. Use `--profile <admin-profile>` on every command below, or export `AWS_PROFILE`.
- AWS CLI v2 and a local clone of this repository (the commands read `cloudformation/*.yaml`).
- Your GitHub organization or username (`<org>`) and the repository name (`tour-data-api`).
- Admin rights on the GitHub repository (branches and secrets).
- The ARN of the IAM user or role that will deploy from a terminal (`<terminal-principal-arn>`).

Placeholders used below: `<org>`, `<terminal-principal-arn>`, `<nonprod-account-id>`, `<prod-account-id>`. Check which account you are in before every step:

```bash
aws sts get-caller-identity --query Account --output text
```

---

## Step 1: Branches and branch protection

Create the `develop` branch from `main` if it does not exist (local git, then push):

```bash
git switch main && git pull
git switch -c develop
git push -u origin develop
```

Then protect both branches in GitHub → **Settings → Branches → Add branch ruleset** (or classic rule) for `develop` and `main`:

- Require a pull request before merging (and at least one approval for `main`).
- Block force pushes and branch deletion.
- Optionally restrict who can push.

This matters: **whoever can change what is on `develop` or `main` can change what gets deployed** (and the code runs with the Lambda roles' permissions). Anyone with write access can press *Run workflow*, but only runs on these two branches can obtain AWS credentials.

## Step 2: GitHub OIDC provider

An AWS account can hold only one provider for `token.actions.githubusercontent.com`. In **each** account (non-prod, then prod), check whether it exists:

```bash
aws iam list-open-id-connect-providers \
  --query "OpenIDConnectProviderList[?contains(Arn, 'token.actions.githubusercontent.com')].Arn" \
  --output text
```

**Case A: nothing is returned** → create the provider (no permissions are granted by it):

```bash
aws cloudformation deploy \
  --template-file cloudformation/github-oidc.yaml \
  --stack-name tour-data-api-github-oidc \
  --tags Project=tour-data-api ManagedBy=CloudFormation
```

**Case B: an ARN is returned** → nothing to create. If the provider was created earlier by an existing `tour-data-api-github-oidc` stack (the old version of the template, which also created an over-privileged deploy role), leave it for now and remove that role in [Step 7](#step-7-retire-the-old-access). If it was created some other way, the new stacks use it as is: the default provider ARN is `arn:aws:iam::<account-id>:oidc-provider/token.actions.githubusercontent.com`.

## Step 3: Deploy-access stacks

Create one stack per environment, in the right account. `--capabilities CAPABILITY_NAMED_IAM` is required because the stack creates named IAM roles and policies.

**Non-prod account – dev** (GitHub role for `develop` plus a terminal role):

```bash
aws cloudformation deploy \
  --template-file cloudformation/deploy-access.yaml \
  --stack-name tour-data-api-deploy-access-dev \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      TargetStackName=dev Environment=dev \
      GitHubOrg=<org> GitHubRepo=tour-data-api GitHubBranch=develop \
      TerminalPrincipalArn=<terminal-principal-arn> \
  --tags Project=tour-data-api Environment=dev ManagedBy=CloudFormation
```

**Non-prod account – test** (terminal role only, no GitHub role):

```bash
aws cloudformation deploy \
  --template-file cloudformation/deploy-access.yaml \
  --stack-name tour-data-api-deploy-access-test \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      TargetStackName=test Environment=test \
      GitHubOrg=<org> GitHubRepo=tour-data-api \
      TerminalPrincipalArn=<terminal-principal-arn> \
  --tags Project=tour-data-api Environment=test ManagedBy=CloudFormation
```

**Prod account – prod** (GitHub role for `main` only, **no** terminal role):

```bash
aws cloudformation deploy \
  --template-file cloudformation/deploy-access.yaml \
  --stack-name tour-data-api-deploy-access-prod \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      TargetStackName=prod Environment=prod \
      GitHubOrg=<org> GitHubRepo=tour-data-api GitHubBranch=main \
  --tags Project=tour-data-api Environment=prod ManagedBy=CloudFormation
```

Parameters worth knowing:

| Parameter | Notes |
|---|---|
| `GitHubBranch` | `develop` (dev), `main` (prod) or empty (no GitHub role). A built-in rule rejects `main` for dev/test and `develop` for prod. |
| `TerminalPrincipalArn` | IAM user or role allowed to assume the terminal role. Leave empty for prod. For an IAM Identity Center (SSO) role, give the role ARN **without** the `aws-reserved/sso.amazonaws.com/<region>/` path segment. |
| `TerminalRequireMfa` | Default `true`: the terminal role can only be assumed with MFA. Set to `false` for Identity Center principals (MFA is then enforced at sign-in), because role-chained SSO sessions do not carry the MFA claim. |
| `OidcProviderArn` | Leave empty (default provider ARN of the account). |

Read the outputs (role ARNs, artifacts bucket, boundary ARN):

```bash
aws cloudformation describe-stacks \
  --stack-name tour-data-api-deploy-access-dev \
  --query "Stacks[0].Outputs[].[OutputKey,OutputValue]" --output table
```

## Step 4: GitHub secrets

In GitHub → **Settings → Secrets and variables → Actions → New repository secret**, add:

| Secret | Value |
|---|---|
| `AWS_DEPLOY_ROLE_ARN_DEV` | `GitHubDeployRoleArn` output of `tour-data-api-deploy-access-dev` (non-prod account) |
| `AWS_DEPLOY_ROLE_ARN_PROD` | `GitHubDeployRoleArn` output of `tour-data-api-deploy-access-prod` (prod account) |

Role ARNs are not secret credentials; they are stored as secrets only so the workflow can select one by name.

Then **delete** these old secrets if they exist: `AWS_DEPLOY_ROLE_ARN`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ACCESS_KEY_ID_PROD`, `AWS_SECRET_ACCESS_KEY_PROD`. Do **not** create GitHub *Environments* for the deploy jobs: using `environment:` changes the OIDC `sub` claim and the roles would stop trusting the run.

## Step 5: Terminal profile

For ad hoc test deployments and dev iteration, add a profile to `~/.aws/config` (use the `TerminalDeployRoleArn` output; `source_profile` is the profile of the principal you gave as `TerminalPrincipalArn`):

```ini
[profile tour-data-api-dev-deploy]
role_arn       = arn:aws:iam::<nonprod-account-id>:role/tour-data-api-terminal-deploy-dev
source_profile = <your-profile>
mfa_serial     = arn:aws:iam::<nonprod-account-id>:mfa/<your-iam-user>   # omit if TerminalRequireMfa=false
region         = ap-south-1

[profile tour-data-api-test-deploy]
role_arn       = arn:aws:iam::<nonprod-account-id>:role/tour-data-api-terminal-deploy-test
source_profile = <your-profile>
mfa_serial     = arn:aws:iam::<nonprod-account-id>:mfa/<your-iam-user>
region         = ap-south-1
```

Use it for a single command or a whole shell: `AWS_PROFILE=tour-data-api-test-deploy make deploy-test`.

## Step 6: First deployment

1. **New environment (no application stack yet).** Run the deployment normally (GitHub workflow, or `make deploy-dev` / `make deploy-test`). The roles create the stack, including every Lambda role with the boundary attached.
2. **Existing environment (stack already deployed with the old, boundary-less roles), e.g. the current dev and test stacks.** Run the first deployment that adds the boundary once with **administrator** credentials. The deploy roles are allowed to attach the boundary, but they may not change the policies of a role that does not carry it yet, and CloudFormation may update both in the same deployment:

   ```bash
   source .venv/bin/activate
   sam build
   sam deploy --config-env default --s3-bucket tour-data-api-sam-dev-<nonprod-account-id> --profile <admin-profile>
   ```

   (use `--config-env test` and `tour-data-api-sam-test-...` for test). Review the change set: besides any pending application changes, every `...Role` resource shows a `PermissionsBoundary` update. Subsequent deployments use the deploy roles.
3. **The boundary policy must exist before the application stack is deployed.** That is why the deploy-access stacks (Step 3) come first.
4. **Prod** is first deployed from GitHub: run the workflow on `main`. Review the dev/test results first.

## Step 7: Retire the old access

Only after a successful deployment through the new path:

1. **Remove the old over-privileged role** (if the account still has the old `tour-data-api-github-oidc` stack): re-deploy the stack with the current template. The provider is kept; the role `tour-data-api-github-deploy-<region>` (with `IAMFullAccess`, `AmazonDynamoDBFullAccess`, ... attached) is deleted.

   ```bash
   aws cloudformation deploy \
     --template-file cloudformation/github-oidc.yaml \
     --stack-name tour-data-api-github-oidc \
     --tags Project=tour-data-api ManagedBy=CloudFormation
   ```

   **Then look for roles that were not created by this repository's templates** (for example created by hand in the console or CLI). Redeploying a stack never removes them. Old trust policies typically use a wildcard `sub` (`repo:<org>/tour-data-api:*`), which lets any branch or workflow in the repository assume the role. List every role that trusts the GitHub provider with a wildcard subject:

   ```bash
   aws iam list-roles --output json | jq -r '.Roles[]
     | select(.AssumeRolePolicyDocument|tostring|test("githubusercontent.*\\*"))
     | .RoleName'
   ```

   For each role returned, check whether a CloudFormation stack owns it. Stacks are regional, so check every region the application was ever deployed to:

   ```bash
   aws cloudformation describe-stack-resources --region <region> \
     --physical-resource-id <role-name> --query 'StackResources[].StackName'
   ```

   - **A stack owns it:** deploy that stack with the current template, or delete the stack.
   - **No stack owns it** (the error is `Stack for <role-name> does not exist` in every region): inspect it, then delete it once nothing uses it.

     ```bash
     # RoleLastUsed = {} means it has never been assumed
     aws iam get-role --role-name <role-name> \
       --query 'Role.[CreateDate,RoleLastUsed,Tags,AssumeRolePolicyDocument]'
     aws iam list-attached-role-policies --role-name <role-name>
     aws iam list-role-policies --role-name <role-name>
     ```

     If the role is in use, find out what uses it first (the GitHub secret `AWS_DEPLOY_ROLE_ARN` is a likely reference). If it must stay for now, tighten its trust policy with `aws iam update-assume-role-policy` to `StringEquals` on `repo:<org>/tour-data-api:ref:refs/heads/<branch>` and replan its removal. Otherwise delete it:

     ```bash
     for arn in $(aws iam list-attached-role-policies --role-name <role-name> \
         --query 'AttachedPolicies[].PolicyArn' --output text); do
       aws iam detach-role-policy --role-name <role-name> --policy-arn "$arn"
     done
     # delete each inline policy listed by list-role-policies:
     # aws iam delete-role-policy --role-name <role-name> --policy-name <name>
     aws iam delete-role --role-name <role-name>
     ```

   Run the `list-roles` query again. It must return nothing: after this step, no role trusting the GitHub provider may use a wildcard subject. The roles from `deploy-access.yaml` and `consumer-read-access.yaml` use exact `StringEquals` matches and never appear in the result.

2. **Retire the old static IAM access keys** that were stored as GitHub secrets. Find them, deactivate, observe for a few days, then delete:

   ```bash
   aws iam list-access-keys --user-name <ci-iam-user>
   aws iam update-access-key --user-name <ci-iam-user> --access-key-id <key-id> --status Inactive
   # after a few days without problems:
   aws iam delete-access-key --user-name <ci-iam-user> --access-key-id <key-id>
   ```

   If the IAM user exists only for CI, delete the user as well.

## Step 8: Client app config read access

The application stack publishes the apps' public connection values to SSM under `/tour-data-api/<env>/<app>/` ([Client app configuration](../design/client-configuration.md)). The app repositories `tour-mgmt-app` and `tour-rider-app` read them from GitHub Actions through read-only roles from [`cloudformation/consumer-read-access.yaml`](../../cloudformation/consumer-read-access.yaml), one stack per app per environment:

| Account | Stack | Reads | Trusted branches |
|---|---|---|---|
| Non-prod | `tour-data-api-mgmt-config-read-dev` | `/tour-data-api/dev/mgmt/*` | `tour-mgmt-app` `develop`, `main` |
| Non-prod | `tour-data-api-rider-config-read-dev` | `/tour-data-api/dev/rider/*` | `tour-rider-app` `develop`, `main` |
| Prod | `tour-data-api-mgmt-config-read-prod` | `/tour-data-api/prod/mgmt/*` | `tour-mgmt-app` `main` |
| Prod | `tour-data-api-rider-config-read-prod` | `/tour-data-api/prod/rider/*` | `tour-rider-app` `main` |

The trusted branches follow from `Environment` and cannot be overridden. The dev roles also trust `main` because each app's Production build routes the store reviewer to the dev backend. A rule rejects a `ClientApp` and `GitHubRepo` pair that do not match.

1. **Update the deploy-access stacks first.** The deploy roles need the `ClientConfigParameters` permission before the application stack can create the parameters. Re-run the Step 3 command for dev and test (non-prod account) and prod (prod account).
2. **Deploy the application** as usual and confirm that the parameters exist:

   ```bash
   aws ssm get-parameters-by-path --path /tour-data-api/dev --recursive \
     --query "Parameters[].[Name,Value]" --output table
   ```

3. **Create the read roles** with administrator credentials. Example for the management app in the non-prod account; change `ClientApp`/`GitHubRepo` (`rider`/`tour-rider-app`) and `Environment` (`prod`, in the prod account) for the others:

   ```bash
   aws cloudformation deploy \
     --template-file cloudformation/consumer-read-access.yaml \
     --stack-name tour-data-api-mgmt-config-read-dev \
     --capabilities CAPABILITY_NAMED_IAM \
     --parameter-overrides \
         Environment=dev ClientApp=mgmt \
         GitHubOrg=<org> GitHubRepo=tour-mgmt-app \
     --tags Project=tour-data-api Environment=dev ManagedBy=CloudFormation
   ```

4. **Hand over the role ARNs** (`ConfigReadRoleArn` output) to the app teams. Each app repository stores the dev and prod ARNs as its own GitHub Actions secrets. The GitHub OIDC provider from Step 2 is shared, so the app repositories need no other AWS setup for this.

---

## Verification

Run these after setup. Use the terminal profile from Step 5 (it has the same permissions as the GitHub role). All "denied" commands must fail with `AccessDenied`.

| # | Check | Expected |
|---|---|---|
| 1 | Run the workflow on a feature branch | Fails in **Resolve environment** with a clear message |
| 2 | Run the workflow on `develop` | Tests, build, deploy to dev, seed, and endpoints printed |
| 3 | `aws dynamodb scan --table-name dev-RiderProfile --profile tour-data-api-dev-deploy` | **Denied** (no item-level access) |
| 4 | `aws dynamodb get-item --table-name dev-AppConfig --key '{"configType":{"S":"x"},"configId":{"S":"x"}}' --profile tour-data-api-dev-deploy` | **Allowed** (seeding exception; returns no item) |
| 5 | `aws s3 cp s3://dev-photos-<nonprod-account-id>/anything - --profile tour-data-api-dev-deploy` | **Denied** (no object access) |
| 6 | `aws iam create-role --role-name dev-test-role --assume-role-policy-document file://trust.json --profile tour-data-api-dev-deploy` | **Denied** (no permissions boundary) |
| 7 | `aws iam delete-role-permissions-boundary --role-name <any dev Lambda role> --profile tour-data-api-dev-deploy` | **Denied** (explicit deny) |
| 8 | `aws cloudformation delete-stack --stack-name dev --profile tour-data-api-dev-deploy` | **Denied** |
| 9 | `AWS_PROFILE=tour-data-api-test-deploy make deploy-test` | Succeeds |
| 10 | `curl <ApiEndpoint>/v1/tours` | `401` (API is up, authentication required) |
| 11 | Provision one tour in dev (`make provision-tour ...`, or `POST /v1/tours` with `"provisioning": true`) | Succeeds: the boundary does not block runtime table creation |
| 12 | Prod, later: run the workflow on `main` | Deploys to prod. Confirm the prod role cannot be assumed from `develop` and the dev role not from `main` (a run that picks the wrong secret fails at *Configure AWS credentials*). |

`trust.json` for check 6 can be any valid trust policy. No role is created if the check behaves as expected; delete it if it is.

---

## What the deploy roles can and cannot do

All permissions are limited to the target stack's resource names (`<env>-*`), the region and the account.

| Service | Allowed | Deliberately not allowed |
|---|---|---|
| CloudFormation | Change sets (create, describe, execute, delete), describe stacks, events and resources, get template, validate; the `Serverless-2016-10-31` transform | `DeleteStack`, stacks other than `<env>` |
| S3 | SAM artifacts bucket: put/get object, list. Application buckets (`<env>-artifacts-*`, `<env>-photos-*`): create and configure (encryption, public access block, versioning, CORS, lifecycle, notifications, policy, tags) | Reading or writing application objects, `DeleteBucket` |
| DynamoDB | The 10 shared tables **by exact name**: create/update/describe, backups, TTL, tags. `GetItem`/`PutItem` on `<env>-AppConfig` and `<env>-NotificationRule` only, for seeding | All other item-level actions, `DeleteTable`, tour-specific tables (`<env>-TourRider-*` and so on, which only the Lambda roles create at runtime) |
| Lambda | Functions `<env>-*`, layer `<env>-common-layer`, event source mappings for `<env>-*` functions | Functions of other stacks |
| IAM | Create/modify roles named `<env>-*` **only with this stack's permissions boundary**; attach only `AWSLambdaBasicExecutionRole`; pass roles to `lambda.amazonaws.com` only | Roles without the boundary, removing the boundary (explicit deny), changing `tour-data-api-*` roles and policies including the deploy roles themselves and the boundary (explicit deny), users, access keys, OIDC providers (explicit deny), editing a role's trust policy |
| API Gateway | HTTP APIs, stages, authorizers, routes, tags in the region (API IDs are random, so they cannot be scoped by name) | |
| Cognito | Create user pools tagged `Project=tour-data-api`/`Environment=<env>`; modify pools carrying those tags (pool, client, group, MFA, tags) | `Admin*`, `ListUsers` (user data), `DeleteUserPool`, `DeleteGroup`, `DeleteUserPoolClient` |
| SQS / CloudWatch / EventBridge | `<env>-push-sender-dlq` queue; alarms `<env>-*`; rules `<env>-*` | |
| SSM | Create, update, tag and delete parameters under `/tour-data-api/<env>/` (client app configuration, public values) | Everything else, including the Expo token parameters under `/<env>/` |
| KMS, CloudWatch Logs | – | Everything |

The boundary (`tour-data-api-<env>-lambda-boundary`) is the ceiling for Lambda roles: logs for `/aws/lambda/<env>-*`, DynamoDB data and tour-table provisioning on `<env>-*` tables, S3 object access on the two application buckets, Cognito user administration, `ssm:GetParameter` on `/<env>/*`, `kms:Decrypt` via SSM, SQS send to the dead-letter queue, and Lambda event-source-mapping and invoke permissions for `<env>-*` functions. A role's effective permissions are its own policies intersected with this boundary.

> A custom `ExpoTokenParamRider` / `ExpoTokenParamMgmt` outside `/<env>/` is blocked by the boundary. Keep Expo token parameters under `/<env>/`, or extend the boundary.

---

## Keeping the policies in sync

The policies list resources and actions explicitly. Update the matching `deploy-access` stack **before** deploying the application change that needs it (re-run the Step 3 command for each environment, in the right account):

| Change in `template.yaml` | Update in `deploy-access.yaml` |
|---|---|
| New **shared DynamoDB table** | Add it to `SharedTablesControlPlane` (`DeployPolicyCore`). If it has a stream, add the stream ARN to `NotificationStreamMetadata`. |
| New **action or resource type** in a Lambda function policy (for example a new Cognito or S3 action) | Add it to `LambdaPermissionsBoundary`; otherwise the function is denied at runtime. |
| New **AWS resource type** (for example an SNS topic or a Step Functions state machine) | Add its create/update/describe/tag permissions, scoped to `<env>-*`, to the deploy policies. Check the CloudFormation handler permissions: `aws cloudformation describe-type --type RESOURCE --type-name AWS::<Service>::<Type> --query Schema` and read `handlers.*.permissions`. |
| New **client app configuration parameter** under `/tour-data-api/<env>/<app>/` | Nothing: the deploy roles and the read roles (`consumer-read-access.yaml`) already cover the path. Update the [contract](../design/client-configuration.md). A new `<app>` folder needs a new `ClientApp` value and read-role stacks. |
| New **region** | Change the region in the stacks (ARNs use the stack region). Also update the workflow and `samconfig.toml`. |
| Any change to a managed policy | Change only its `PolicyDocument`. `ManagedPolicyName`, `Description` and `Path` force a replacement, which fails for these named policies with "A policy called ... already exists". |
| Each managed policy is limited to 6,144 non-whitespace characters | If `DeployPolicyCore` or `DeployPolicyCompute` grows too large, split it and attach the new policy to both roles. |

## Known limits and residual risk

- **Deploying is code execution.** A run of the workflow ships whatever is on `develop`/`main`, and that code executes with the Lambda roles' permissions (data access, up to the boundary). The deploy role cannot read data itself, but protecting the two branches (Step 1) is what protects the data. Deploy roles can also create a Lambda role with an arbitrary trust policy as long as it carries the boundary, so the boundary — not the deploy policy — is the real ceiling.
- **Deploy roles cannot delete tables, buckets, user pools or stacks.** A failed first deployment, or an update that fails after creating a new table or bucket, leaves CloudFormation unable to roll that resource back (`ROLLBACK_FAILED` / `UPDATE_ROLLBACK_FAILED`). An administrator must continue the rollback or delete the stack (also required to remove the stack deliberately: `make delete` with admin credentials). This is by design.
- **The SAM artifacts bucket expires objects after 30 days.** If an update fails and CloudFormation has to roll back Lambda code that was last deployed more than 30 days ago, the old package is gone and the rollback can fail; redeploy a fixed version instead. Raise `ExpirationInDays` in `deploy-access.yaml` if that is a concern (cost is negligible).
- **Existing roles must carry the boundary before the deploy roles can modify them** (Step 6).
- `lambda:ListEventSourceMappings` and `dynamodb:ListStreams` do not support resource-level scoping in IAM and are granted on `*` (metadata only).
- The Cognito create permission relies on `CreateUserPool` carrying the `Project`/`Environment` tags in the same call (the template's `UserPoolTags` do). If a first deployment fails with `AccessDenied` on `cognito-idp:CreateUserPool` or `TagResource`, see [Troubleshooting](#troubleshooting).
- Role names `<env>-*` are shared with any other stack called `dev`, `test` or `prod` in the same account; keep those names for this application only.

---

## Troubleshooting

**`AccessDenied` during deployment.** The CloudFormation event or `sam deploy` output names the action and resource ("... is not authorized to perform: `iam:CreateRole` on resource ..."). For the exact denied call, search CloudTrail (events appear after up to ~15 minutes; requires `jq`):

```bash
aws cloudtrail lookup-events --max-results 100 \
  --lookup-attributes AttributeKey=EventSource,AttributeValue=iam.amazonaws.com --output json \
| jq -r '.Events[].CloudTrailEvent | fromjson | select(.errorCode != null)
         | [.eventTime, .userIdentity.arn, .eventName, .errorCode, .errorMessage] | @tsv'
```

Change `iam.amazonaws.com` to the service in question (`dynamodb`, `lambda`, `cognito-idp`, ...). Then decide: if the call is legitimate, add it to the right place in `deploy-access.yaml` (see [Keeping the policies in sync](#keeping-the-policies-in-sync)) and update the stack.

**`sts:AssumeRoleWithWebIdentity` / "Not authorized to perform sts:AssumeRoleWithWebIdentity".**
- The workflow ran on a branch other than the role's branch (`develop` for dev, `main` for prod).
- The secret holds the wrong role ARN (a dev ARN in `AWS_DEPLOY_ROLE_ARN_PROD`, or the role is in another account).
- The job uses `environment:`, which changes the `sub` claim.
- The repository name or organization in the stack parameters does not match (`GitHubOrg`, `GitHubRepo`; they are case sensitive).

**Terminal profile: "AccessDenied" on `AssumeRole`.** The caller is not `TerminalPrincipalArn`, or MFA is required (`TerminalRequireMfa=true`) and the session has no MFA. Add `mfa_serial`, or set `TerminalRequireMfa=false` for Identity Center principals and update the stack.

**`AccessDenied` on `iam:CreateRole` / `iam:PutRolePolicy`.** The role carries no boundary. For existing stacks, run the one-time administrator deployment from [Step 6](#step-6-first-deployment). For new roles, check that `Globals.Function.PermissionsBoundary` in `template.yaml` points to `tour-data-api-<stack>-lambda-boundary` and that the deploy-access stack for that environment exists in the same account.

**Lambda `AccessDeniedException` at runtime after a deployment.** The function role is allowed the action, but the boundary is not. Compare the action in the function's policy with `LambdaPermissionsBoundary` and update the deploy-access stack.

**`sam deploy` asks for a bucket / "Missing option --s3-bucket" / "Cannot use both ... resolve_s3 and s3_bucket".** Pass `--s3-bucket tour-data-api-sam-<env>-<account-id>` (the make targets and the workflow do), and do not add `resolve_s3` to `[*.deploy.parameters]` in `samconfig.toml`.

**Stack stuck in `ROLLBACK_FAILED` or `UPDATE_ROLLBACK_FAILED`.** See [Known limits](#known-limits-and-residual-risk). With administrator credentials: `aws cloudformation continue-update-rollback --stack-name <env>` (update rollback) or delete the stack (create rollback), then redeploy.

**Update a deploy-access stack.** Re-run the Step 3 command for that environment with the same parameters; unchanged resources are left alone. To preview first, add `--no-execute-changeset` and check the change set: the managed policies and roles must show `Modify` with `Replacement: False`.

**"A policy called tour-data-api-<env>-deploy-... already exists" (`AlreadyExists`) on a stack update.** A change to a managed policy's `ManagedPolicyName`, `Description` or `Path` requires a replacement, and the new policy cannot be created under the same name. Revert that property, keep only the `PolicyDocument` change, and re-run. The failed update rolls back on its own; confirm the stack is `UPDATE_ROLLBACK_COMPLETE` first.

**Remove an environment's access.** With administrator credentials: empty the SAM artifacts bucket (`aws s3 rm s3://tour-data-api-sam-<env>-<account-id> --recursive`), then delete the `tour-data-api-deploy-access-<env>` stack. The application stack is not touched.

---

[← Documentation index](../README.md) · [Deployment Guide](deployment.md) · [Infrastructure Guide](infrastructure.md)
