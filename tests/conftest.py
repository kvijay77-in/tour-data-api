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
    
    These environment variables are used by Lambda functions to
    locate AWS resources during testing.
    """
    env_vars = {
        'TOUR_TABLE': 'test-tour-table',
        'RIDER_PROFILE_TABLE': 'test-rider-table',
        'TOUR_RIDER_TABLE': 'test-tour-rider-table',
        'RIDE_TABLE': 'test-ride-table',
        'CHECKIN_TABLE': 'test-checkin-table',
        'USER_TABLE': 'test-user-table',
        'PHOTOS_BUCKET': 'test-photos-bucket',
        'LOG_LEVEL': 'INFO'
    }
    
    # Set environment variables
    for key, value in env_vars.items():
        os.environ[key] = value
    
    yield env_vars
    
    # Cleanup (optional - tests run in isolation)
    for key in env_vars:
        os.environ.pop(key, None)
