#!/usr/bin/env python3
"""Bootstrap notification push prerequisites for a deployed stack."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import ClientError


def _default_param_path(stack_name: str, app: str) -> str:
    return f"/{stack_name}/push/expo-token/{app}"


def _put_secure_string(
    ssm_client,
    name: str,
    value: str,
    overwrite: bool,
) -> None:
    ssm_client.put_parameter(
        Name=name,
        Value=value,
        Type="SecureString",
        Overwrite=overwrite,
        Tier="Standard",
    )


def _run_seed_script(script_name: str, table_name: str, region: str) -> None:
    script_path = Path(__file__).resolve().parent / script_name
    subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--table-name",
            table_name,
            "--region",
            region,
        ],
        check=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Set Expo token SSM parameters required by Notification push sender "
            "and optionally seed notification defaults."
        )
    )
    parser.add_argument(
        "--stack-name",
        required=True,
        help="CloudFormation stack name (for default SSM parameter paths/table names).",
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", "ap-south-1"),
        help="AWS region (default: AWS_REGION env or ap-south-1).",
    )
    parser.add_argument(
        "--rider-param-path",
        help="SSM parameter path for rider Expo token (default: /<stack>/push/expo-token/rider).",
    )
    parser.add_argument(
        "--mgmt-param-path",
        help="SSM parameter path for mgmt Expo token (default: /<stack>/push/expo-token/mgmt).",
    )
    parser.add_argument(
        "--rider-token",
        help="Expo access token for rider app push delivery (or use EXPO_RIDER_ACCESS_TOKEN env var).",
    )
    parser.add_argument(
        "--mgmt-token",
        help="Expo access token for management app push delivery (or use EXPO_MGMT_ACCESS_TOKEN env var).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing SSM parameters when they already exist.",
    )
    parser.add_argument(
        "--seed-notification-rules",
        action="store_true",
        help="Also run scripts/seed_notification_rules.py against <stack>-NotificationRule.",
    )
    parser.add_argument(
        "--seed-app-config",
        action="store_true",
        help="Also run scripts/seed_app_config.py against <stack>-AppConfig.",
    )
    return parser.parse_args()


def _resolve_token(arg_value: Optional[str], env_name: str) -> Optional[str]:
    value = arg_value or os.environ.get(env_name)
    if value:
        return value.strip()
    return None


def main() -> int:
    args = parse_args()
    stack_name = args.stack_name
    region = args.region

    rider_param_path = args.rider_param_path or _default_param_path(stack_name, "rider")
    mgmt_param_path = args.mgmt_param_path or _default_param_path(stack_name, "mgmt")

    rider_token = _resolve_token(args.rider_token, "EXPO_RIDER_ACCESS_TOKEN")
    mgmt_token = _resolve_token(args.mgmt_token, "EXPO_MGMT_ACCESS_TOKEN")

    ssm = boto3.client("ssm", region_name=region)
    updated_count = 0

    if rider_token:
        try:
            _put_secure_string(ssm, rider_param_path, rider_token, args.overwrite)
            print(f"Updated SSM SecureString: {rider_param_path}")
            updated_count += 1
        except ClientError as exc:
            print(f"Failed updating {rider_param_path}: {exc}")
            return 1
    else:
        print("Skipped rider Expo token update (no token provided).")

    if mgmt_token:
        try:
            _put_secure_string(ssm, mgmt_param_path, mgmt_token, args.overwrite)
            print(f"Updated SSM SecureString: {mgmt_param_path}")
            updated_count += 1
        except ClientError as exc:
            print(f"Failed updating {mgmt_param_path}: {exc}")
            return 1
    else:
        print("Skipped mgmt Expo token update (no token provided).")

    if args.seed_notification_rules:
        rules_table = f"{stack_name}-NotificationRule"
        print(f"Seeding notification rules in {rules_table}...")
        _run_seed_script("seed_notification_rules.py", rules_table, region)

    if args.seed_app_config:
        app_config_table = f"{stack_name}-AppConfig"
        print(f"Seeding app config defaults in {app_config_table}...")
        _run_seed_script("seed_app_config.py", app_config_table, region)

    if updated_count == 0 and not args.seed_notification_rules and not args.seed_app_config:
        print(
            "No changes made. Provide --rider-token/--mgmt-token (or env vars) "
            "and/or enable seeding flags."
        )
        return 1

    print("Notification bootstrap complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
