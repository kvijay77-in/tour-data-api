"""Template tests for management-web CORS configuration."""

from pathlib import Path

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode


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
