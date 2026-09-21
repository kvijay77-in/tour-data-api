import sys
sys.path.insert(0, '/opt/python')

from event_engine import list_occurrences


def lambda_handler(event, context):
    return list_occurrences(event)
