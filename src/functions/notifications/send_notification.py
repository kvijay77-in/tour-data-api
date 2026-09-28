import sys
sys.path.insert(0, '/opt/python')

from common import get_jwt_claim, parse_json_body
from logger import get_logger, log_event
from notification_service import notify
from rbac import Permission, require_permission
from response import bad_request_response, internal_error_response, success_response

logger = get_logger(__name__)


def lambda_handler(event, context):
    try:
        log_event(logger, event)
        deny = require_permission(event, Permission.NOTIFICATION_MANAGE)
        if deny:
            return deny

        body = parse_json_body(event)
        rule_id = body.get('ruleId')
        if not isinstance(rule_id, str) or not rule_id:
            return bad_request_response('ruleId is required')

        notification_id = notify(
            rule_id=rule_id,
            tour_id=body.get('tourId'),
            context=body.get('context') or {},
            audience_override=body.get('audiences'),
            actor=get_jwt_claim(event, 'sub', 'system'),
        )
        if not notification_id:
            return success_response({'notificationId': None})

        return success_response({'notificationId': notification_id})

    except ValueError as exc:
        return bad_request_response(str(exc))
    except Exception as exc:
        logger.error('send notification failed: %s', str(exc), exc_info=True)
        return internal_error_response('Failed to send notification')
