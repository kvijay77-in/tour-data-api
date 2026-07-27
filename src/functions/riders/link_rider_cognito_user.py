"""
Link/unlink rider Cognito username to rider profile ID.

Route: GET/POST/DELETE /v1/riders/link/{cognitoUserName}
Table: RiderCognitoUser (partition key: cognitoUserName)
"""

import sys
import uuid

sys.path.insert(0, '/opt/python')

from logger import get_logger, log_event
from response import (
    success_response,
    bad_request_response,
    conflict_response,
    not_found_response,
    internal_error_response,
)
from dynamodb_utils import get_item, put_item, get_table

logger = get_logger(__name__)


TABLE_ENV = 'RIDER_COGNITO_USER_TABLE'


def _get_method(event):
    return event.get('requestContext', {}).get('http', {}).get('method', '').upper()


def _get_cognito_user_name(event):
    value = event.get('pathParameters', {}).get('cognitoUserName', '')
    return value.strip()


def _create_link(cognito_user_name):
    existing = get_item(
        table_name_env=TABLE_ENV,
        key={'cognitoUserName': cognito_user_name}
    )

    if existing:
        return conflict_response(
            f"cognitoUserName '{cognito_user_name}' is already linked",
            error_code='COGNITO_USER_ALREADY_LINKED'
        )

    item = {
        'cognitoUserName': cognito_user_name,
        'profileId': str(uuid.uuid4())
    }

    put_item(table_name_env=TABLE_ENV, item=item)
    return success_response(item, status_code=201)


def _delete_link(cognito_user_name):
    table = get_table(TABLE_ENV)
    response = table.delete_item(
        Key={'cognitoUserName': cognito_user_name},
        ReturnValues='ALL_OLD'
    )

    if 'Attributes' not in response:
        return not_found_response('RiderCognitoUser', cognito_user_name)

    return success_response({
        'cognitoUserName': cognito_user_name,
        'deleted': True
    })


def _get_link(cognito_user_name):
    link = get_item(
        table_name_env=TABLE_ENV,
        key={'cognitoUserName': cognito_user_name}
    )

    if not link:
        return not_found_response('RiderCognitoUser', cognito_user_name)

    return success_response({
        'profileId': link['profileId']
    })


def lambda_handler(event, context):
    """Create, read, or delete a RiderCognitoUser mapping by cognitoUserName."""
    try:
        log_event(logger, event)

        method = _get_method(event)
        cognito_user_name = _get_cognito_user_name(event)

        if not cognito_user_name:
            return bad_request_response('cognitoUserName is required in path')

        if method == 'POST':
            return _create_link(cognito_user_name)

        if method == 'GET':
            return _get_link(cognito_user_name)

        if method == 'DELETE':
            return _delete_link(cognito_user_name)

        return bad_request_response(f'Unsupported HTTP method: {method}')

    except Exception as e:
        logger.error(f"Error linking/unlinking rider cognito user: {str(e)}", exc_info=True)
        return internal_error_response('Failed to process rider link request')
