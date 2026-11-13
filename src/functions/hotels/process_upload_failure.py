import sys

from event_engine import handle_hotel_upload_failure

sys.path.insert(0, "/opt/python")


def lambda_handler(event, context):
    return handle_hotel_upload_failure(event)
