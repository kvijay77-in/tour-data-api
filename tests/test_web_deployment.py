"""Focused tests for management-web origin discovery and SAM deployment."""

import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest
import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

import scripts.deploy_backend as deployment
from scripts.deploy_backend import (
    DeploymentError,
    _hosting_origin,
    build_sam_command,
    deploy,
    normalize_origin,
    parse_origin_list,
)


class CloudFormationLoader(yaml.SafeLoader):
    """Load CloudFormation short-form intrinsics into inspectable dictionaries."""


def _construct_intrinsic(loader, tag_suffix, node):
    if isinstance(node, ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, SequenceNode):
        value = loader.construct_sequence(node)
    elif isinstance(node, MappingNode):
        value = loader.construct_mapping(node)
    else:
        raise TypeError(f"Unsupported CloudFormation node: {type(node).__name__}")
    return {tag_suffix: value}


CloudFormationLoader.add_multi_constructor("!", _construct_intrinsic)


def _completed(command, payload=None, *, returncode=0, stderr=""):
    return CompletedProcess(
        command,
        returncode,
        json.dumps(payload) if payload is not None else "",
        stderr,
    )


def _environment(**overrides):
    values = {
        "AWS_REGION": "ap-south-1",
        "EXPECTED_BACKEND_REGION": "ap-south-1",
        "EXPECTED_AWS_ACCOUNT_ID": "123456789012",
        "MANAGEMENT_WEB_ENABLED": "false",
    }
    values.update(overrides)
    return values


def _stack_result(stack_name, stack):
    if stack is None:
        return _completed(
            ["aws"],
            returncode=255,
            stderr=f"An error occurred (ValidationError): Stack with id {stack_name} does not exist",
        )
    return _completed(["aws"], {"Stacks": [stack]})


def _stack(
    *,
    status="UPDATE_COMPLETE",
    environment="dev",
    project="tour-mgmt-app",
    outputs=None,
    parameters=None,
):
    return {
        "StackStatus": status,
        "Tags": [
            {"Key": "Environment", "Value": environment},
            {"Key": "Project", "Value": project},
        ],
        "Outputs": outputs or [],
        "Parameters": parameters or [],
    }


def _runner_for(
    *,
    backend_stack=None,
    hosting_stack=None,
    caller_account="123456789012",
):
    commands = []

    def runner(command, **kwargs):
        assert kwargs.get("check") is False
        commands.append(command)
        if command[:3] == ["aws", "sts", "get-caller-identity"]:
            return _completed(command, {"Account": caller_account})
        if command[:3] == ["aws", "cloudformation", "describe-stacks"]:
            stack_name = command[command.index("--stack-name") + 1]
            if stack_name == "dev":
                return _stack_result(stack_name, backend_stack)
            return _stack_result(stack_name, hosting_stack)
        if command[:2] == ["sam", "deploy"]:
            return _completed(command)
        raise AssertionError(f"Unexpected command: {command}")

    return runner, commands


def test_origin_validation_canonicalizes_deduplicates_and_allows_dev_localhost():
    assert normalize_origin("HTTPS://Example.COM:443", "dev") == "https://example.com"
    assert parse_origin_list(
        "http://localhost:5173,https://Example.com,https://example.com",
        "dev",
    ) == ["http://localhost:5173", "https://example.com"]


@pytest.mark.parametrize(
    "origin,environment",
    [
        ("*", "dev"),
        ("https://example.com/path", "dev"),
        ("https://example.com?", "dev"),
        ("https://user@example.com", "dev"),
        ("https://bad_host", "dev"),
        ("https://example.com:70000", "dev"),
        ("https://example.com:", "dev"),
        ("http://example.com", "dev"),
        ("http://localhost:5173", "prod"),
        ("https://localhost:8443", "prod"),
    ],
)
def test_origin_validation_rejects_invalid_or_insecure_origins(origin, environment):
    with pytest.raises(DeploymentError):
        normalize_origin(origin, environment)


