import sys
sys.path.insert(0, '/opt/python')

from event_engine import handle_hotel_upload_failure


def lambda_handler(event, context):
    return handle_hotel_upload_failure(event)
