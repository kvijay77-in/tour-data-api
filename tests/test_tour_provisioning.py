"""
Unit tests for tour provisioning utilities

Tests the shared tour table provisioning logic used by both
the create_tour Lambda function (API method) and the
provision_tour CLI script (deployment method).
"""

import os
import json
import pytest
import boto3
from moto import mock_aws

# Set up path for imports
import sys
sys.path.insert(0, 'src/layers/common')

# Set AWS credentials before importing modules that initialize boto3 at module level
os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
os.environ['AWS_SECURITY_TOKEN'] = 'testing'
os.environ['AWS_SESSION_TOKEN'] = 'testing'
os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

from tour_provisioning import (
    TOUR_TABLE_DEFINITIONS,
    build_tour_table_tags,
    create_tour_table,
    wait_for_tour_tables,
    provision_tour_tables,
)
from models import TOUR_TABLE_TYPES


MOCK_STACK_NAME = 'test-stack'
MOCK_TOUR_ID = 'TestTour-2026'


@pytest.fixture
def aws_credentials():
    """Mock AWS credentials for moto"""
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'


@pytest.fixture
def env_setup(aws_credentials):
    """Set up environment variables"""
    os.environ['STACK_NAME'] = MOCK_STACK_NAME
    os.environ['ENVIRONMENT'] = 'test'
    os.environ['SUBSCRIPTION_ID'] = 'test-sub-001'
    yield
    os.environ.pop('STACK_NAME', None)
    os.environ.pop('ENVIRONMENT', None)
    os.environ.pop('SUBSCRIPTION_ID', None)


@pytest.fixture
def dynamodb_client_mock(env_setup):
    """Create a mocked DynamoDB client"""
    with mock_aws():
        client = boto3.client('dynamodb', region_name='us-east-1')
        yield client


class TestTourTableDefinitions:
    """Test tour table definitions are complete and correct"""

    def test_all_tour_table_types_have_definitions(self):
        """All table types in TOUR_TABLE_TYPES have definitions"""
        for table_type in TOUR_TABLE_TYPES:
            assert table_type in TOUR_TABLE_DEFINITIONS, \
                f"Missing definition for {table_type}"

    def test_definitions_have_required_fields(self):
        """Each definition has required DynamoDB fields"""
        for table_type, definition in TOUR_TABLE_DEFINITIONS.items():
            assert 'AttributeDefinitions' in definition, \
                f"{table_type} missing AttributeDefinitions"
            assert 'KeySchema' in definition, \
                f"{table_type} missing KeySchema"

    def test_checkin_table_has_composite_key(self):
        """CheckIn table has both PK and SK (composite key)"""
        checkin_def = TOUR_TABLE_DEFINITIONS['CheckIn']
        key_attrs = [k['AttributeName'] for k in checkin_def['KeySchema']]
        assert 'PK' in key_attrs
        assert 'SK' in key_attrs

    def test_other_tables_have_simple_key(self):
        """TourRider, Ride, User tables have PK-only keys"""
        for table_type in ['TourRider', 'Ride', 'User']:
            definition = TOUR_TABLE_DEFINITIONS[table_type]
            key_attrs = [k['AttributeName'] for k in definition['KeySchema']]
            assert key_attrs == ['PK'], \
                f"{table_type} should have PK-only key"