def test_origin_lists_reject_empty_items():
    with pytest.raises(DeploymentError, match="empty items"):
        parse_origin_list("https://example.com,,https://other.example", "dev")


@pytest.mark.parametrize(
    "stack,expected_error",
    [
        (_stack(status="UPDATE_IN_PROGRESS"), "stable successful state"),
        (_stack(environment="prod"), "Environment tag"),
        (_stack(project="unrelated-project"), "Project tag"),
        (_stack(outputs=[]), "no SiteUrl output"),
        (
            _stack(
                outputs=[
                    {"OutputKey": "SiteUrl", "OutputValue": "http://web.example.com"}
                ]
            ),
            "must use HTTPS",
        ),
    ],
)
def test_hosting_stack_must_be_validated(stack, expected_error):
    runner, _ = _runner_for(hosting_stack=stack)
    with pytest.raises(DeploymentError, match=expected_error):
        _hosting_origin(
            stack_name="tour-mgmt-web-dev",
            stack_region="ap-south-1",
            expected_environment="dev",
            expected_project="tour-mgmt-app",
            runner=runner,
        )


def test_enabled_deploy_merges_discovered_and_existing_origins_and_all_overrides():
    backend_stack = _stack(
        parameters=[
            {
                "ParameterKey": "ManagementWebAllowedOrigins",
                "ParameterValue": "https://legacy.example.com,http://localhost:5173",
            },
        ]
    )
    hosting_stack = _stack(
        outputs=[
            {"OutputKey": "SiteUrl", "OutputValue": "https://CloudFront.Example.net/"}
        ]
    )
    runner, commands = _runner_for(
        backend_stack=backend_stack, hosting_stack=hosting_stack
    )

    assert (
        deploy(
            config_environment="default",
            extra_args=["--no-fail-on-empty-changeset"],
            env=_environment(
                MANAGEMENT_WEB_ENABLED="true",
                MANAGEMENT_WEB_STACK_NAME="tour-mgmt-web-dev",
                MANAGEMENT_WEB_STACK_REGION="us-east-2",
                MANAGEMENT_WEB_ADDITIONAL_ORIGINS="https://local.example.com",
            ),
            runner=runner,
        )
        == 0
    )

    sam_command = next(
        command for command in commands if command[:2] == ["sam", "deploy"]
    )
    overrides = sam_command[sam_command.index("--parameter-overrides") + 1 :]
    assert "Environment=dev" in overrides
    assert (
        "ManagementWebAllowedOrigins=http://localhost:5173,https://cloudfront.example.net,"
        "https://legacy.example.com,https://local.example.com"
    ) in overrides
    assert sam_command[sam_command.index("--region") + 1] == "ap-south-1"
    hosting_lookup = next(
        command
        for command in commands
        if command[:3] == ["aws", "cloudformation", "describe-stacks"]
        and command[command.index("--stack-name") + 1] == "tour-mgmt-web-dev"
    )
    assert hosting_lookup[hosting_lookup.index("--region") + 1] == "us-east-2"
    assert "--no-fail-on-empty-changeset" in sam_command


def test_disabled_deploy_does_not_require_hosting_stack():
    runner, commands = _runner_for()

    assert (
        deploy(
            config_environment="default",
            extra_args=[],
            env=_environment(),
            runner=runner,
        )
        == 0
    )

    assert not any(
        command[:3] == ["aws", "cloudformation", "describe-stacks"]
        and command[command.index("--stack-name") + 1] != "dev"
        for command in commands
    )
    sam_command = next(
        command for command in commands if command[:2] == ["sam", "deploy"]
    )
    assert "ManagementWebAllowedOrigins=" not in sam_command


