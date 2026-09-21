import sys
sys.path.insert(0, '/opt/python')

from event_engine import list_events


def lambda_handler(event, context):
    return list_events(event)
