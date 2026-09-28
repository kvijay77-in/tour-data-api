"""Rider profile schema and value validation backed by AppConfig."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from dynamodb_utils import query_items
from rbac import get_user_groups
from validation import ValidationError, validate_email, validate_iso_date, normalize_personal_code


PROFILE_SECTION_TYPE = 'RIDER_PROFILE_SECTION'
PROFILE_ATTRIBUTE_TYPE = 'RIDER_PROFILE_ATTRIBUTE'
LOV_TYPE = 'LOV'

CACHE_TTL_SECONDS = 60

_ALLOWED_TYPES = {
    'TEXT', 'TEXTAREA', 'EMAIL', 'PHONE', 'URL', 'NUMBER', 'DATE',
    'BOOLEAN', 'SELECT', 'MULTI_SELECT', 'FILE', 'IMAGE', 'GROUP'
}
_HANDLER_REGISTRY = {'PERSONAL_CODE', 'COGNITO_EMAIL', 'PROFILE_PHOTO'}

_CACHE: Dict[str, Any] = {'expires_at': 0.0, 'data': None}

_DEFAULT_DEFINITIONS: Optional["Definitions"] = None


@dataclass
class ProfileSchemaError(Exception):
    message: str
    code: str
    status_code: int = 422


@dataclass
class Definitions:
    sections: Dict[str, Dict[str, Any]]
    attributes: Dict[str, Dict[str, Any]]
    lovs: Dict[str, Dict[str, Any]]
    version: str


_DEFAULT_DEFINITIONS = Definitions(
    sections={
        'personal': {'configId': 'personal', 'config': {'label': 'Personal', 'order': 1}},
        'contact': {'configId': 'contact', 'config': {'label': 'Contact', 'order': 2}},
        'address': {'configId': 'address', 'config': {'label': 'Address', 'order': 3}},
        'emergency': {'configId': 'emergency', 'config': {'label': 'Emergency', 'order': 4}},
        'preferences': {'configId': 'preferences', 'config': {'label': 'Preferences', 'order': 5}},
    },
    attributes={
        'name': {'configId': 'name', 'config': {'type': 'TEXT', 'storage': {'scope': 'CORE', 'path': 'name'}, 'required': True, 'sectionId': 'personal', 'label': 'Name', 'order': 1}},
        'email': {'configId': 'email', 'config': {'type': 'EMAIL', 'storage': {'scope': 'CORE', 'path': 'email'}, 'required': True, 'sectionId': 'contact', 'label': 'Email', 'order': 1}},
        'phone': {'configId': 'phone', 'config': {'type': 'PHONE', 'storage': {'scope': 'CORE', 'path': 'phone'}, 'required': True, 'sectionId': 'contact', 'label': 'Phone', 'order': 2}},
        'emergencyContact': {'configId': 'emergencyContact', 'config': {'type': 'GROUP', 'storage': {'scope': 'CORE', 'path': 'emergencyContact'}, 'required': True, 'sectionId': 'emergency', 'label': 'Emergency Contact', 'order': 1, 'fields': [{'key': 'name', 'type': 'TEXT', 'required': True}, {'key': 'phone', 'type': 'PHONE', 'required': True}, {'key': 'relation', 'type': 'TEXT', 'required': True}]}},
        'dateOfBirth': {'configId': 'dateOfBirth', 'config': {'type': 'DATE', 'storage': {'scope': 'CORE', 'path': 'dateOfBirth'}, 'required': True, 'sectionId': 'personal', 'label': 'Date of Birth', 'order': 3}},
        'gender': {'configId': 'gender', 'config': {'type': 'SELECT', 'storage': {'scope': 'CORE', 'path': 'gender'}, 'required': True, 'sectionId': 'personal', 'label': 'Gender', 'order': 4, 'lovId': 'GENDER'}},
        'address': {'configId': 'address', 'config': {'type': 'GROUP', 'storage': {'scope': 'CORE', 'path': 'address'}, 'required': True, 'sectionId': 'address', 'label': 'Address', 'order': 1, 'fields': [{'key': 'line1', 'type': 'TEXT', 'required': True}, {'key': 'line2', 'type': 'TEXT', 'required': False}, {'key': 'city', 'type': 'TEXT', 'required': True}, {'key': 'state', 'type': 'TEXT', 'required': False}, {'key': 'country', 'type': 'TEXT', 'required': True}, {'key': 'postalCode', 'type': 'TEXT', 'required': True}]}},
        'dietaryPreference': {'configId': 'dietaryPreference', 'config': {'type': 'TEXT', 'storage': {'scope': 'ATTRIBUTES'}, 'required': False, 'sectionId': 'preferences', 'label': 'Dietary Preference', 'order': 1}},
        'photo': {'configId': 'photo', 'config': {'type': 'IMAGE', 'storage': {'scope': 'CORE', 'path': 'photoS3Key'}, 'required': False, 'sectionId': 'personal', 'label': 'Photo', 'order': 2}},
        'personalCode': {'configId': 'personalCode', 'config': {'type': 'TEXT', 'storage': {'scope': 'CORE', 'path': 'personalCode'}, 'required': False, 'sectionId': 'preferences', 'label': 'Personal Code', 'order': 2, 'handler': 'PERSONAL_CODE'}},
    },
    lovs={
        'GENDER': {'configId': 'GENDER', 'config': {'label': 'Gender', 'items': [
            {'value': 'Male', 'label': 'Male', 'enabled': True},
            {'value': 'Female', 'label': 'Female', 'enabled': True},
            {'value': 'Other', 'label': 'Other', 'enabled': True},
            {'value': 'Prefer not to say', 'label': 'Prefer not to say', 'enabled': True},
        ]}}
    },
    version='legacy-default',
)


def _now() -> float:
    return time.time()


def clear_schema_cache() -> None:
    _CACHE['expires_at'] = 0.0
    _CACHE['data'] = None


def _load_enabled(config_type: str) -> List[Dict[str, Any]]:
    return query_items(
        table_name_env='APP_CONFIG_TABLE',
        key_condition_expression='configType = :ct',
        expression_values={':ct': config_type, ':enabled': True},
        filter_expression='enabled = :enabled',
    )


def get_definitions() -> Definitions:
    if _CACHE['data'] and _CACHE['expires_at'] > _now():
        return _CACHE['data']

    load_failed = False
    try:
        sections = {item['configId']: item for item in _load_enabled(PROFILE_SECTION_TYPE)}
        attributes = {item['configId']: item for item in _load_enabled(PROFILE_ATTRIBUTE_TYPE)}
        lovs = {item['configId']: item for item in _load_enabled(LOV_TYPE)}
    except Exception:
        load_failed = True
        sections = {}
        attributes = {}
        lovs = {}

    if load_failed:
        data = copy.deepcopy(_DEFAULT_DEFINITIONS)
        _CACHE['data'] = data
        _CACHE['expires_at'] = _now() + CACHE_TTL_SECONDS
        return data

    version_basis: List[str] = []
    for group in (sections, attributes, lovs):
        for key, item in sorted(group.items()):
            version_basis.append(f"{key}:{item.get('updatedAt', '')}:{item.get('version', 0)}")
    digest = hashlib.sha256('|'.join(version_basis).encode('utf-8')).hexdigest() if version_basis else 'none'

    data = Definitions(sections=sections, attributes=attributes, lovs=lovs, version=digest)
    _CACHE['data'] = data
    _CACHE['expires_at'] = _now() + CACHE_TTL_SECONDS
    return data


def get_definitions_version() -> str:
    return get_definitions().version


def ensure_definitions_version(client_version: Optional[str]) -> None:
    current = get_definitions_version()
    if client_version and client_version != current:
        raise ProfileSchemaError(
            message='Rider profile definitions changed. Refresh and retry.',
            code='PROFILE_DEFINITIONS_CHANGED',
            status_code=409,
        )


def get_user_role_flags(event: Dict[str, Any]) -> Dict[str, bool]:
    groups = set(get_user_groups(event))
    return {
        'is_admin': 'ADMINISTRATOR' in groups,
        'is_super_user': 'SUPER_USER' in groups,
        'is_staff': bool(groups - {'RIDER'}) and ('RIDER' not in groups or len(groups) > 1),
    }


def _storage_for(attr: Dict[str, Any]) -> Dict[str, Any]:
    return (attr.get('config') or {}).get('storage') or {'scope': 'ATTRIBUTES'}


def _attr_type(attr: Dict[str, Any]) -> str:
    return ((attr.get('config') or {}).get('type') or '').upper()


def _attr_flags(attr: Dict[str, Any]) -> Dict[str, Any]:
    cfg = attr.get('config') or {}
    return {
        'required': bool(cfg.get('required')),
        'adminOnly': bool(cfg.get('adminOnly')),
        'sensitive': bool(cfg.get('sensitive')),
        'visibleToAllMgmtUsers': bool(cfg.get('visibleToAllMgmtUsers', True)),
    }


def get_attribute_flags(attribute_key: str) -> Dict[str, Any]:
    attr_def = get_attribute_definition(attribute_key)
    if not attr_def:
        return {'required': False, 'adminOnly': False, 'sensitive': False, 'visibleToAllMgmtUsers': True}
    return _attr_flags(attr_def)


def read_attribute_value(profile: Dict[str, Any], attribute_key: str, attr_def: Optional[Dict[str, Any]] = None) -> Any:
    defs = get_definitions()
    attr = attr_def or defs.attributes.get(attribute_key)
    if not attr:
        return None

    storage = _storage_for(attr)
    if storage.get('scope') == 'CORE':
        return profile.get(storage.get('path'))
    return (profile.get('attributes') or {}).get(attribute_key)


def write_attribute_value(profile: Dict[str, Any], attribute_key: str, attr_def: Dict[str, Any], value: Any) -> None:
    storage = _storage_for(attr_def)
    if storage.get('scope') == 'CORE':
        profile[storage.get('path')] = value
        return

    if not isinstance(profile.get('attributes'), dict):
        profile['attributes'] = {}
    profile['attributes'][attribute_key] = value


def clear_attribute_value(profile: Dict[str, Any], attribute_key: str, attr_def: Dict[str, Any]) -> None:
    storage = _storage_for(attr_def)
    if storage.get('scope') == 'CORE':
        profile.pop(storage.get('path'), None)
        return

    attributes = profile.get('attributes')
    if isinstance(attributes, dict):
        attributes.pop(attribute_key, None)


def _lov_items(lov: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    config = lov.get('config') or {}
    items = config.get('items') or []
    return {str(item.get('value')): item for item in items if item.get('value') is not None}


def _match_lov_item(items: Dict[str, Dict[str, Any]], value: Any) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    value_str = str(value).strip()
    for item_value, item in items.items():
        if str(item_value).strip().lower() == value_str.lower():
            return str(item_value), item
    for item_value, item in items.items():
        label = item.get('label')
        if isinstance(label, str) and label.strip().lower() == value_str.lower():
            return str(item_value), item
    return None, None


def _parse_relative_date(token: str) -> Optional[date]:
    if not isinstance(token, str):
        return None
    token = token.strip()
    match = re.fullmatch(r'([+-]?)(\d+)([ymd])', token)
    if not match:
        return None
    sign = -1 if match.group(1) == '-' else 1
    amount = int(match.group(2)) * sign
    unit = match.group(3)
    today = date.today()
    if unit == 'd':
        return today + timedelta(days=amount)
    if unit == 'm':
        # approximated to 30 days per month
        return today + timedelta(days=amount * 30)
    if unit == 'y':
        try:
            return today.replace(year=today.year + amount)
        except ValueError:
            return today.replace(month=2, day=28, year=today.year + amount)
    return None


def _to_date(value: str, field_name: str) -> date:
    validate_iso_date(value, field_name=field_name)
    return datetime.strptime(value, '%Y-%m-%d').date()


def _validate_date_bounds(value: str, validation: Dict[str, Any], field_name: str) -> None:
    actual = _to_date(value, field_name)
    for key in ('minDate', 'maxDate'):
        bound_raw = validation.get(key)
        if not bound_raw:
            continue
        if isinstance(bound_raw, str):
            bound_date = _parse_relative_date(bound_raw) or _to_date(bound_raw, f'{field_name}.{key}')
        else:
            raise ValidationError(f'{field_name}.{key} must be a string')
        if key == 'minDate' and actual < bound_date:
            raise ValidationError(f'{field_name} must be on/after {bound_date.isoformat()}')
        if key == 'maxDate' and actual > bound_date:
            raise ValidationError(f'{field_name} must be on/before {bound_date.isoformat()}')


def _validate_lov_value(key: str, value: str, attr_cfg: Dict[str, Any], definitions: Definitions, parent_value: Optional[str] = None) -> str:
    lov_id = attr_cfg.get('lovId')
    if not lov_id:
        raise ValidationError(f'{key} requires lovId')
    lov = definitions.lovs.get(lov_id)
    if not lov:
        raise ValidationError(f'LOV {lov_id} not found for {key}')

    items = _lov_items(lov)
    normalized_value, item = _match_lov_item(items, value)
    if not item or normalized_value is None:
        raise ValidationError(f"{key} has unsupported value '{value}'")
    if not item.get('enabled', True):
        raise ValidationError(f"{key} has disabled value '{normalized_value}'")

    depends_on = attr_cfg.get('dependsOn')
    if depends_on and parent_value is not None:
        parent_item = item.get('parent')
        normalized_parent = parent_value
        parent_lov_id = (lov.get('config') or {}).get('parentLovId')
        if parent_lov_id:
            parent_lov = definitions.lovs.get(parent_lov_id)
            if parent_lov:
                parent_normalized, _ = _match_lov_item(_lov_items(parent_lov), parent_value)
                if parent_normalized is not None:
                    normalized_parent = parent_normalized
        if parent_item is not None and str(parent_item).strip().lower() != str(normalized_parent).strip().lower():
            raise ValidationError(f"{key} value '{value}' is not valid for selected parent")
    return normalized_value


def _validate_file_like(value: Any, key: str, attr_cfg: Dict[str, Any], attr_type: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f'{key} must be an object')
    required = {'s3Key', 'fileName', 'contentType', 'sizeBytes', 'uploadedAt'}
    missing = sorted(required - set(value.keys()))
    if missing:
        raise ValidationError(f"{key} is missing file metadata fields: {', '.join(missing)}")

    allowed_mime_types = attr_cfg.get('validation', {}).get('allowedMimeTypes') or []
    if allowed_mime_types and value.get('contentType') not in allowed_mime_types:
        raise ValidationError(f"{key} contentType '{value.get('contentType')}' not allowed")

    max_size = attr_cfg.get('validation', {}).get('maxFileSizeBytes')
    if max_size is not None:
        try:
            size = int(value.get('sizeBytes'))
        except Exception as exc:
            raise ValidationError(f'{key}.sizeBytes must be an integer') from exc
        if size > int(max_size):
            raise ValidationError(f'{key}.sizeBytes exceeds maxFileSizeBytes')


def _validate_group(value: Any, key: str, attr_cfg: Dict[str, Any], definitions: Definitions, profile: Dict[str, Any]) -> None:
    fields = attr_cfg.get('fields') or []
    repeatable = bool(attr_cfg.get('repeatable'))
    max_items = attr_cfg.get('maxItems')

    def _validate_group_item(item: Any, idx: Optional[int] = None) -> None:
        if not isinstance(item, dict):
            raise ValidationError(f'{key} must be an object')
        for field in fields:
            field_key = field.get('key')
            if not field_key:
                continue
            field_type = (field.get('type') or 'TEXT').upper()
            field_required = bool(field.get('required'))
            field_value = item.get(field_key)
            if field_value is None:
                if field_required:
                    raise ValidationError(f"{key}.{field_key} is required")
                continue
            pseudo_attr = {'config': {'type': field_type, 'validation': field.get('validation', {}), 'lovId': field.get('lovId'), 'dependsOn': field.get('dependsOn')}}
            _validate_scalar_value(field_value, f"{key}.{field_key}", pseudo_attr, definitions, profile, group_context=item)

    if repeatable:
        if not isinstance(value, list):
            raise ValidationError(f'{key} must be an array')
        if max_items is not None and len(value) > int(max_items):
            raise ValidationError(f'{key} exceeds maxItems')
        for idx, entry in enumerate(value):
            _validate_group_item(entry, idx)
        return

    _validate_group_item(value)


def _validate_scalar_value(
    value: Any,
    key: str,
    attr_def: Dict[str, Any],
    definitions: Definitions,
    profile: Dict[str, Any],
    group_context: Optional[Dict[str, Any]] = None,
) -> Any:
    cfg = attr_def.get('config') or {}
    attr_type = _attr_type(attr_def)
    validation = cfg.get('validation') or {}

    if attr_type not in _ALLOWED_TYPES:
        raise ValidationError(f'{key} has unsupported type {attr_type}')

    if attr_type in {'TEXT', 'TEXTAREA'}:
        if not isinstance(value, str):
            raise ValidationError(f'{key} must be a string')
        if validation.get('minLength') is not None and len(value) < int(validation['minLength']):
            raise ValidationError(f'{key} length below minLength')
        if validation.get('maxLength') is not None and len(value) > int(validation['maxLength']):
            raise ValidationError(f'{key} length exceeds maxLength')
        pattern = validation.get('pattern')
        if pattern and not re.fullmatch(pattern, value):
            raise ValidationError(f'{key} does not match required pattern')
        return value

    if attr_type == 'EMAIL':
        if not isinstance(value, str):
            raise ValidationError(f'{key} must be a string')
        validate_email(value)
        return value

    if attr_type == 'PHONE':
        if not isinstance(value, str):
            raise ValidationError(f'{key} must be a string')
        if not re.fullmatch(r'^\+[1-9]\d{5,14}$', value):
            raise ValidationError(f'{key} must be E.164 format (+ and 6-15 digits)')
        return value

    if attr_type == 'URL':
        if not isinstance(value, str):
            raise ValidationError(f'{key} must be a string')
        parsed = urlparse(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            raise ValidationError(f'{key} must be a valid URL')
        return value

    if attr_type == 'NUMBER':
        if not isinstance(value, (int, float, Decimal)) or isinstance(value, bool):
            raise ValidationError(f'{key} must be a number')
        number = float(value)
        if validation.get('min') is not None and number < float(validation['min']):
            raise ValidationError(f'{key} is below min')
        if validation.get('max') is not None and number > float(validation['max']):
            raise ValidationError(f'{key} is above max')
        decimals = validation.get('decimals')
        if decimals is not None:
            scale = 10 ** int(decimals)
            if int(round(number * scale)) != round(number * scale):
                raise ValidationError(f'{key} has too many decimal places')
        return value

    if attr_type == 'DATE':
        if not isinstance(value, str):
            raise ValidationError(f'{key} must be YYYY-MM-DD')
        _validate_date_bounds(value, validation, key)
        return value

    if attr_type == 'BOOLEAN':
        if not isinstance(value, bool):
            raise ValidationError(f'{key} must be boolean')
        return value

    if attr_type == 'SELECT':
        if not isinstance(value, str):
            raise ValidationError(f'{key} must be a string')
        depends_on = cfg.get('dependsOn')
        parent_value = None
        if depends_on:
            if group_context and depends_on in group_context:
                parent_value = group_context.get(depends_on)
            else:
                parent_value = read_attribute_value(profile, depends_on)
        try:
            return _validate_lov_value(key, value, cfg, definitions, parent_value=parent_value)
        except ValidationError:
            fallback_enabled = bool(cfg.get('fallbackToText'))
            if not (fallback_enabled and depends_on):
                raise
            if not isinstance(value, str):
                raise
        return value

    if attr_type == 'MULTI_SELECT':
        if not isinstance(value, list):
            raise ValidationError(f'{key} must be an array')
        min_items = validation.get('minItems')
        max_items = validation.get('maxItems')
        if min_items is not None and len(value) < int(min_items):
            raise ValidationError(f'{key} has fewer than minItems')
        if max_items is not None and len(value) > int(max_items):
            raise ValidationError(f'{key} exceeds maxItems')
        for idx, item in enumerate(value):
            if not isinstance(item, str):
                raise ValidationError(f'{key}[{idx}] must be a string')
            _validate_lov_value(key, item, cfg, definitions)
        return value

    if attr_type in {'FILE', 'IMAGE'}:
        if (cfg.get('handler') or '').upper() == 'PROFILE_PHOTO':
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(f'{key} must be a non-empty S3 key string')
            return value.strip()
        _validate_file_like(value, key, attr_def, attr_type)
        return value

    if attr_type == 'GROUP':
        _validate_group(value, key, cfg, definitions, profile)
        return value

    return value


def _is_attribute_visible(attr_key: str, attr_def: Dict[str, Any], profile: Dict[str, Any]) -> bool:
    cfg = attr_def.get('config') or {}
    visible_when = cfg.get('visibleWhen')
    if not visible_when:
        return True

    target_key = visible_when.get('attribute')
    op = (visible_when.get('op') or '').upper()
    expected = visible_when.get('value')
    actual = read_attribute_value(profile, target_key)

    if op == 'EQ':
        return actual == expected
    if op == 'NEQ':
        return actual != expected
    if op == 'IN':
        values = expected if isinstance(expected, list) else [expected]
        return actual in values
    if op == 'NOT_EMPTY':
        return actual not in (None, '', [], {})
    return True


def validate_attribute_definitions_entry(entry: Dict[str, Any], existing: Optional[Dict[str, Any]], definitions: Optional[Definitions] = None) -> None:
    cfg = entry.get('config') or {}
    if not isinstance(cfg, dict):
        raise ProfileSchemaError('config must be an object', 'VALIDATION_ERROR')

    attr_type = (cfg.get('type') or '').upper()
    if attr_type not in _ALLOWED_TYPES:
        raise ProfileSchemaError('Attribute type is invalid', 'VALIDATION_ERROR')

    handler = cfg.get('handler')
    if handler and handler not in _HANDLER_REGISTRY:
        raise ProfileSchemaError('Unknown handler name', 'VALIDATION_ERROR')

    defs = definitions or get_definitions()
    section_id = cfg.get('sectionId')
    if section_id and section_id not in defs.sections:
        raise ProfileSchemaError('Unknown sectionId reference', 'VALIDATION_ERROR')

    lov_id = cfg.get('lovId')
    if lov_id and lov_id not in defs.lovs:
        raise ProfileSchemaError('Unknown lovId reference', 'VALIDATION_ERROR')

    depends_on = cfg.get('dependsOn')
    if depends_on and depends_on not in defs.attributes and (not existing or depends_on != existing.get('configId')):
        raise ProfileSchemaError('Unknown dependsOn attribute', 'VALIDATION_ERROR')

    visible_when = cfg.get('visibleWhen')
    if visible_when:
        target = visible_when.get('attribute')
        if target and target not in defs.attributes and (not existing or target != existing.get('configId')):
            raise ProfileSchemaError('Unknown visibleWhen attribute', 'VALIDATION_ERROR')

    if existing:
        existing_cfg = existing.get('config') or {}
        if existing.get('configId') != entry.get('configId'):
            raise ProfileSchemaError('Attribute key cannot be changed', 'IMMUTABLE_FIELD')
        if (existing_cfg.get('type') or '').upper() != attr_type:
            raise ProfileSchemaError('Attribute type cannot be changed', 'IMMUTABLE_FIELD')

        if existing_cfg.get('system'):
            if not entry.get('enabled', True):
                raise ProfileSchemaError('System attributes cannot be disabled', 'SYSTEM_ATTRIBUTE_PROTECTED')
            existing_storage = existing_cfg.get('storage') or {}
            new_storage = cfg.get('storage') or {}
            if existing_storage != new_storage:
                raise ProfileSchemaError('System attribute storage is immutable', 'IMMUTABLE_FIELD')


def _apply_handler_normalization(attr_def: Dict[str, Any], value: Any, profile: Dict[str, Any], caller_is_admin: bool) -> Any:
    cfg = attr_def.get('config') or {}
    handler = cfg.get('handler')
    key = attr_def.get('configId')

    if handler == 'PERSONAL_CODE' and value is not None:
        return normalize_personal_code(value)

    if handler == 'COGNITO_EMAIL' and not caller_is_admin:
        raise ProfileSchemaError(
            message=f"{key} is controlled by the system",
            code='ADMIN_ONLY_ATTRIBUTE',
            status_code=403,
        )

    if handler == 'PROFILE_PHOTO' and value is not None:
        if not isinstance(value, str) or not value.strip():
            raise ProfileSchemaError(
                message=f"{key} must be a non-empty S3 key string",
                code='VALIDATION_ERROR',
                status_code=422,
            )
        profile_id = str(profile.get('profileId') or '').strip()
        s3_key = value.strip()
        if not profile_id or '/' in profile_id or '\\' in profile_id:
            raise ProfileSchemaError(
                message=f"{key} cannot be validated for this profile",
                code='VALIDATION_ERROR',
                status_code=422,
            )
        if '..' in [segment for segment in s3_key.split('/') if segment]:
            raise ProfileSchemaError(
                message=f"{key} must not contain path traversal segments",
                code='VALIDATION_ERROR',
                status_code=422,
            )
        if not s3_key.startswith((f'riders/{profile_id}/photo/', f'profiles/{profile_id}/')):
            raise ProfileSchemaError(
                message=f"{key} must be under riders/{profile_id}/photo/ or profiles/{profile_id}/",
                code='VALIDATION_ERROR',
                status_code=422,
            )
        return s3_key

    return value


def merge_profile_values(
    existing_profile: Dict[str, Any],
    submitted_payload: Dict[str, Any],
    *,
    event: Optional[Dict[str, Any]] = None,
    enforce_required: bool = True,
    is_save: bool = True,
) -> Tuple[Dict[str, Any], str]:
    definitions = get_definitions()
    role_flags = get_user_role_flags(event or {})
    caller_is_admin = role_flags['is_admin']

    profile = copy.deepcopy(existing_profile or {})
    if not isinstance(profile.get('attributes'), dict):
        profile['attributes'] = copy.deepcopy(profile.get('attributes') or {}) if isinstance(profile.get('attributes'), dict) else {}

    submitted_core_keys = {
        k: v for k, v in submitted_payload.items()
        if k not in {'profileId', 'attributes', 'definitionsVersion', 'createdAt', 'updatedAt'}
    }
    submitted_attr_keys = submitted_payload.get('attributes') or {}
    if submitted_attr_keys is None:
        submitted_attr_keys = {}
    if not isinstance(submitted_attr_keys, dict):
        raise ProfileSchemaError('attributes must be an object', 'VALIDATION_ERROR')

    core_path_to_attribute: Dict[str, str] = {}
    for attr_key, attr_def in definitions.attributes.items():
        storage = _storage_for(attr_def)
        if (storage.get('scope') or '').upper() != 'CORE':
            continue
        storage_path = storage.get('path')
        if storage_path:
            core_path_to_attribute[storage_path] = attr_key

    to_process: Dict[str, Any] = {}
    for submitted_key, submitted_value in submitted_core_keys.items():
        resolved_key = core_path_to_attribute.get(submitted_key)
        if resolved_key is None and submitted_key in definitions.attributes:
            resolved_key = submitted_key
        if resolved_key is None:
            raise ProfileSchemaError(
                message=f"Attribute '{submitted_key}' is unknown or disabled",
                code='UNKNOWN_OR_DISABLED_ATTRIBUTE',
                status_code=422,
            )
        to_process[resolved_key] = submitted_value

    for attr_key, value in submitted_attr_keys.items():
        if attr_key not in definitions.attributes:
            raise ProfileSchemaError(
                message=f"Attribute '{attr_key}' is unknown or disabled",
                code='UNKNOWN_OR_DISABLED_ATTRIBUTE',
                status_code=422,
            )
        to_process[attr_key] = value

    for key, value in to_process.items():
        attr_def = definitions.attributes.get(key)
        if not attr_def:
            raise ProfileSchemaError(
                message=f"Attribute '{key}' is unknown or disabled",
                code='UNKNOWN_OR_DISABLED_ATTRIBUTE',
                status_code=422,
            )

        flags = _attr_flags(attr_def)
        if flags['adminOnly'] and not caller_is_admin:
            raise ProfileSchemaError(
                message=f"Attribute '{key}' is admin-only",
                code='ADMIN_ONLY_ATTRIBUTE',
                status_code=403,
            )

        normalized = _apply_handler_normalization(attr_def, value, profile, caller_is_admin)
        if normalized is None:
            if flags['required']:
                raise ProfileSchemaError(
                    message=f"Attribute '{key}' cannot be null",
                    code='VALIDATION_ERROR',
                    status_code=422,
                )
            clear_attribute_value(profile, key, attr_def)
            continue
        validated = _validate_scalar_value(normalized, key, attr_def, definitions, profile)
        write_attribute_value(profile, key, attr_def, validated)

    if enforce_required and is_save:
        for key, attr_def in definitions.attributes.items():
            flags = _attr_flags(attr_def)
            if not flags['required']:
                continue
            if not _is_attribute_visible(key, attr_def, profile):
                continue
            if not caller_is_admin and flags['adminOnly']:
                continue
            required_value = read_attribute_value(profile, key, attr_def)
            if required_value in (None, '', [], {}):
                raise ProfileSchemaError(
                    message=f"Attribute '{key}' is required",
                    code='VALIDATION_ERROR',
                    status_code=422,
                )

    return profile, definitions.version


def filter_profile_for_response(
    profile: Dict[str, Any],
    *,
    event: Optional[Dict[str, Any]] = None,
    staff_mode: bool = False,
) -> Dict[str, Any]:
    definitions = get_definitions()
    flags = get_user_role_flags(event or {})
    include_restricted = flags['is_admin'] or flags['is_super_user'] or not staff_mode

    result = copy.deepcopy(profile)
    stored_attributes = result.get('attributes') if isinstance(result.get('attributes'), dict) else {}
    filtered_attrs: Dict[str, Any] = {}
    sensitive_keys: List[str] = []

    for key, attr_def in definitions.attributes.items():
        attr_flags = _attr_flags(attr_def)
        storage = _storage_for(attr_def)
        should_include = not staff_mode or include_restricted or attr_flags['visibleToAllMgmtUsers']

        if storage.get('scope') == 'CORE':
            core_path = storage.get('path')
            if core_path and not should_include:
                result.pop(core_path, None)
            if should_include and attr_flags['sensitive'] and core_path and core_path in result:
                sensitive_keys.append(key)

    for key, value in (stored_attributes or {}).items():
        attr_def = definitions.attributes.get(key)
        if not attr_def:
            continue
        attr_flags = _attr_flags(attr_def)
        if staff_mode and not include_restricted and not attr_flags['visibleToAllMgmtUsers']:
            continue
        filtered_attrs[key] = value
        if attr_flags['sensitive']:
            sensitive_keys.append(key)

    result['attributes'] = filtered_attrs
    result['definitionsVersion'] = definitions.version
    if sensitive_keys:
        result['sensitiveKeys'] = sorted(sensitive_keys)
    return result


def get_attribute_definition(attribute_key: str) -> Optional[Dict[str, Any]]:
    return get_definitions().attributes.get(attribute_key)


def require_file_attribute_definition(attribute_key: str) -> Dict[str, Any]:
    attr_def = get_attribute_definition(attribute_key)
    if not attr_def:
        raise ProfileSchemaError(
            message=f"Attribute '{attribute_key}' is unknown or disabled",
            code='UNKNOWN_OR_DISABLED_ATTRIBUTE',
            status_code=422,
        )

    cfg = attr_def.get('config') or {}
    attr_type = (cfg.get('type') or '').upper()
    if attr_type not in {'FILE', 'IMAGE'}:
        raise ProfileSchemaError(
            message=f"Attribute '{attribute_key}' is not a file/image attribute",
            code='VALIDATION_ERROR',
            status_code=422,
        )

    if (_storage_for(attr_def).get('scope') or '').upper() != 'ATTRIBUTES':
        raise ProfileSchemaError(
            message=f"Attribute '{attribute_key}' upload is supported only for ATTRIBUTES storage",
            code='VALIDATION_ERROR',
            status_code=422,
        )

    return attr_def


def validate_attribute_upload_request(attribute_key: str, content_type: str, size_bytes: int) -> Dict[str, Any]:
    attr_def = require_file_attribute_definition(attribute_key)
    cfg = attr_def.get('config') or {}
    validation = cfg.get('validation') or {}
    allowed = validation.get('allowedMimeTypes') or []
    if allowed and content_type not in allowed:
        raise ProfileSchemaError(
            message=f"Unsupported contentType for '{attribute_key}'",
            code='VALIDATION_ERROR',
            status_code=422,
        )

    max_size = validation.get('maxFileSizeBytes')
    if max_size is not None and int(size_bytes) > int(max_size):
        raise ProfileSchemaError(
            message=f"File too large for '{attribute_key}'",
            code='VALIDATION_ERROR',
            status_code=422,
        )

    return attr_def