class TestBuildTourTableTags:
    """Test tag generation for tour-specific tables"""

    def test_tags_include_required_fields(self, env_setup):
        """Tags include project, application, managedBy, tourId, environment"""
        tags = build_tour_table_tags('TestTour-2026')
        tag_keys = [t['Key'] for t in tags]
        assert 'Project' in tag_keys
        assert 'Application' in tag_keys
        assert 'ManagedBy' in tag_keys
        assert 'tourId' in tag_keys
        assert 'Environment' in tag_keys

    def test_tags_include_subscription_id(self, env_setup):
        """Tags include SubscriptionId when set"""
        tags = build_tour_table_tags('TestTour-2026')
        tag_keys = [t['Key'] for t in tags]
        assert 'SubscriptionId' in tag_keys

    def test_tags_exclude_empty_subscription_id(self, env_setup):
        """Tags exclude SubscriptionId when empty"""
        os.environ['SUBSCRIPTION_ID'] = ''
        tags = build_tour_table_tags('TestTour-2026')
        tag_keys = [t['Key'] for t in tags]
        assert 'SubscriptionId' not in tag_keys

    def test_tour_id_in_tags(self, env_setup):
        """Tour ID is correctly set in tags"""
        tags = build_tour_table_tags('MyTour-2026')
        tour_tag = next(t for t in tags if t['Key'] == 'tourId')
        assert tour_tag['Value'] == 'MyTour-2026'


class TestProvisionTourTables:
    """Test end-to-end tour table provisioning"""

    def test_provision_creates_all_four_tables(self, dynamodb_client_mock):
        """Provisioning creates all 4 tour-specific tables"""
        created = provision_tour_tables(dynamodb_client_mock, MOCK_TOUR_ID)
        assert len(created) == 4

        # Verify table names
        expected_prefix = f"{MOCK_STACK_NAME}-"
        for table_name in created:
            assert table_name.startswith(expected_prefix)
            assert MOCK_TOUR_ID in table_name

    def test_provision_creates_correct_table_names(self, dynamodb_client_mock):
        """Provisioned tables follow naming convention"""
        created = provision_tour_tables(dynamodb_client_mock, MOCK_TOUR_ID)
        expected_names = [
            f"{MOCK_STACK_NAME}-TourRider-{MOCK_TOUR_ID}",
            f"{MOCK_STACK_NAME}-Ride-{MOCK_TOUR_ID}",
            f"{MOCK_STACK_NAME}-CheckIn-{MOCK_TOUR_ID}",
            f"{MOCK_STACK_NAME}-User-{MOCK_TOUR_ID}",
        ]
        assert sorted(created) == sorted(expected_names)

    def test_provisioned_tables_are_active(self, dynamodb_client_mock):
        """All provisioned tables are in ACTIVE status"""
        created = provision_tour_tables(dynamodb_client_mock, MOCK_TOUR_ID)

        for table_name in created:
            resp = dynamodb_client_mock.describe_table(TableName=table_name)
            assert resp['Table']['TableStatus'] == 'ACTIVE'

    def test_provisioned_tables_have_gsis(self, dynamodb_client_mock):
        """Provisioned tables have expected GSIs"""
        provision_tour_tables(dynamodb_client_mock, MOCK_TOUR_ID)

        # TourRider should have ProfileIdIndex
        resp = dynamodb_client_mock.describe_table(
            TableName=f"{MOCK_STACK_NAME}-TourRider-{MOCK_TOUR_ID}"
        )
        gsi_names = [g['IndexName'] for g in resp['Table'].get('GlobalSecondaryIndexes', [])]
        assert 'ProfileIdIndex' in gsi_names

        # Ride should have DateIndex and StatusIndex
        resp = dynamodb_client_mock.describe_table(
            TableName=f"{MOCK_STACK_NAME}-Ride-{MOCK_TOUR_ID}"
        )
        gsi_names = [g['IndexName'] for g in resp['Table'].get('GlobalSecondaryIndexes', [])]
        assert 'DateIndex' in gsi_names
        assert 'StatusIndex' in gsi_names

    def test_create_single_table(self, dynamodb_client_mock):
        """Creating a single tour table works correctly"""
        table_name = create_tour_table(dynamodb_client_mock, 'TourRider', MOCK_TOUR_ID)
        assert table_name == f"{MOCK_STACK_NAME}-TourRider-{MOCK_TOUR_ID}"

        resp = dynamodb_client_mock.describe_table(TableName=table_name)
        assert resp['Table']['TableStatus'] == 'ACTIVE'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
