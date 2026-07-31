"""
Unit tests for admin user management handlers using a stubbed Cognito client.
"""

import importlib
import json
import os
import re
import sys
import uuid

from botocore.exceptions import ClientError


sys.path.insert(0, 'src/layers/common')
sys.path.insert(0, 'src/functions/users')


class FakeCognitoClient:
    def __init__(self):
        self.groups = {
            'ADMINISTRATOR',
            'SUPER_USER',
            'HOTEL_STAFF',
            'GUEST',
            'PS_1_USER',
            'PS_2_USER',
        }
        self.users = {}
        self.reject_attributes_to_get = False

    def list_groups(self, UserPoolId, Limit=None, NextToken=None):
        return {'Groups': [{'GroupName': g} for g in sorted(self.groups)]}

    def list_users(
        self,
        UserPoolId,
        Limit=None,
        PaginationToken=None,
        Filter=None,
        AttributesToGet=None,
    ):
        if self.reject_attributes_to_get and AttributesToGet:
            raise ClientError(
                {
                    'Error': {
                        'Code': 'InvalidParameterException',
                        'Message': 'Input fails to satisfy the constraints.',
                    }
                },
                'ListUsers',
            )

        users = list(self.users.values())
        if Filter:
            match = re.match(r'^sub = "(.+)"$', Filter)
            if match:
                sub = match.group(1)
                users = [u for u in users if _attr_value(u['Attributes'], 'sub') == sub]

        if AttributesToGet:
            filtered_users = []
            for user in users:
                attrs = [
                    attr for attr in user.get('Attributes', [])
                    if attr.get('Name') in set(AttributesToGet)
                ]
                filtered_users.append({
                    'Username': user.get('Username'),
                    'Attributes': attrs,
                    'Enabled': user.get('Enabled', True),
                    'UserStatus': user.get('UserStatus', 'CONFIRMED'),
                })
            users = filtered_users

        if Limit is not None:
            users = users[:Limit]
        return {'Users': users}

    def admin_list_groups_for_user(self, UserPoolId, Username, Limit=None, NextToken=None):
        user = self.users[Username]
        return {'Groups': [{'GroupName': g} for g in sorted(user['Groups'])]}

    def admin_create_user(self, UserPoolId, Username, UserAttributes):
        user_sub = str(uuid.uuid4())
        attrs = list(UserAttributes) + [{'Name': 'sub', 'Value': user_sub}]
        user = {
            'Username': Username,
            'Attributes': attrs,
            'Enabled': True,
            'UserStatus': 'FORCE_CHANGE_PASSWORD',
            'Groups': set(),
        }
        self.users[Username] = user
        return {'User': {'Username': Username, 'Attributes': attrs}}

    def admin_add_user_to_group(self, UserPoolId, Username, GroupName):
        self.users[Username]['Groups'].add(GroupName)

    def admin_remove_user_from_group(self, UserPoolId, Username, GroupName):
        self.users[Username]['Groups'].discard(GroupName)

    def admin_delete_user(self, UserPoolId, Username):
        self.users.pop(Username, None)

    def admin_get_user(self, UserPoolId, Username):
        user = self.users[Username]
        return {'Username': Username, 'UserAttributes': user['Attributes']}

    def admin_enable_user(self, UserPoolId, Username):
        self.users[Username]['Enabled'] = True

    def admin_disable_user(self, UserPoolId, Username):
        self.users[Username]['Enabled'] = False

    def admin_update_user_attributes(self, UserPoolId, Username, UserAttributes):
        user = self.users[Username]
        attrs = {a['Name']: a['Value'] for a in user['Attributes']}
        for attr in UserAttributes:
            attrs[attr['Name']] = attr['Value']
        user['Attributes'] = [{'Name': k, 'Value': v} for k, v in attrs.items()]


def _attr_value(attributes, name):
    for attr in attributes:
        if attr['Name'] == name:
            return attr['Value']
    return None


def _event(method='GET', groups=None, body=None, path_params=None, query_params=None):
    claims = {
        'sub': 'actor-001',
        'email': 'admin@example.com',
        'cognito:username': 'admin-user',
    }
    if groups is not None:
        claims['cognito:groups'] = ','.join(groups)

    return {
        'version': '2.0',
        'requestContext': {
            'http': {'method': method},
            'authorizer': {'jwt': {'claims': claims}},
        },
        'pathParameters': path_params or {},
        'queryStringParameters': query_params,
        'headers': {},
        'body': json.dumps(body) if body is not None else None,
    }


def _load(module_name):
    mod = importlib.import_module(module_name)
    importlib.reload(mod)
    return mod


def test_list_role_groups_admin_only_and_sorted(monkeypatch):
    fake = FakeCognitoClient()
    os.environ['MGMT_USER_POOL_ID'] = 'pool-1'

    module = _load('list_role_groups')
    monkeypatch.setattr(module, 'get_cognito_client', lambda: fake)

    denied = module.lambda_handler(_event(groups=['SUPER_USER']), None)
    denied_body = json.loads(denied['body'])
    assert denied['statusCode'] == 403
    assert denied_body['error']['code'] == 'FORBIDDEN'

    ok = module.lambda_handler(_event(groups=['ADMINISTRATOR']), None)
    ok_body = json.loads(ok['body'])
    assert ok['statusCode'] == 200
    assert ok_body['data']['groups'] == sorted(ok_body['data']['groups'])
    assert 'RIDER' not in ok_body['data']['groups']


