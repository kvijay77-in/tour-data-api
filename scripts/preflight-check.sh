#!/usr/bin/env bash
# =============================================================================
# Preflight Check — Validates environment before deployment
# =============================================================================
# Run: make check-config   OR   bash scripts/preflight-check.sh
#
# Checks:
#   1. AWS CLI installed and configured
#   2. SAM CLI installed
#   3. Python 3.11+ installed
#   4. samconfig.toml exists
#   5. SAM template is valid
#   6. Git available
# =============================================================================

set -uo pipefail

PASS="✓"
FAIL="✗"
WARN="!"
passed=0
failed=0
warnings=0

echo ""
echo "=== Tour Data API — Preflight Check ==="
echo ""

# -------------------------------------------------------------------------
# 1. AWS CLI
# -------------------------------------------------------------------------
printf "%-45s" "AWS CLI installed"
if command -v aws &>/dev/null; then
    version=$(aws --version 2>&1 | awk '{print $1}' | cut -d/ -f2)
    echo "$PASS  (v$version)"
    ((passed++))
else
    echo "$FAIL  Not found — install from https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
    ((failed++))
fi

printf "%-45s" "AWS credentials configured"
if aws sts get-caller-identity &>/dev/null; then
    account=$(aws sts get-caller-identity --query 'Account' --output text 2>/dev/null)
    echo "$PASS  (account: $account)"
    ((passed++))
else
    echo "$FAIL  Run 'aws configure' or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY"
    ((failed++))
fi

printf "%-45s" "AWS region set"
region=$(aws configure get region 2>/dev/null || echo "")
if [[ -n "$region" ]]; then
    echo "$PASS  ($region)"
    ((passed++))
else
    echo "$WARN  No default region — set with 'aws configure set region us-east-1'"
    ((warnings++))
fi

# -------------------------------------------------------------------------
# 2. SAM CLI
# -------------------------------------------------------------------------
printf "%-45s" "SAM CLI installed"
if command -v sam &>/dev/null; then
    sam_version=$(sam --version 2>&1 | awk '{print $NF}')
    echo "$PASS  (v$sam_version)"
    ((passed++))
else
    echo "$FAIL  Not found — install from https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html"
    ((failed++))
fi

# -------------------------------------------------------------------------
# 3. Python 3.11+
# -------------------------------------------------------------------------
printf "%-45s" "Python 3.11+ installed"
if command -v python3 &>/dev/null; then
    py_version=$(python3 --version 2>&1 | awk '{print $2}')
    py_major=$(echo "$py_version" | cut -d. -f1)
    py_minor=$(echo "$py_version" | cut -d. -f2)
    if [[ "$py_major" -ge 3 && "$py_minor" -ge 11 ]]; then
        echo "$PASS  (v$py_version)"
        ((passed++))
    else
        echo "$FAIL  Found v$py_version — need 3.11 or higher"
        ((failed++))
    fi
else
    echo "$FAIL  Not found — install from https://www.python.org/downloads/"
    ((failed++))
fi

# -------------------------------------------------------------------------
# 4. samconfig.toml
# -------------------------------------------------------------------------
printf "%-45s" "samconfig.toml exists"
if [[ -f "samconfig.toml" ]]; then
    echo "$PASS"
    ((passed++))
else
    echo "$FAIL  Not found in current directory"
    ((failed++))
fi

# -------------------------------------------------------------------------
# 5. SAM template validation
# -------------------------------------------------------------------------
printf "%-45s" "SAM template valid"
if command -v sam &>/dev/null; then
    if sam validate --lint &>/dev/null; then
        echo "$PASS"
        ((passed++))
    else
        echo "$FAIL  Run 'sam validate --lint' to see errors"
        ((failed++))
    fi
else
    echo "$WARN  Skipped (SAM CLI not installed)"
    ((warnings++))
fi

# -------------------------------------------------------------------------
# 6. Git
# -------------------------------------------------------------------------
printf "%-45s" "Git installed"
if command -v git &>/dev/null; then
    git_version=$(git --version 2>&1 | awk '{print $3}')
    echo "$PASS  (v$git_version)"
    ((passed++))
else
    echo "$WARN  Not found — needed for version control"
    ((warnings++))
fi

# -------------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------------
echo ""
echo "--- Results ---"
echo "$PASS Passed:   $passed"
[[ $warnings -gt 0 ]] && echo "$WARN Warnings: $warnings"
[[ $failed -gt 0 ]]   && echo "$FAIL Failed:   $failed"
echo ""

if [[ $failed -gt 0 ]]; then
    echo "Fix the failed checks above before deploying."
    exit 1
else
    echo "All checks passed. Ready to deploy!"
    exit 0
fi
