#!/usr/bin/env bash
# =============================================================================
# Dev Test Setup — Exports environment variables for API testing
# =============================================================================
# Usage:
#   source scripts/dev-test-setup.sh                  # Uses default stack
#   source scripts/dev-test-setup.sh <stack-name>     # Custom stack name
#
# After running, you can test the API with:
#   curl -H "Authorization: Bearer $BEARER_TOKEN" $API_ENDPOINT/v1/tours
#
# Variables exported:
#   STACK_NAME       — CloudFormation stack name
#   API_ENDPOINT     — Full API Gateway endpoint URL
#   USER_POOL_ID     — Cognito User Pool ID
#   CLIENT_ID        — Cognito App Client ID
#   BEARER_TOKEN     — JWT IdToken for API requests
# =============================================================================

set -uo pipefail

# -------------------------------------------------------------------------
# Configuration
# -------------------------------------------------------------------------
STACK_NAME="${1:-dev}"
TEST_USERNAME="${TEST_USERNAME:-tot.admin@someusefulapps.com}"
TEST_PASSWORD="${TEST_PASSWORD:-}"

echo ""
echo "=== Dev Test Setup — $STACK_NAME ==="
echo ""

# -------------------------------------------------------------------------
# Verify AWS credentials
# -------------------------------------------------------------------------
printf "%-45s" "Checking AWS credentials..."
if ! aws sts get-caller-identity &>/dev/null; then
    echo "FAILED"
    echo "  Error: AWS credentials not configured. Run 'aws configure' or set credentials."
    return 1 2>/dev/null || exit 1
fi
echo "OK"

# -------------------------------------------------------------------------
# Verify stack exists
# -------------------------------------------------------------------------
printf "%-45s" "Checking stack '$STACK_NAME'..."
STACK_STATUS=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query "Stacks[0].StackStatus" \
    --output text 2>/dev/null)

if [[ -z "$STACK_STATUS" || "$STACK_STATUS" == "None" ]]; then
    echo "FAILED"
    echo "  Error: Stack '$STACK_NAME' not found. Deploy first with 'sam deploy'."
    return 1 2>/dev/null || exit 1
fi
echo "OK ($STACK_STATUS)"

# -------------------------------------------------------------------------
# Fetch CloudFormation outputs (single API call)
# -------------------------------------------------------------------------
echo ""
echo "Fetching stack outputs..."

if ! STACK_OUTPUTS=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs" \
    --output json); then
    echo "  Error: Failed to fetch stack outputs (see AWS error above)."
    return 1 2>/dev/null || exit 1
fi