def test_create_and_list_users_with_filters(monkeypatch):
    fake = FakeCognitoClient()
    os.environ['MGMT_USER_POOL_ID'] = 'pool-1'

    create_mod = _load('create_managed_user')
    list_mod = _load('list_managed_users')
    monkeypatch.setattr(create_mod, 'get_cognito_client', lambda: fake)
    monkeypatch.setattr(list_mod, 'get_cognito_client', lambda: fake)

    created = create_mod.lambda_handler(
        _event(
            method='POST',
            groups=['ADMINISTRATOR'],
            body={
                'email': 'new.user@example.com',
                'phoneNumber': '+919876543210',
                'name': 'New User',
                'roles': ['SUPER_USER', 'PS_2_USER'],
            },
        ),
        None,
    )
    created_body = json.loads(created['body'])
    assert created['statusCode'] == 201
    assert created_body['data']['cognitoUserId']
    assert created_body['data']['username'] == 'new.user@example.com'

    listed = list_mod.lambda_handler(
        _event(method='GET', groups=['ADMINISTRATOR'], query_params={'role': 'SUPER_USER'}),
        None,
    )
    listed_body = json.loads(listed['body'])
    assert listed['statusCode'] == 200
    assert len(listed_body['data']['users']) == 1
    assert listed_body['data']['users'][0]['email'] == 'new.user@example.com'
    assert 'SUPER_USER' in listed_body['data']['users'][0]['roles']


def test_enable_disable_update_user_flow(monkeypatch):
    fake = FakeCognitoClient()
    os.environ['MGMT_USER_POOL_ID'] = 'pool-1'

    bootstrap = fake.admin_create_user(
        UserPoolId='pool-1',
        Username='seed-user',
        UserAttributes=[
            {'Name': 'email', 'Value': 'flow.user@example.com'},
            {'Name': 'name', 'Value': 'Flow User'},
            {'Name': 'email_verified', 'Value': 'true'},
        ],
    )
    user_sub = _attr_value(bootstrap['User']['Attributes'], 'sub')
    fake.admin_add_user_to_group(UserPoolId='pool-1', Username='seed-user', GroupName='GUEST')

    disable_mod = _load('disable_managed_user')
    enable_mod = _load('enable_managed_user')
    update_mod = _load('update_managed_user')
    monkeypatch.setattr(disable_mod, 'get_cognito_client', lambda: fake)
    monkeypatch.setattr(enable_mod, 'get_cognito_client', lambda: fake)
    monkeypatch.setattr(update_mod, 'get_cognito_client', lambda: fake)

    disabled = disable_mod.lambda_handler(
        _event(
            method='POST',
            groups=['ADMINISTRATOR'],
            path_params={'cognitoUserId': user_sub},
        ),
        None,
    )
    disabled_body = json.loads(disabled['body'])
    assert disabled['statusCode'] == 200
    assert disabled_body['data']['enabled'] is False

    enabled = enable_mod.lambda_handler(
        _event(
            method='POST',
            groups=['ADMINISTRATOR'],
            path_params={'cognitoUserId': user_sub},
        ),
        None,
    )
    enabled_body = json.loads(enabled['body'])
    assert enabled['statusCode'] == 200
    assert enabled_body['data']['enabled'] is True

    updated = update_mod.lambda_handler(
        _event(
            method='PUT',
            groups=['ADMINISTRATOR'],
            path_params={'cognitoUserId': user_sub},
            body={
                'email': 'flow.updated@example.com',
                'phoneNumber': '',
                'name': '',
                'roles': ['ADMINISTRATOR'],
            },
        ),
        None,
    )
    updated_body = json.loads(updated['body'])
    assert updated['statusCode'] == 200
    assert updated_body['data']['cognitoUserId'] == user_sub

    groups_after = fake.admin_list_groups_for_user(UserPoolId='pool-1', Username='seed-user')['Groups']
    assert [g['GroupName'] for g in groups_after] == ['ADMINISTRATOR']


def test_delete_user_flow_without_prior_disable(monkeypatch):
    fake = FakeCognitoClient()
    os.environ['MGMT_USER_POOL_ID'] = 'pool-1'

    bootstrap = fake.admin_create_user(
        UserPoolId='pool-1',
        Username='delete-user',
        UserAttributes=[
            {'Name': 'email', 'Value': 'delete.user@example.com'},
            {'Name': 'name', 'Value': 'Delete User'},
            {'Name': 'email_verified', 'Value': 'true'},
        ],
    )
    user_sub = _attr_value(bootstrap['User']['Attributes'], 'sub')

    delete_mod = _load('delete_managed_user')
    monkeypatch.setattr(delete_mod, 'get_cognito_client', lambda: fake)

    deleted = delete_mod.lambda_handler(
        _event(
            method='DELETE',
            groups=['ADMINISTRATOR'],
            path_params={'cognitoUserId': user_sub},
        ),
        None,
    )
    deleted_body = json.loads(deleted['body'])

    assert deleted['statusCode'] == 200
    assert deleted_body['data']['cognitoUserId'] == user_sub
    assert deleted_body['data']['deleted'] is True
    assert 'delete-user' not in fake.users


