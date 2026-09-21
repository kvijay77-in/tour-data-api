import sys
sys.path.insert(0, '/opt/python')

from event_engine import get_occurrence_response


def lambda_handler(event, context):
    return get_occurrence_response(event)