def test_disabled_deploy_preserves_stored_origins_unless_explicitly_disabled():
    backend_stack = _stack(
        parameters=[
            {
                "ParameterKey": "ManagementWebAllowedOrigins",
                "ParameterValue": "https://site.example.com",
            },
        ]
    )
    runner, commands = _runner_for(backend_stack=backend_stack)

    deploy(
        config_environment="default",
        extra_args=[],
        env=_environment(),
        runner=runner,
    )
    sam_command = next(
        command for command in commands if command[:2] == ["sam", "deploy"]
    )
    assert "ManagementWebAllowedOrigins=https://site.example.com" in sam_command

    runner, commands = _runner_for(backend_stack=backend_stack)
    deploy(
        config_environment="default",
        extra_args=[],
        env=_environment(MANAGEMENT_WEB_DISABLE_APPROVED="true"),
        runner=runner,
    )
    sam_command = next(
        command for command in commands if command[:2] == ["sam", "deploy"]
    )
    assert "ManagementWebAllowedOrigins=" in sam_command


def test_disabled_deploy_rejects_configured_origins_without_backend_state(
    monkeypatch, tmp_path
):
    config_path = tmp_path / "samconfig.toml"
    config_path.write_text("""
[default.global.parameters]
stack_name = "dev"

[default.deploy.parameters]
parameter_overrides = "Environment=dev ManagementWebAllowedOrigins=https://site.example.com"
""")
    monkeypatch.setattr(deployment, "SAM_CONFIG", config_path)
    runner, _ = _runner_for()

    with pytest.raises(DeploymentError, match="lookup is disabled"):
        deployment.deploy(
            config_environment="default",
            extra_args=[],
            env=_environment(),
            runner=runner,
        )


def test_wrong_account_fails_before_stack_lookup_or_sam():
    runner, commands = _runner_for(caller_account="999999999999")

    with pytest.raises(DeploymentError, match="Active AWS account"):
        deploy(
            config_environment="default",
            extra_args=[],
            env=_environment(),
            runner=runner,
        )

    assert len(commands) == 1


def test_enabled_deploy_fails_closed_when_hosting_stack_is_missing():
    runner, _ = _runner_for(backend_stack=None, hosting_stack=None)

    with pytest.raises(DeploymentError, match="does not exist"):
        deploy(
            config_environment="default",
            extra_args=[],
            env=_environment(
                MANAGEMENT_WEB_ENABLED="true",
                MANAGEMENT_WEB_STACK_NAME="tour-mgmt-web-dev",
                MANAGEMENT_WEB_STACK_REGION="ap-south-1",
            ),
            runner=runner,
        )


def test_region_mismatch_fails_before_aws_or_sam():
    runner, commands = _runner_for()

    with pytest.raises(DeploymentError, match="does not match"):
        deploy(
            config_environment="default",
            extra_args=[],
            env=_environment(EXPECTED_BACKEND_REGION="us-east-1"),
            runner=runner,
        )

    assert not commands


def test_sam_command_passes_complete_parameter_overrides_together():
    command = build_sam_command(
        config_environment="prod",
        parameters={
            "Environment": "prod",
            "CognitoUserPoolArn": "arn:aws:cognito-idp:ap-south-1:123456789012:userpool/example",
            "CognitoAppClientId": "client-id",
            "ManagementWebAllowedOrigins": "https://web.example.com",
        },
        region="ap-south-1",
        extra_args=["--no-confirm-changeset"],
    )

    assert command.count("--parameter-overrides") == 1
    assert command[command.index("--parameter-overrides") + 1 :] == [
        "Environment=prod",
        "CognitoUserPoolArn=arn:aws:cognito-idp:ap-south-1:123456789012:userpool/example",
        "CognitoAppClientId=client-id",
        "ManagementWebAllowedOrigins=https://web.example.com",
        "--no-confirm-changeset",
    ]