def test_disable_user_accepts_cognito_sub_without_rfc_uuid_bits(monkeypatch):
    fake = FakeCognitoClient()
    os.environ['MGMT_USER_POOL_ID'] = 'pool-1'

    fake.users['seed-user'] = {
        'Username': 'seed-user',
        'Attributes': [
            {'Name': 'sub', 'Value': 'c1536d0a-e071-707f-571e-9526433c84ac'},
            {'Name': 'email', 'Value': 'flow.user@example.com'},
            {'Name': 'name', 'Value': 'Flow User'},
        ],
        'Enabled': True,
        'UserStatus': 'CONFIRMED',
        'Groups': {'GUEST'},
    }

    disable_mod = _load('disable_managed_user')
    monkeypatch.setattr(disable_mod, 'get_cognito_client', lambda: fake)

    disabled = disable_mod.lambda_handler(
        _event(
            method='POST',
            groups=['ADMINISTRATOR'],
            path_params={'cognitoUserId': 'c1536d0a-e071-707f-571e-9526433c84ac'},
        ),
        None,
    )
    disabled_body = json.loads(disabled['body'])

    assert disabled['statusCode'] == 200
    assert disabled_body['data'] == {
        'cognitoUserId': 'c1536d0a-e071-707f-571e-9526433c84ac',
        'enabled': False,
    }
    assert fake.users['seed-user']['Enabled'] is False


def test_list_cognito_users_returns_only_sub_and_name(monkeypatch):
    fake = FakeCognitoClient()
    os.environ['MGMT_USER_POOL_ID'] = 'pool-1'

    fake.users['user-one'] = {
        'Username': 'user-one',
        'Attributes': [
            {'Name': 'sub', 'Value': '11111111-1111-1111-1111-111111111111'},
            {'Name': 'name', 'Value': 'User One'},
            {'Name': 'email', 'Value': 'one@example.com'},
        ],
        'Enabled': True,
        'UserStatus': 'CONFIRMED',
        'Groups': {'GUEST'},
    }
    fake.users['user-two'] = {
        'Username': 'user-two',
        'Attributes': [
            {'Name': 'sub', 'Value': '22222222-2222-2222-2222-222222222222'},
            {'Name': 'name', 'Value': 'User Two'},
            {'Name': 'phone_number', 'Value': '+919999999999'},
        ],
        'Enabled': True,
        'UserStatus': 'CONFIRMED',
        'Groups': {'PS_1_USER'},
    }

    list_mod = _load('list_cognito_users')
    monkeypatch.setattr(list_mod, 'get_cognito_client', lambda: fake)

    response = list_mod.lambda_handler(
        _event(method='GET', groups=['PS_1_USER']),
        None,
    )
    body = json.loads(response['body'])

    assert response['statusCode'] == 200
    assert body['data']['count'] == 2
    assert body['data']['users'] == [
        {
            'sub': '11111111-1111-1111-1111-111111111111',
            'name': 'User One',
        },
        {
            'sub': '22222222-2222-2222-2222-222222222222',
            'name': 'User Two',
        },
    ]


def test_list_cognito_users_requires_valid_group(monkeypatch):
    fake = FakeCognitoClient()
    os.environ['MGMT_USER_POOL_ID'] = 'pool-1'

    list_mod = _load('list_cognito_users')
    monkeypatch.setattr(list_mod, 'get_cognito_client', lambda: fake)

    denied = list_mod.lambda_handler(_event(method='GET', groups=None), None)
    denied_body = json.loads(denied['body'])

    assert denied['statusCode'] == 403
    assert denied_body['error']['code'] == 'FORBIDDEN'


def test_list_cognito_users_fallback_when_projection_rejected(monkeypatch):
    fake = FakeCognitoClient()
    os.environ['MGMT_USER_POOL_ID'] = 'pool-1'
    fake.reject_attributes_to_get = True

    fake.users['user-one'] = {
        'Username': 'user-one',
        'Attributes': [
            {'Name': 'sub', 'Value': '11111111-1111-1111-1111-111111111111'},
            {'Name': 'name', 'Value': 'User One'},
            {'Name': 'email', 'Value': 'one@example.com'},
        ],
        'Enabled': True,
        'UserStatus': 'CONFIRMED',
        'Groups': {'ADMINISTRATOR'},
    }

    list_mod = _load('list_cognito_users')
    monkeypatch.setattr(list_mod, 'get_cognito_client', lambda: fake)

    response = list_mod.lambda_handler(_event(method='GET', groups=['ADMINISTRATOR']), None)
    body = json.loads(response['body'])

    assert response['statusCode'] == 200
    assert body['data']['count'] == 1
    assert body['data']['users'] == [
        {
            'sub': '11111111-1111-1111-1111-111111111111',
            'name': 'User One',
        }
    ]
