import sys
sys.path.insert(0, '/opt/python')

from event_engine import process_hotel_upload


def lambda_handler(event, context):
    detail = event.get('detail') or {}
    return process_hotel_upload(
        (detail.get('bucket') or {}).get('name'),
        (detail.get('object') or {}).get('key'),
        context,
    )