def test_deploy_preserves_all_existing_sam_config_overrides(monkeypatch, tmp_path):
    config_path = tmp_path / "samconfig.toml"
    config_path.write_text("""
[default.global.parameters]
stack_name = "dev"

[default.deploy.parameters]
parameter_overrides = "Environment=dev CognitoUserPoolArn=arn:aws:cognito-idp:ap-south-1:123456789012:userpool/example CognitoAppClientId=client-id"
""")
    monkeypatch.setattr(deployment, "SAM_CONFIG", config_path)
    runner, commands = _runner_for()

    assert (
        deployment.deploy(
            config_environment="default",
            extra_args=[],
            env=_environment(),
            runner=runner,
        )
        == 0
    )

    sam_command = next(
        command for command in commands if command[:2] == ["sam", "deploy"]
    )
    overrides = sam_command[sam_command.index("--parameter-overrides") + 1 :]
    assert "Environment=dev" in overrides
    assert (
        "CognitoUserPoolArn=arn:aws:cognito-idp:ap-south-1:123456789012:userpool/example"
        in overrides
    )
    assert "CognitoAppClientId=client-id" in overrides


def test_template_web_cors_is_conditional_and_keeps_rider_policy_independent():
    template_path = Path(__file__).resolve().parents[1] / "template.yaml"
    template = yaml.load(template_path.read_text(), Loader=CloudFormationLoader)
    parameters = template["Parameters"]
    conditions = template["Conditions"]
    resources = template["Resources"]

    assert parameters["ManagementWebAllowedOrigins"]["Default"] == ""
    assert conditions["HasManagementWebOrigins"]["Not"] == [
        {"Equals": [{"Ref": "ManagementWebAllowedOrigins"}, ""]}
    ]

    management_cors = resources["TourDataApi"]["Properties"]["CorsConfiguration"]
    assert management_cors["AllowOrigins"]["If"][0] == "HasManagementWebOrigins"
    assert management_cors["AllowOrigins"]["If"][1]["Split"] == [
        ",",
        {"Ref": "ManagementWebAllowedOrigins"},
    ]
    assert management_cors["AllowOrigins"]["If"][2] == ["*"]
    assert management_cors["AllowHeaders"]["If"][1] == [
        "Authorization",
        "Content-Type",
        "If-None-Match",
    ]
    assert management_cors["ExposeHeaders"]["If"][1] == ["ETag"]
    assert management_cors["AllowMethods"] == [
        "GET",
        "POST",
        "PUT",
        "DELETE",
        "OPTIONS",
    ]
    assert management_cors["MaxAge"] == 600

    rider_cors = resources["RiderApi"]["Properties"]["CorsConfiguration"]
    assert rider_cors["AllowOrigins"] == ["*"]
    assert rider_cors["AllowHeaders"] == ["*"]
    assert rider_cors["AllowMethods"] == ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    assert rider_cors["MaxAge"] == 600
    assert (
        resources["TourDataApi"]["Properties"]["Auth"]["DefaultAuthorizer"]
        == "CognitoAuthorizer"
    )
    assert (
        resources["RiderApi"]["Properties"]["Auth"]["DefaultAuthorizer"]
        == "RiderCognitoAuthorizer"
    )

    artifacts = resources["ArtifactsBucket"]["Properties"]
    artifact_cors = artifacts["CorsConfiguration"]["If"]
    assert artifact_cors[0] == "HasManagementWebOrigins"
    rule = artifact_cors[1]["CorsRules"][0]
    assert rule["AllowedMethods"] == ["PUT"]
    assert "OPTIONS" not in rule["AllowedMethods"]
    assert rule["AllowedHeaders"] == ["Content-Type"]
    assert rule["MaxAge"] == 600
    assert "CorsConfiguration" not in resources["PhotosBucket"]["Properties"]
    assert artifacts["PublicAccessBlockConfiguration"]["BlockPublicAcls"] is True
    assert (
        artifacts["BucketEncryption"]["ServerSideEncryptionConfiguration"][0][
            "ServerSideEncryptionByDefault"
        ]["SSEAlgorithm"]
        == "AES256"
    )
