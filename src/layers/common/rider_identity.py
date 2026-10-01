"""
Rider identity resolution for Rider API self-service endpoints.

The rider ID used by self check-in, event registration, event self-records and
the Rider API own-data rule always comes from the caller's login:

    Cognito user (JWT ``sub``) -> ``RiderCognitoUser`` link -> ``profileId``
    -> ``TourRider-{tourId}`` row (``ProfileIdIndex``) -> ``riderId``

A rider ID supplied in a request body is never trusted.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, Optional, Tuple

from botocore.exceptions import ClientError

from dynamodb_utils import query_tour_items
from logger import get_logger
from models import TourRiderStatus
from ownership import get_jwt_sub, resolve_profile_id_for_sub
from rbac import get_user_groups
from response import error_response


logger = get_logger(__name__)

RIDER_GROUP = 'RIDER'
INACTIVE_TOUR_RIDER_STATUSES = {TourRiderStatus.EXITED.value, TourRiderStatus.WITHDRAWN.value}


def _claims(event: Dict[str, Any]) -> Dict[str, Any]:
    return (
        (event or {}).get('requestContext', {})
        .get('authorizer', {})
        .get('jwt', {})
        .get('claims', {})
    ) or {}


def is_rider_caller(event: Dict[str, Any]) -> bool:
    """Return True when the caller signed in through the rider user pool.

    The token issuer is compared with ``RIDER_USER_POOL_ID`` when it is
    configured. The ``RIDER`` group (only defined in the rider pool) is also
    treated as a rider caller so the own-data rule fails closed.
    """
    rider_pool_id = os.environ.get('RIDER_USER_POOL_ID', '').strip()
    issuer = str(_claims(event).get('iss') or '').rstrip('/')
    if rider_pool_id and issuer.endswith(f'/{rider_pool_id}'):
        return True
    return RIDER_GROUP in get_user_groups(event)


def rider_not_in_tour_response(message: str = 'You are not a rider on this tour') -> Dict[str, Any]:
    return error_response(error_code='RIDER_NOT_IN_TOUR', message=message, status_code=403)


def _find_tour_rider_by_profile(tour_id: str, profile_id: str) -> Optional[Dict[str, Any]]:
    try:
        items = query_tour_items(
            table_type='TourRider',
            tour_id=tour_id,
            key_condition_expression='profileId = :profileId',
            expression_values={':profileId': profile_id},
            index_name='ProfileIdIndex',
        )
    except ClientError as exc:
        if exc.response.get('Error', {}).get('Code') == 'ResourceNotFoundException':
            return None
        raise
    return items[0] if items else None


def resolve_caller_tour_rider(
    event: Dict[str, Any],
    tour_id: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Resolve the caller's rider identity for a tour.

    Returns ``(identity, None)`` with ``profileId``, ``riderId`` and the
    ``tourRider`` row, or ``(None, 403 RIDER_NOT_IN_TOUR)`` when there is no
    link, profile or ``TourRider`` row.
    """
    claims = _claims(event)
    candidates = [get_jwt_sub(event), claims.get('username'), claims.get('cognito:username')]
    profile_id = None
    for candidate in candidates:
        if candidate:
            profile_id = resolve_profile_id_for_sub(str(candidate))
            if profile_id:
                break
    if not profile_id:
        return None, rider_not_in_tour_response('No rider profile is linked to this login')

    tour_rider = _find_tour_rider_by_profile(tour_id, profile_id)
    if not tour_rider or not tour_rider.get('riderId'):
        return None, rider_not_in_tour_response()

    return {
        'profileId': profile_id,
        'riderId': tour_rider['riderId'],
        'tourRider': tour_rider,
    }, None


def is_active_tour_rider(tour_rider: Dict[str, Any]) -> bool:
    """A rider counts as on the tour unless their status is EXITED or WITHDRAWN."""
    return str(tour_rider.get('status') or '').upper() not in INACTIVE_TOUR_RIDER_STATUSES


def resolve_active_caller_tour_rider(
    event: Dict[str, Any],
    tour_id: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Like ``resolve_caller_tour_rider`` but EXITED/WITHDRAWN riders get 403 RIDER_NOT_IN_TOUR."""
    identity, error = resolve_caller_tour_rider(event, tour_id)
    if error:
        return None, error
    if not is_active_tour_rider(identity['tourRider']):
        return None, rider_not_in_tour_response(
            f"Rider {identity['riderId']} is {identity['tourRider'].get('status')} on this tour"
        )
    return identity, None


def reject_client_rider_id(body: Dict[str, Any], sources: Iterable[Dict[str, Any]] = ()) -> Optional[Dict[str, Any]]:
    """Reject ``riderId`` sent by the client; it always comes from the login."""
    for source in (body or {}, *sources):
        if isinstance(source, dict) and 'riderId' in source:
            return error_response(
                error_code='VALIDATION_ERROR',
                message='riderId must not be sent; it is taken from your login',
                status_code=400,
                details={'field': 'riderId'},
            )
    return None


def require_own_rider_data(event: Dict[str, Any], tour_id: str, rider_id: str) -> Optional[Dict[str, Any]]:
    """Rider API own-data rule: a rider caller may only read their own rider ID.

    Management callers are not restricted by this rule.
    """
    if not is_rider_caller(event):
        return None
    identity, _ = resolve_caller_tour_rider(event, tour_id)
    if identity and identity['riderId'] == rider_id:
        return None
    return error_response(
        error_code='NOT_OWN_DATA',
        message='You can only read your own rider data',
        status_code=403,
    )
