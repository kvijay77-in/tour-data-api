import sys
sys.path.insert(0, '/opt/python')

from event_engine import get_event_definition_response


def lambda_handler(event, context):
    return get_event_definition_response(event)
