#!/usr/bin/env python3
"""Dev test setup utility for manual API testing.

Run directly:
    python3 scripts/dev-test-setup.py --stack-name dev --user-pool mgmt

The script prints `export ...` lines so you can eval or copy/paste them if you
want the variables in your current shell session.
"""

from __future__ import annotations

import argparse
import getpass
import os
import shlex
import sys
from typing import Dict, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

POOL_CONFIG = {
    "mgmt": {
        "label": "tour-mgmt-app",
        "api_endpoint_key": "ApiEndpoint",
        "user_pool_id_key": "CognitoUserPoolIdOutput",
        "client_id_key": "CognitoAppClientIdOutput",
        "default_username": "tot.admin@someusefulapps.com",
        "username_env_var": "MGMT_TEST_USERNAME",
    },
    "rider": {
        "label": "tour-rider-app",
        "api_endpoint_key": "RiderApiEndpoint",
        "user_pool_id_key": "CognitoRiderUserPoolIdOutput",
        "client_id_key": "CognitoRiderAppClientIdOutput",
        "default_username": "rider.user@someusefulapps.com",
        "username_env_var": "RIDER_TEST_USERNAME",
    },
}


def log(message: str = "") -> None:
    print(message, file=sys.stderr)


def fail(message: str, code: int = 1) -> int:
    log(message)
    return code


def choose_user_pool_interactive() -> str:
    log("Choose user pool for test preparation:")
    log("  1) mgmt  (tour-mgmt-app)")
    log("  2) rider (tour-rider-app)")
    while True:
        choice = input("Enter choice [1/2]: ").strip()
        if choice == "1":
            return "mgmt"
        if choice == "2":
            return "rider"
        log("Invalid selection. Enter 1 or 2.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export API test environment variables from CloudFormation stack outputs."
    )
    parser.add_argument(
        "--stack-name",
        default="dev",
        help="CloudFormation stack name (default: dev)",
    )
    parser.add_argument(
        "--user-pool",
        choices=sorted(POOL_CONFIG.keys()),
        help="User pool selection: mgmt or rider (required unless interactive)",
    )
    parser.add_argument(
        "--username",
        help="Cognito username/email for auth. If omitted, uses pool-specific env var or default.",
    )
    parser.add_argument(
        "--password",
        help="Password for Cognito auth. Prefer TEST_PASSWORD env var to avoid shell history.",
    )
    parser.add_argument(
        "--skip-token",
        action="store_true",
        help="Skip Cognito auth and only export stack/pool details.",
    )
    return parser.parse_args()


def get_stack_outputs(stack_name: str) -> Dict[str, str]:
    cf = boto3.client("cloudformation")
    response = cf.describe_stacks(StackName=stack_name)
    stacks = response.get("Stacks", [])
    if not stacks:
        raise RuntimeError(f"Stack '{stack_name}' not found")

    outputs = stacks[0].get("Outputs", [])
    return {
        item["OutputKey"]: item["OutputValue"]
        for item in outputs
        if "OutputKey" in item and "OutputValue" in item
    }


def get_stack_status(stack_name: str) -> str:
    cf = boto3.client("cloudformation")
    response = cf.describe_stacks(StackName=stack_name)
    stacks = response.get("Stacks", [])
    if not stacks:
        raise RuntimeError(f"Stack '{stack_name}' not found")
    return stacks[0].get("StackStatus", "UNKNOWN")


def initiate_auth(client_id: str, username: str, password: str) -> Dict[str, object]:
    cognito = boto3.client("cognito-idp")
    return cognito.initiate_auth(
        AuthFlow="USER_PASSWORD_AUTH",
        ClientId=client_id,
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )


def print_exports(export_map: Dict[str, str]) -> None:
    for key, value in export_map.items():
        print(f"export {key}={shlex.quote(value)}")


