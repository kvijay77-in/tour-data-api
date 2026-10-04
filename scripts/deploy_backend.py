#!/usr/bin/env python3
"""Resolve management web origins and run a parameter-preserving SAM deploy."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SAM_CONFIG = ROOT / "samconfig.toml"
EXPECTED_MANAGEMENT_WEB_PROJECT = "tour-mgmt-app"
STABLE_STACK_STATUSES = {
    "CREATE_COMPLETE",
    "UPDATE_COMPLETE",
    "IMPORT_COMPLETE",
}
RUNNER = Callable[..., subprocess.CompletedProcess[str]]


class DeploymentError(RuntimeError):
    """Raised when deployment inputs or AWS discovery are unsafe or incomplete."""


def _run_json(command: list[str], region: str, runner: RUNNER) -> dict[str, Any]:
    result = runner(
        [*command, "--region", region, "--output", "json"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise DeploymentError(result.stderr.strip() or "AWS CLI request failed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DeploymentError("AWS CLI returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise DeploymentError("AWS CLI returned an unexpected JSON value")
    return payload


def _is_stack_not_found_error(message: str) -> bool:
    normalized = message.casefold()
    return "does not exist" in normalized or "not exist" in normalized


def _load_sam_configuration(config_env: str) -> tuple[str, dict[str, str]]:
    try:
        with SAM_CONFIG.open("rb") as config_file:
            config = tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise DeploymentError(f"Unable to load {SAM_CONFIG.name}: {exc}") from exc

    selected = config.get(config_env)
    if not isinstance(selected, dict):
        raise DeploymentError(f"SAM config environment {config_env!r} was not found")

    global_parameters = selected.get("global", {}).get("parameters", {})
    deploy_parameters = selected.get("deploy", {}).get("parameters", {})
    stack_name = global_parameters.get("stack_name")
    if not isinstance(stack_name, str) or not stack_name:
        raise DeploymentError(
            f"SAM config environment {config_env!r} has no stack_name"
        )

    configured_overrides = deploy_parameters.get("parameter_overrides", "")
    if not isinstance(configured_overrides, str):
        raise DeploymentError("SAM parameter_overrides must be a string")
    parameters: dict[str, str] = {}
    for token in shlex.split(configured_overrides):
        name, separator, value = token.partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", name):
            raise DeploymentError(f"Invalid SAM parameter override: {token!r}")
        parameters[name] = value
    return stack_name, parameters


def _get_stack(
    stack_name: str, region: str, runner: RUNNER, *, optional: bool
) -> dict[str, Any] | None:
    result = runner(
        [
            "aws",
            "cloudformation",
            "describe-stacks",
            "--stack-name",
            stack_name,
            "--region",
            region,
            "--output",
            "json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        if optional and _is_stack_not_found_error(result.stderr):
            return None
        raise DeploymentError(
            result.stderr.strip() or f"Unable to describe stack {stack_name}"
        )
    try:
        payload = json.loads(result.stdout)
        stacks = payload["Stacks"]
        if len(stacks) != 1 or not isinstance(stacks[0], dict):
            raise ValueError("expected one stack")
        return stacks[0]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DeploymentError(
            f"Unexpected CloudFormation response for stack {stack_name}"
        ) from exc


def _stack_parameter(stack: dict[str, Any], name: str) -> str:
    for parameter in stack.get("Parameters", []):
        if parameter.get("ParameterKey") == name:
            value = parameter.get("ParameterValue", "")
            if not isinstance(value, str):
                raise DeploymentError(f"Stack parameter {name} has an invalid value")
            return value
    return ""


def _is_localhost(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def normalize_origin(value: str, environment: str, *, site_url: bool = False) -> str:
    raw = value.strip()
    if not raw or "*" in raw:
        raise DeploymentError(f"Invalid web origin: {value!r}")
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise DeploymentError(f"Invalid web origin: {value!r}") from exc

    if (
        parsed.scheme not in {"https", "http"}
        or not host
        or "?" in raw
        or "#" in raw
        or parsed.netloc.endswith(":")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (parsed.path and not (site_url and parsed.path == "/"))
    ):
        raise DeploymentError(
            f"Expected an origin without path, query, or userinfo: {value!r}"
        )

    host = host.rstrip(".").lower()
    if not host:
        raise DeploymentError(f"Invalid web origin host: {value!r}")
    try:
        if ":" not in host:
            host = host.encode("idna").decode("ascii")
            labels = host.split(".")
            if any(
                not label
                or len(label) > 63
                or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
                for label in labels
            ):
                raise ValueError("invalid DNS name")
        else:
            ipaddress.IPv6Address(host)
    except (UnicodeError, ValueError) as exc:
        raise DeploymentError(f"Invalid web origin host: {value!r}") from exc

    if port is not None and not 1 <= port <= 65535:
        raise DeploymentError(f"Invalid web origin port: {value!r}")
    if parsed.scheme == "http" and not (
        environment == "dev" and _is_localhost(host) and port is not None
    ):
        raise DeploymentError(
            f"HTTP origins are permitted only for explicit Dev localhost ports: {value!r}"
        )
    if environment == "prod" and _is_localhost(host):
        raise DeploymentError(
            f"Local origins are not permitted in Production: {value!r}"
        )

    default_port = 443 if parsed.scheme == "https" else 80
    authority_host = f"[{host}]" if ":" in host else host
    authority = (
        authority_host if port in (None, default_port) else f"{authority_host}:{port}"
    )
    return f"{parsed.scheme}://{authority}"


def parse_origin_list(value: str, environment: str) -> list[str]:
    if value == "":
        return []
    entries = value.split(",")
    if any(not entry.strip() for entry in entries):
        raise DeploymentError("Origin lists must not contain empty items")
    origins = {normalize_origin(entry, environment) for entry in entries}
    return sorted(origins)


def _hosting_origin(
    *,
    stack_name: str,
    stack_region: str,
    expected_environment: str,
    expected_project: str,
    runner: RUNNER,
) -> str:
    stack = _get_stack(stack_name, stack_region, runner, optional=False)
    if stack is None:
        raise DeploymentError(f"Hosting stack {stack_name} was not found")
    status = stack.get("StackStatus")
    if status not in STABLE_STACK_STATUSES:
        raise DeploymentError(
            f"Hosting stack {stack_name} is not in a stable successful state: {status}"
        )

    tags = {tag.get("Key"): tag.get("Value") for tag in stack.get("Tags", [])}
    if tags.get("Environment") != expected_environment:
        raise DeploymentError(
            f"Hosting stack {stack_name} has the wrong Environment tag"
        )
    if tags.get("Project") != expected_project:
        raise DeploymentError(f"Hosting stack {stack_name} has the wrong Project tag")

    outputs = {
        output.get("OutputKey"): output.get("OutputValue")
        for output in stack.get("Outputs", [])
    }
    site_url = outputs.get("SiteUrl")
    if not isinstance(site_url, str) or not site_url:
        raise DeploymentError(f"Hosting stack {stack_name} has no SiteUrl output")
    try:
        site_url_parts = urlsplit(site_url)
    except ValueError as exc:
        raise DeploymentError(
            f"Hosting stack {stack_name} has an invalid SiteUrl"
        ) from exc
    if site_url_parts.scheme != "https":
        raise DeploymentError("The management hosting SiteUrl must use HTTPS")
    origin = normalize_origin(site_url, expected_environment, site_url=True)
    if _is_localhost(urlsplit(origin).hostname or ""):
        raise DeploymentError(
            "The management hosting SiteUrl must not be a local origin"
        )
    return origin


def _validated_target_environment(
    config_environment: str,
    parameters: dict[str, str],
    env: dict[str, str],
) -> tuple[str, str]:
    environment = parameters.get("Environment")
    if environment not in {"dev", "test", "prod"}:
        raise DeploymentError(
            "SAM parameter_overrides must include Environment=dev|test|prod"
        )
    expected_environment = {"default": "dev"}.get(
        config_environment, config_environment
    )
    if environment != expected_environment:
        raise DeploymentError(
            f"SAM config {config_environment!r} selects {environment!r}, expected {expected_environment!r}"
        )

    region = env.get("AWS_REGION", "").strip()
    expected_region = env.get("EXPECTED_BACKEND_REGION", "").strip()
    if not region or not expected_region:
        raise DeploymentError(
            "AWS_REGION and EXPECTED_BACKEND_REGION must both be configured"
        )
    if region != expected_region:
        raise DeploymentError("AWS_REGION does not match EXPECTED_BACKEND_REGION")
    account_id = env.get("EXPECTED_AWS_ACCOUNT_ID", "").strip()
    if not re.fullmatch(r"\d{12}", account_id):
        raise DeploymentError(
            "EXPECTED_AWS_ACCOUNT_ID must be the approved 12-digit account ID"
        )

    return environment, region


def _resolve_origins(
    *,
    enabled: bool,
    environment: str,
    region: str,
    backend_stack_name: str,
    parameters: dict[str, str],
    env: dict[str, str],
    runner: RUNNER,
) -> None:
    backend_stack = _get_stack(backend_stack_name, region, runner, optional=True)
    previous_origins = (
        _stack_parameter(backend_stack, "ManagementWebAllowedOrigins")
        if backend_stack is not None
        else ""
    )
    configured_origins = parameters.get("ManagementWebAllowedOrigins", "")
    disable_approved = env.get("MANAGEMENT_WEB_DISABLE_APPROVED", "").lower() == "true"
    if not enabled:
        if (previous_origins or configured_origins) and disable_approved:
            parameters["ManagementWebAllowedOrigins"] = ""
            return
        old_origins = set(parse_origin_list(previous_origins, environment))
        configured_origin_list = set(parse_origin_list(configured_origins, environment))
        if configured_origin_list and not old_origins:
            raise DeploymentError(
                "SAM config contains web origins but management web lookup is disabled"
            )
        preserved_origins = sorted(old_origins | configured_origin_list)
        if preserved_origins:
            parameters["ManagementWebAllowedOrigins"] = ",".join(preserved_origins)
        else:
            parameters.pop("ManagementWebAllowedOrigins", None)
        return

    if (
        environment == "test"
        and env.get("MANAGEMENT_WEB_ENABLED", "").lower() != "true"
    ):
        raise DeploymentError(
            "Test deployments remain no-web unless explicitly enabled"
        )
    if env.get("MANAGEMENT_WEB_ENABLED", "").lower() != "true":
        raise DeploymentError("MANAGEMENT_WEB_ENABLED must be exactly true or false")
    if disable_approved:
        raise DeploymentError(
            "MANAGEMENT_WEB_DISABLE_APPROVED cannot be used while web CORS is enabled"
        )

    old_origins = set(parse_origin_list(previous_origins, environment))
    configured_origins = set(parse_origin_list(configured_origins, environment))
    stack_name = env.get("MANAGEMENT_WEB_STACK_NAME", "").strip()
    if not stack_name:
        stack_name = {
            "dev": "tour-mgmt-web-dev",
            "prod": "tour-mgmt-web-prod",
            "test": "",
        }[environment]
    stack_region = env.get("MANAGEMENT_WEB_STACK_REGION", "").strip()
    if not stack_name or not stack_region:
        raise DeploymentError(
            "Enabled management web deployments require MANAGEMENT_WEB_STACK_NAME and MANAGEMENT_WEB_STACK_REGION"
        )

    discovered = _hosting_origin(
        stack_name=stack_name,
        stack_region=stack_region,
        expected_environment=environment,
        expected_project=env.get(
            "MANAGEMENT_WEB_PROJECT_TAG", EXPECTED_MANAGEMENT_WEB_PROJECT
        ),
        runner=runner,
    )
    additions = parse_origin_list(
        env.get("MANAGEMENT_WEB_ADDITIONAL_ORIGINS", ""), environment
    )
    complete_origins = sorted(
        old_origins | configured_origins | set(additions) | {discovered}
    )
    if not complete_origins:
        raise DeploymentError(
            "Enabled management web deployment has no allowed origins"
        )
    parameters["ManagementWebAllowedOrigins"] = ",".join(complete_origins)


def build_sam_command(
    *,
    config_environment: str,
    parameters: dict[str, str],
    region: str,
    extra_args: list[str],
) -> list[str]:
    command = [
        "sam",
        "deploy",
        "--config-env",
        config_environment,
        "--region",
        region,
    ]
    if parameters:
        command.extend(["--parameter-overrides"])
        command.extend(
            f"{parameter_name}={value}" for parameter_name, value in parameters.items()
        )
    command.extend(extra_args)
    return command


def deploy(
    *,
    config_environment: str,
    extra_args: list[str],
    env: dict[str, str],
    runner: RUNNER = subprocess.run,
) -> int:
    backend_stack_name, parameters = _load_sam_configuration(config_environment)
    environment, region = _validated_target_environment(
        config_environment, parameters, env
    )
    caller = _run_json(["aws", "sts", "get-caller-identity"], region, runner)
    if caller.get("Account") != env["EXPECTED_AWS_ACCOUNT_ID"].strip():
        raise DeploymentError(
            "Active AWS account does not match EXPECTED_AWS_ACCOUNT_ID"
        )

    enabled_value = env.get("MANAGEMENT_WEB_ENABLED", "false").lower()
    if enabled_value not in {"true", "false"}:
        raise DeploymentError("MANAGEMENT_WEB_ENABLED must be exactly true or false")
    _resolve_origins(
        enabled=enabled_value == "true",
        environment=environment,
        region=region,
        backend_stack_name=backend_stack_name,
        parameters=parameters,
        env=env,
        runner=runner,
    )

    command = build_sam_command(
        config_environment=config_environment,
        parameters=parameters,
        region=region,
        extra_args=extra_args,
    )
    return runner(command, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config-env", choices=("default", "test", "prod"), default="default"
    )
    parser.add_argument("--no-confirm-changeset", action="store_true")
    parser.add_argument("--no-fail-on-empty-changeset", action="store_true")
    args = parser.parse_args(argv)
    extra_args = []
    if args.no_confirm_changeset:
        extra_args.append("--no-confirm-changeset")
    if args.no_fail_on_empty_changeset:
        extra_args.append("--no-fail-on-empty-changeset")

    try:
        return deploy(
            config_environment=args.config_env,
            extra_args=extra_args,
            env=dict(os.environ),
        )
    except DeploymentError as exc:
        print(f"Deployment preflight failed: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Unable to execute deployment command: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
