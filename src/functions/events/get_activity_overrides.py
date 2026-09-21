import sys
sys.path.insert(0, '/opt/python')

from event_engine import get_activity_overrides


def lambda_handler(event, context):
    return get_activity_overrides(event)