def main() -> int:
    args = parse_args()
    stack_name = args.stack_name

    log("")
    log(f"=== Dev Test Setup - {stack_name} ===")
    log("")

    log(f"{'Checking AWS credentials...':<45}")
    try:
        boto3.client("sts").get_caller_identity()
    except (BotoCoreError, ClientError) as exc:
        return fail(
            "FAILED\n"
            "  Error: AWS credentials not configured or invalid. "
            "Run 'aws configure' or set credentials.\n"
            f"  Details: {exc}"
        )
    log("OK")

    log(f"{'Checking stack ' + repr(stack_name) + '...':<45}")
    try:
        stack_status = get_stack_status(stack_name)
    except (BotoCoreError, ClientError, RuntimeError) as exc:
        return fail(
            "FAILED\n"
            f"  Error: Stack '{stack_name}' not found or inaccessible.\n"
            f"  Details: {exc}"
        )
    log(f"OK ({stack_status})")

    log("")
    log("Fetching stack outputs...")
    try:
        outputs = get_stack_outputs(stack_name)
    except (BotoCoreError, ClientError, RuntimeError) as exc:
        return fail(f"  Error: Failed to fetch stack outputs.\n  Details: {exc}")

    print('echo "After stack outputs are retrieved......"')

    user_pool = args.user_pool
    print(
        f"echo \"{'User pool selection: ' + repr(user_pool) if user_pool else 'No user pool selected.'}\""
    )
    if not user_pool:
        if sys.stdin.isatty():
            user_pool = choose_user_pool_interactive()
        else:
            return fail(
                "Error: --user-pool is required in non-interactive mode. "
                "Choose one: mgmt or rider."
            )

    config = POOL_CONFIG[user_pool]
    api_endpoint = outputs.get(config["api_endpoint_key"], "")
    user_pool_id = outputs.get(config["user_pool_id_key"], "")
    client_id = outputs.get(config["client_id_key"], "")

    if not api_endpoint:
        return fail(
            "  Error: Could not retrieve API endpoint from stack outputs.\n"
            f"  Missing output key: {config['api_endpoint_key']}"
        )

    selected_username_env = config["username_env_var"]
    selected_username = (
        args.username
        or os.environ.get(selected_username_env)
        or os.environ.get("TEST_USERNAME")
        or config["default_username"]
    )

    log(f"  USER_POOL_TYPE = {user_pool} ({config['label']})")
    log(f"  API_ENDPOINT   = {api_endpoint}")
    log(f"  USER_POOL_ID   = {user_pool_id or 'not set'}")
    log(f"  CLIENT_ID      = {client_id or 'not set'}")
    log(f"  TEST_USERNAME  = {selected_username}")

    export_map = {
        "STACK_NAME": stack_name,
        "USER_POOL_TYPE": user_pool,
        "API_ENDPOINT": api_endpoint,
        "USER_POOL_ID": user_pool_id,
        "CLIENT_ID": client_id,
        "USER_ID": selected_username,
        "TEST_USERNAME": selected_username,
    }

    log("")
    if args.skip_token:
        log("Skipping token retrieval (--skip-token set).")
        print_exports(export_map)
        return 0

    if not user_pool_id or not client_id:
        log("Skipping token retrieval (user pool outputs not available for selection).")
        log("Set BEARER_TOKEN manually if needed.")
        print_exports(export_map)
        return 0

    password = args.password or os.environ.get("TEST_PASSWORD", "")
    if not password:
        log(f"Enter password for {selected_username}")
        log("  (or set TEST_PASSWORD env var / use --password to skip prompt)")
        password = getpass.getpass("  Password: ")

    if not password:
        log("  No password provided. Skipping token retrieval.")
        log("  Set BEARER_TOKEN manually.")
        print_exports(export_map)
        return 0

    log(f"{'Fetching JWT token...':<45}")
    try:
        auth_result = initiate_auth(client_id, selected_username, password)
    except (BotoCoreError, ClientError) as exc:
        return fail(
            "FAILED\n"
            "  Error: Authentication failed (see details below).\n"
            "\n"
            "  Possible causes:\n"
            f"    - User '{selected_username}' does not exist in the selected user pool\n"
            "    - Incorrect password\n"
            "    - User pool or client ID is invalid\n"
            "\n"
            "  To create the test user:\n"
            f"    aws cognito-idp admin-create-user --user-pool-id {user_pool_id} "
            f"--username {selected_username} --user-attributes Name=email,Value={selected_username}\n"
            f"\n  Details: {exc}"
        )

    challenge_name = str(auth_result.get("ChallengeName") or "")
    if challenge_name:
        lines = [
            "FAILED",
            f"  Error: Cognito returned a challenge: {challenge_name}",
        ]
        if challenge_name == "NEW_PASSWORD_REQUIRED":
            lines.extend(
                [
                    "  The user must set a permanent password before authenticating.",
                    "  Run: aws cognito-idp admin-set-user-password "
                    f"--user-pool-id {user_pool_id} --username {selected_username} "
                    "--password <NEW_PASSWORD> --permanent",
                ]
            )
        return fail("\n".join(lines))

    token: Optional[str] = None
    auth_payload = auth_result.get("AuthenticationResult")
    if isinstance(auth_payload, dict):
        id_token = auth_payload.get("IdToken")
        if isinstance(id_token, str) and id_token:
            token = id_token

    if not token:
        return fail("FAILED\n  Error: Could not extract IdToken from auth response.")

    export_map["BEARER_TOKEN"] = token
    log("OK")

    log("")
    log("=== Ready to test! ===")
    log("")
    log("  Example commands:")
    log(
        "    curl -w '\\n' -H \"Authorization: Bearer $BEARER_TOKEN\" $API_ENDPOINT/v1/tours"
    )
    log(
        "    curl -w '\\n' -H \"Authorization: Bearer $BEARER_TOKEN\" $API_ENDPOINT/v1/tours/active"
    )
    log("")
    log(
        "  Exported variables: STACK_NAME, USER_POOL_TYPE, API_ENDPOINT, USER_POOL_ID, "
        "CLIENT_ID, USER_ID, TEST_USERNAME, BEARER_TOKEN"
    )
    log("")

    print_exports(export_map)
    return 0


if __name__ == "__main__":
    sys.exit(main())