# Extract individual outputs
API_ENDPOINT=$(echo "$STACK_OUTPUTS" | python3 -c "
import sys, json
outputs = json.load(sys.stdin)
for o in outputs:
    if o['OutputKey'] == 'ApiEndpoint':
        print(o['OutputValue'])
        break
" 2>/dev/null)

USER_POOL_ID=$(echo "$STACK_OUTPUTS" | python3 -c "
import sys, json
outputs = json.load(sys.stdin)
for o in outputs:
    if o['OutputKey'] == 'CognitoUserPoolIdOutput':
        print(o['OutputValue'])
        break
" 2>/dev/null)

CLIENT_ID=$(echo "$STACK_OUTPUTS" | python3 -c "
import sys, json
outputs = json.load(sys.stdin)
for o in outputs:
    if o['OutputKey'] == 'CognitoAppClientIdOutput':
        print(o['OutputValue'])
        break
" 2>/dev/null)

# Validate outputs
if [[ -z "$API_ENDPOINT" ]]; then
    echo "  Error: Could not retrieve API endpoint from stack outputs."
    echo "  Ensure the stack deployed successfully and has an 'ApiEndpoint' output."
    return 1 2>/dev/null || exit 1
fi

if [[ -z "$USER_POOL_ID" ]]; then
    echo "  Warning: Cognito User Pool ID not found in stack outputs."
    echo "  Set USER_POOL_ID and CLIENT_ID manually if needed."
fi

echo "  API_ENDPOINT  = $API_ENDPOINT"
echo "  USER_POOL_ID  = ${USER_POOL_ID:-not set}"
echo "  CLIENT_ID     = ${CLIENT_ID:-not set}"

export STACK_NAME API_ENDPOINT USER_POOL_ID CLIENT_ID

# -------------------------------------------------------------------------
# Get JWT token
# -------------------------------------------------------------------------
echo ""

if [[ -z "$USER_POOL_ID" || -z "$CLIENT_ID" ]]; then
    echo "Skipping token retrieval (Cognito outputs not available)."
    echo "Set BEARER_TOKEN manually."
    echo ""
    return 0 2>/dev/null || exit 0
fi

# Prompt for password if not set
if [[ -z "$TEST_PASSWORD" ]]; then
    echo "Enter password for $TEST_USERNAME"
    echo "  (or set TEST_PASSWORD env var to skip this prompt)"
    read -rsp "  Password: " TEST_PASSWORD
    echo ""
fi

if [[ -z "$TEST_PASSWORD" ]]; then
    echo "  No password provided. Skipping token retrieval."
    echo "  Set BEARER_TOKEN manually."
    echo ""
    return 0 2>/dev/null || exit 0
fi

printf "%-45s" "Fetching JWT token..."
if ! AUTH_RESULT=$(aws cognito-idp initiate-auth \
    --auth-flow USER_PASSWORD_AUTH \
    --client-id "$CLIENT_ID" \
    --auth-parameters "USERNAME=$TEST_USERNAME,PASSWORD=$TEST_PASSWORD"); then
    echo "FAILED"
    echo "  Error: Authentication failed (see AWS error above)."
    echo ""
    echo "  Possible causes:"
    echo "    - User '$TEST_USERNAME' does not exist in the user pool"
    echo "    - Incorrect password"
    echo "    - User pool or client ID is invalid"
    echo ""
    echo "  To create the test user:"
    echo "    aws cognito-idp admin-create-user --user-pool-id $USER_POOL_ID --username $TEST_USERNAME --user-attributes Name=email,Value=$TEST_USERNAME"
    echo ""
    return 1 2>/dev/null || exit 1
fi

if [[ -z "$AUTH_RESULT" ]]; then
    echo "FAILED"
    echo "  Error: Authentication returned an empty response."
    return 1 2>/dev/null || exit 1
fi

# Check for Cognito auth challenges (e.g., NEW_PASSWORD_REQUIRED for first-time login)
CHALLENGE_NAME=$(echo "$AUTH_RESULT" | python3 -c "import sys, json; r=json.load(sys.stdin); print(r.get('ChallengeName', ''))" 2>/dev/null)

if [[ -n "$CHALLENGE_NAME" ]]; then
    echo "FAILED"
    echo "  Error: Cognito returned a challenge: $CHALLENGE_NAME"
    if [[ "$CHALLENGE_NAME" == "NEW_PASSWORD_REQUIRED" ]]; then
        echo "  The user must set a permanent password before authenticating."
        echo "  Run: aws cognito-idp admin-set-user-password --user-pool-id $USER_POOL_ID --username $TEST_USERNAME --password <NEW_PASSWORD> --permanent"
    fi
    echo ""
    return 1 2>/dev/null || exit 1
fi

BEARER_TOKEN=$(echo "$AUTH_RESULT" | python3 -c "import sys, json; print(json.load(sys.stdin)['AuthenticationResult']['IdToken'])" 2>/dev/null)

if [[ -z "$BEARER_TOKEN" ]]; then
    echo "FAILED"
    echo "  Error: Could not extract IdToken from auth response."
    echo "  Unexpected response structure:"
    echo "$AUTH_RESULT" | python3 -c "import sys, json; print(json.dumps(json.load(sys.stdin), indent=2))" 2>/dev/null | head -20
    return 1 2>/dev/null || exit 1
fi

export BEARER_TOKEN
echo "OK"

# -------------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------------
echo ""
echo "=== Ready to test! ==="
echo ""
echo "  Example commands:"
echo "    curl -H \"Authorization: Bearer \$BEARER_TOKEN\" \$API_ENDPOINT/v1/tours"
echo "    curl -H \"Authorization: Bearer \$BEARER_TOKEN\" \$API_ENDPOINT/v1/tours/active"
echo ""
echo "  Exported variables: STACK_NAME, API_ENDPOINT, USER_POOL_ID, CLIENT_ID, BEARER_TOKEN"
echo ""
