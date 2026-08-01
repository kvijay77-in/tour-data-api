"""
Pytest configuration and shared fixtures

This file contains pytest fixtures that are shared across all test files.
Fixtures defined here are automatically available in all test modules.
"""

import os
import pytest
import boto3
from moto import mock_aws


@pytest.fixture(scope='function')
def aws_credentials():
    """
    Mocked AWS Credentials for moto
    
    Sets environment variables for AWS credentials that moto will use.
    These are not real credentials - moto intercepts boto3 calls.
    """
    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'


@pytest.fixture(scope='function')
def dynamodb_client(aws_credentials):
    """
    Creates a mocked DynamoDB client
    
    Returns:
        boto3 DynamoDB client with mocked backend
    """
    with mock_aws():
        yield boto3.client('dynamodb', region_name='us-east-1')


@pytest.fixture(scope='function')
def dynamodb_resource(aws_credentials):
    """
    Creates a mocked DynamoDB resource
    
    Returns:
        boto3 DynamoDB resource with mocked backend
    """
    with mock_aws():
        yield boto3.resource('dynamodb', region_name='us-east-1')


@pytest.fixture(scope='function')
def lambda_environment():
    """
    Sets up Lambda environment variables for testing
    
    Hybrid table strategy:
    - Shared tables: resolved via env var (TOUR_MASTER_TABLE, RIDER_PROFILE_TABLE)
    - Tour-specific tables: resolved dynamically via STACK_NAME + tourId
    """
    env_vars = {
        'TOUR_MASTER_TABLE': 'test-tour-master-table',
        'RIDER_PROFILE_TABLE': 'test-rider-table',
        'APP_CONFIG_TABLE': 'test-app-config-table',
        'STACK_NAME': 'test-stack',
        'ENVIRONMENT': 'test',
        'SUBSCRIPTION_ID': 'test-sub-001',
        'PHOTOS_BUCKET': 'test-photos-bucket',
        'LOG_LEVEL': 'INFO'
    }
    
    # Set environment variables
    for key, value in env_vars.items():
        os.environ[key] = value
    
    yield env_vars
    
    # Cleanup
    for key in env_vars:
        os.environ.pop(key, None)
