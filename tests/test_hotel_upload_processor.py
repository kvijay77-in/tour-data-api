"""Hotel allocation CSV processor tests (§8.22a/§8.22b, D21)."""

import json
import os
import sys

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, 'src/layers/common')
sys.path.insert(0, 'src/functions/hotels')


TOUR_ID = 'TestTour-2026'
BUCKET = 'test-artifacts-bucket'
UPLOADER = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'


class _Context:
    """Lambda context whose remaining time drops once `low_after` checks have passed."""

    def __init__(self, low_after=None):
        self.calls = 0
        self.low_after = low_after

    def get_remaining_time_in_millis(self):
        self.calls += 1
        if self.low_after is not None and self.calls > self.low_after:
            return 1000
        return 100000


@pytest.fixture
def hotel_upload_setup():
    os.environ.update({
        'AWS_ACCESS_KEY_ID': 'testing',
        'AWS_SECRET_ACCESS_KEY': 'testing',
        'AWS_SECURITY_TOKEN': 'testing',
        'AWS_SESSION_TOKEN': 'testing',
        'AWS_DEFAULT_REGION': 'us-east-1',
        'STACK_NAME': 'test-stack',
        'APP_CONFIG_TABLE': 'test-app-config-table',
        'ARTIFACTS_BUCKET': BUCKET,
        'LOG_LEVEL': 'INFO',
    })
    with mock_aws():
        dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
        dynamodb.create_table(
            TableName='test-app-config-table',
            KeySchema=[
                {'AttributeName': 'configType', 'KeyType': 'HASH'},
                {'AttributeName': 'configId', 'KeyType': 'RANGE'},
            ],
            AttributeDefinitions=[
                {'AttributeName': 'configType', 'AttributeType': 'S'},
                {'AttributeName': 'configId', 'AttributeType': 'S'},
            ],
            BillingMode='PAY_PER_REQUEST',
        )
        dynamodb.create_table(
            TableName=f'test-stack-Hotel-{TOUR_ID}',
            KeySchema=[{'AttributeName': 'hotelId', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'hotelId', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )
        dynamodb.create_table(
            TableName=f'test-stack-TourRider-{TOUR_ID}',
            KeySchema=[{'AttributeName': 'riderId', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'riderId', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )
        dynamodb.create_table(
            TableName=f'test-stack-RoomAllocation-{TOUR_ID}',
            KeySchema=[
                {'AttributeName': 'stayDate', 'KeyType': 'HASH'},
                {'AttributeName': 'riderId', 'KeyType': 'RANGE'},
            ],
            AttributeDefinitions=[
                {'AttributeName': 'stayDate', 'AttributeType': 'S'},
                {'AttributeName': 'riderId', 'AttributeType': 'S'},
            ],
            BillingMode='PAY_PER_REQUEST',
        )
        s3 = boto3.client('s3', region_name='us-east-1')
        s3.create_bucket(Bucket=BUCKET)

        hotels = dynamodb.Table(f'test-stack-Hotel-{TOUR_ID}')
        for hotel_id in ('HTL-MDU-01', 'HTL-MDU-02'):
            hotels.put_item(Item={'hotelId': hotel_id, 'name': hotel_id, 'city': 'Madurai', 'address': 'Addr'})
        riders = dynamodb.Table(f'test-stack-TourRider-{TOUR_ID}')
        with riders.batch_writer() as batch:
            for number in range(1, 201):
                batch.put_item(Item={'riderId': f'R{number}', 'status': 'ACTIVE'})
        riders.put_item(Item={'riderId': 'R300', 'status': 'WITHDRAWN'})
        riders.put_item(Item={'riderId': 'R301', 'status': 'EXITED'})

        import dynamodb_utils
        dynamodb_utils.TABLES = {}
        dynamodb_utils.dynamodb = dynamodb
        import event_engine
        event_engine.s3_client = s3

        yield {'dynamodb': dynamodb, 's3': s3, 'engine': event_engine}


def _presign(engine):
    event = {
        'pathParameters': {'tourId': TOUR_ID},
        'requestContext': {'authorizer': {'jwt': {'claims': {'sub': UPLOADER}}}},
    }
    response = engine.presign_hotel_upload(event)
    return json.loads(response['body'])['data']


def _upload(setup, csv_text):
    upload = _presign(setup['engine'])
    setup['s3'].put_object(Bucket=BUCKET, Key=upload['s3Key'], Body=csv_text.encode('utf-8'))
    return upload


def _process(setup, upload, context=None):
    from process_upload import lambda_handler
    event = {
        'source': 'aws.s3',
        'detail-type': 'Object Created',
        'detail': {'bucket': {'name': BUCKET}, 'object': {'key': upload['s3Key']}},
    }
    return lambda_handler(event, context or _Context())


def _status(setup, upload):
    return setup['dynamodb'].Table(f'test-stack-Hotel-{TOUR_ID}').get_item(
        Key={'hotelId': f"UPLOAD#{upload['uploadId']}"}
    )['Item']


def _allocations(setup):
    return setup['dynamodb'].Table(f'test-stack-RoomAllocation-{TOUR_ID}').scan()['Items']


def _codes(status):
    return [error['code'] for error in status['errors']]


def _put_allocation(setup, stay_date, rider_id, room_no, sharing_with=None, hotel_id='HTL-MDU-01', capacity=2):
    setup['dynamodb'].Table(f'test-stack-RoomAllocation-{TOUR_ID}').put_item(Item={
        'stayDate': stay_date,
        'riderId': rider_id,
        'hotelId': hotel_id,
        'roomNo': room_no,
        'roomCapacity': capacity,
        'sharingWith': sharing_with or [],
        'source': 'MANUAL',
        'createdAt': '2026-01-01T00:00:00Z',
        'updatedAt': '2026-01-01T00:00:00Z',
    })


def _put_config(setup, config, enabled=True):
    setup['dynamodb'].Table('test-app-config-table').put_item(Item={
        'configType': 'HOTEL_UPLOAD',
        'configId': 'PROCESSING',
        'enabled': enabled,
        'config': config,
    })


VALID_CSV = """\ufeff# stayDates=2026-02-11,2026-02-12
# hotelId=HTL-MDU-01
riderId,hotelId,roomNo,roomCapacity,sharingWith
R1,HTL-MDU-01,204,2,R2
R2,,204,2,R1
R58,HTL-MDU-01,207,3,R59;R60
R59,HTL-MDU-01,207,3,R58;R60
R60,HTL-MDU-01,207,3,R58;R59
R57,HTL-MDU-02,311,2,
"""


def test_presign_records_uploader(hotel_upload_setup):
    upload = _presign(hotel_upload_setup['engine'])
    status = _status(hotel_upload_setup, upload)
    assert status['status'] == 'PENDING'
    assert status['createdBy'] == UPLOADER


def test_valid_upload_is_applied(hotel_upload_setup):
    upload = _upload(hotel_upload_setup, VALID_CSV)
    result = _process(hotel_upload_setup, upload)

    status = _status(hotel_upload_setup, upload)
    assert result['status'] == 'APPLIED'
    assert status['status'] == 'APPLIED'
    assert status['rowCount'] == 6
    assert status['appliedCount'] == 12
    assert status['errorCount'] == 0
    items = _allocations(hotel_upload_setup)
    assert len(items) == 12
    r2 = next(item for item in items if item['riderId'] == 'R2' and item['stayDate'] == '2026-02-12')
    assert r2['hotelId'] == 'HTL-MDU-01'
    assert r2['sharingWith'] == ['R1']
    assert r2['source'] == 'UPLOAD'
    assert r2['uploadId'] == upload['uploadId']
    assert r2['updatedBy'] == UPLOADER


def test_start_date_and_nights_expansion(hotel_upload_setup):
    csv_text = "# startDate=2026-02-11\n# nights=3\n# hotelId=HTL-MDU-01\nriderId,roomNo\nR1,101\n"
    upload = _upload(hotel_upload_setup, csv_text)
    _process(hotel_upload_setup, upload)

    assert _status(hotel_upload_setup, upload)['status'] == 'APPLIED'
    assert sorted(item['stayDate'] for item in _allocations(hotel_upload_setup)) == [
        '2026-02-11', '2026-02-12', '2026-02-13'
    ]


def test_single_bad_row_rejects_whole_batch(hotel_upload_setup):
    lines = ['# stayDates=2026-02-11', 'riderId,hotelId,roomNo']
    lines += [f'R{number},HTL-MDU-01,{number}' for number in range(1, 200)]
    lines.append('R200,HTL-XXX-99,200')
    upload = _upload(hotel_upload_setup, '\n'.join(lines))
    _process(hotel_upload_setup, upload)

    status = _status(hotel_upload_setup, upload)
    assert status['status'] == 'REJECTED'
    assert status['rowCount'] == 200
    assert status['errors'] == [
        {'row': 202, 'code': 'UNKNOWN_HOTEL_ID', 'message': 'Hotel HTL-XXX-99 does not exist in this tour.'}
    ]
    assert _allocations(hotel_upload_setup) == []


def test_row_level_errors_are_all_reported(hotel_upload_setup):
    csv_text = (
        "# stayDates=2026-02-11\n"
        "riderId,hotelId,roomNo,roomCapacity,sharingWith\n"
        "R999,HTL-MDU-01,101,2,\n"
        "R300,HTL-MDU-01,102,2,\n"
        "bad,HTL-MDU-01,103,2,\n"
        "R1,HTL-MDU-01,,4,R1\n"
        "R2,HTL-MDU-01,105,2,R3;R4\n"
    )
    upload = _upload(hotel_upload_setup, csv_text)
    _process(hotel_upload_setup, upload)

    status = _status(hotel_upload_setup, upload)
    assert status['status'] == 'REJECTED'
    assert [(error['row'], error['code']) for error in status['errors']] == [
        (3, 'UNKNOWN_RIDER_ID'),
        (4, 'RIDER_NOT_ELIGIBLE'),
        (5, 'INVALID_RIDER_ID'),
        (6, 'MISSING_ROOM_NO'),
        (6, 'INVALID_ROOM_CAPACITY'),
        (6, 'INVALID_SHARING_WITH'),
        (7, 'ROOM_CAPACITY_EXCEEDED'),
    ]


def test_cross_row_errors(hotel_upload_setup):
    csv_text = (
        "# stayDates=2026-02-11\n"
        "riderId,hotelId,roomNo,roomCapacity,sharingWith\n"
        "R1,HTL-MDU-01,204,2,R2\n"
        "R2,HTL-MDU-01,205,2,R1\n"
        "R3,HTL-MDU-01,301,2,\n"
        "R4,HTL-MDU-01,301,2,\n"
    )
    upload = _upload(hotel_upload_setup, csv_text)
    _process(hotel_upload_setup, upload)

    status = _status(hotel_upload_setup, upload)
    assert status['status'] == 'REJECTED'
    assert [(error['row'], error['code']) for error in status['errors']] == [
        (3, 'NON_RECIPROCAL_SHARING'),
        (4, 'NON_RECIPROCAL_SHARING'),
        (5, 'ROOM_CLASH'),
        (6, 'ROOM_CLASH'),
    ]
    assert _allocations(hotel_upload_setup) == []


def test_duplicate_rider_in_file(hotel_upload_setup):
    csv_text = "# stayDates=2026-02-11\nriderId,hotelId,roomNo\nR1,HTL-MDU-01,101\nR1,HTL-MDU-01,102\n"
    upload = _upload(hotel_upload_setup, csv_text)
    _process(hotel_upload_setup, upload)

    status = _status(hotel_upload_setup, upload)
    assert [(error['row'], error['code']) for error in status['errors']] == [(4, 'DUPLICATE_RIDER_FOR_DATE')]


def test_clash_with_existing_manual_allocation(hotel_upload_setup):
    _put_allocation(hotel_upload_setup, '2026-02-11', 'R10', '101')
    csv_text = "# stayDates=2026-02-11\nriderId,hotelId,roomNo\nR1,HTL-MDU-01,101\n"
    upload = _upload(hotel_upload_setup, csv_text)
    _process(hotel_upload_setup, upload)

    status = _status(hotel_upload_setup, upload)
    assert _codes(status) == ['ROOM_CLASH']
    assert len(_allocations(hotel_upload_setup)) == 1


def test_existing_room_mate_left_non_reciprocal(hotel_upload_setup):
    _put_allocation(hotel_upload_setup, '2026-02-11', 'R10', '101', ['R11'])
    _put_allocation(hotel_upload_setup, '2026-02-11', 'R11', '101', ['R10'])
    csv_text = "# stayDates=2026-02-11\nriderId,hotelId,roomNo\nR11,HTL-MDU-01,305\n"
    upload = _upload(hotel_upload_setup, csv_text)
    _process(hotel_upload_setup, upload)

    status = _status(hotel_upload_setup, upload)
    assert [(error['row'], error['code']) for error in status['errors']] == [(3, 'NON_RECIPROCAL_SHARING')]


def test_merge_keeps_other_riders_and_replaces_same_rider(hotel_upload_setup):
    _put_allocation(hotel_upload_setup, '2026-02-11', 'R10', '401')
    _put_allocation(hotel_upload_setup, '2026-02-11', 'R1', '999')
    upload = _upload(hotel_upload_setup, "# stayDates=2026-02-11\nriderId,hotelId,roomNo\nR1,HTL-MDU-01,101\n")
    _process(hotel_upload_setup, upload)

    items = {item['riderId']: item for item in _allocations(hotel_upload_setup)}
    assert _status(hotel_upload_setup, upload)['status'] == 'APPLIED'
    assert items['R10']['source'] == 'MANUAL'
    assert items['R1']['roomNo'] == '101'
    assert items['R1']['source'] == 'UPLOAD'
    assert items['R1']['createdAt'] == '2026-01-01T00:00:00Z'

    second = _upload(hotel_upload_setup, "# stayDates=2026-02-11\nriderId,hotelId,roomNo\nR1,HTL-MDU-01,102\n")
    _process(hotel_upload_setup, second)
    items = {item['riderId']: item for item in _allocations(hotel_upload_setup)}
    assert items['R1']['roomNo'] == '102'
    assert items['R1']['uploadId'] == second['uploadId']


def test_duplicate_event_and_foreign_key_are_ignored(hotel_upload_setup):
    upload = _upload(hotel_upload_setup, VALID_CSV)
    assert _process(hotel_upload_setup, upload)['status'] == 'APPLIED'
    assert _process(hotel_upload_setup, upload)['status'] == 'IGNORED'
    assert _process(hotel_upload_setup, {'s3Key': f'tours/{TOUR_ID}/artifacts/plan.csv'})['status'] == 'IGNORED'


@pytest.mark.parametrize('csv_text, code', [
    ('riderId,roomNo\nR1,101\n', 'MISSING_STAY_DATES'),
    ('# stayDates=2026-02-11\n# comment only\n', 'INVALID_HEADER'),
    ('# stayDates=2026-02-11\nriderId,roomNo,colour\nR1,101,red\n', 'INVALID_HEADER'),
    ('# stayDates=2026-02-11\nriderId,roomNo\n', 'EMPTY_FILE'),
    ('# stayDates=2026-02-30\nriderId,hotelId,roomNo\nR1,HTL-MDU-01,101\n', 'INVALID_STAY_DATES'),
    ('# startDate=2026-02-11\nriderId,hotelId,roomNo\nR1,HTL-MDU-01,101\n', 'INVALID_STAY_DATES'),
    ('# startDate=2026-02-11\n# nights=40\nriderId,hotelId,roomNo\nR1,HTL-MDU-01,101\n', 'TOO_MANY_STAY_DATES'),
])
def test_file_level_errors(hotel_upload_setup, csv_text, code):
    upload = _upload(hotel_upload_setup, csv_text)
    _process(hotel_upload_setup, upload)

    status = _status(hotel_upload_setup, upload)
    assert status['status'] == 'REJECTED'
    assert code in _codes(status)


def test_limits_come_from_app_config(hotel_upload_setup):
    _put_config(hotel_upload_setup, {'maxDataRows': 1, 'maxFileSizeBytes': 'bad'})
    upload = _upload(hotel_upload_setup, VALID_CSV)
    _process(hotel_upload_setup, upload)
    assert _codes(_status(hotel_upload_setup, upload)) == ['TOO_MANY_ROWS']

    _put_config(hotel_upload_setup, {'maxFileSizeBytes': 10})
    upload = _upload(hotel_upload_setup, VALID_CSV)
    _process(hotel_upload_setup, upload)
    assert _codes(_status(hotel_upload_setup, upload)) == ['FILE_TOO_LARGE']


def test_disabled_config_uses_defaults(hotel_upload_setup):
    _put_config(hotel_upload_setup, {'maxDataRows': 1}, enabled=False)
    engine = hotel_upload_setup['engine']
    assert engine._get_hotel_upload_config() == engine.HOTEL_UPLOAD_CONFIG_DEFAULTS


def test_error_list_is_capped(hotel_upload_setup):
    _put_config(hotel_upload_setup, {'maxStoredErrors': 2})
    lines = ['# stayDates=2026-02-11', 'riderId,hotelId,roomNo'] + [f'R{n},HTL-XXX-99,{n}' for n in range(1, 6)]
    upload = _upload(hotel_upload_setup, '\n'.join(lines))
    _process(hotel_upload_setup, upload)

    status = _status(hotel_upload_setup, upload)
    assert status['errorCount'] == 5
    assert len(status['errors']) == 2


def test_time_reserve_before_apply_rejects_with_timeout(hotel_upload_setup):
    upload = _upload(hotel_upload_setup, VALID_CSV)
    _process(hotel_upload_setup, upload, _Context(low_after=1))

    status = _status(hotel_upload_setup, upload)
    assert status['status'] == 'REJECTED'
    assert _codes(status) == ['PROCESSING_TIMEOUT']
    assert _allocations(hotel_upload_setup) == []


def test_time_reserve_during_apply_rolls_back(hotel_upload_setup):
    _put_allocation(hotel_upload_setup, '2026-02-11', 'R1', '999')
    lines = ['# stayDates=2026-02-11,2026-02-12', 'riderId,hotelId,roomNo']
    lines += [f'R{number},HTL-MDU-01,{number}' for number in range(1, 61)]
    upload = _upload(hotel_upload_setup, '\n'.join(lines))
    # checks: file read, phase 1, 2 stay dates, before build, chunk 1 -> low at chunk 2
    _process(hotel_upload_setup, upload, _Context(low_after=6))

    status = _status(hotel_upload_setup, upload)
    assert _codes(status) == ['PROCESSING_TIMEOUT']
    items = _allocations(hotel_upload_setup)
    assert len(items) == 1
    assert items[0]['roomNo'] == '999'
    assert items[0]['source'] == 'MANUAL'


def test_concurrent_modification_rolls_back(hotel_upload_setup, monkeypatch):
    _put_allocation(hotel_upload_setup, '2026-02-11', 'R1', '999')
    engine = hotel_upload_setup['engine']
    original = engine._write_hotel_upload_snapshot

    def snapshot_then_edit(*args, **kwargs):
        original(*args, **kwargs)
        _put_allocation(hotel_upload_setup, '2026-02-11', 'R1', '888')
        table = hotel_upload_setup['dynamodb'].Table(f'test-stack-RoomAllocation-{TOUR_ID}')
        table.update_item(
            Key={'stayDate': '2026-02-11', 'riderId': 'R1'},
            UpdateExpression='SET updatedAt = :now',
            ExpressionAttributeValues={':now': '2026-02-01T00:00:00Z'},
        )

    monkeypatch.setattr(engine, '_write_hotel_upload_snapshot', snapshot_then_edit)
    upload = _upload(hotel_upload_setup, "# stayDates=2026-02-11\nriderId,hotelId,roomNo\nR1,HTL-MDU-01,101\n")
    _process(hotel_upload_setup, upload)

    assert _codes(_status(hotel_upload_setup, upload)) == ['CONCURRENT_MODIFICATION']
    assert [item['roomNo'] for item in _allocations(hotel_upload_setup)] == ['888']


def _failure_event(upload, error_type='Sandbox.Timedout', message='Task timed out after 120.00 seconds'):
    return {
        'requestContext': {'condition': 'RetriesExhausted'},
        'requestPayload': {'detail': {'bucket': {'name': BUCKET}, 'object': {'key': upload['s3Key']}}},
        'responsePayload': {'errorType': error_type, 'errorMessage': message},
    }


def _mark_validating(setup, upload, apply_started=False):
    fields = {'status': 'VALIDATING'}
    if apply_started:
        fields['applyStartedAt'] = '2026-02-01T00:00:00Z'
    setup['engine']._update_upload_status(TOUR_ID, upload['uploadId'], fields, 'PENDING')


def test_failure_handler_records_timeout(hotel_upload_setup):
    from process_upload_failure import lambda_handler
    upload = _upload(hotel_upload_setup, VALID_CSV)
    _mark_validating(hotel_upload_setup, upload)

    lambda_handler(_failure_event(upload), None)
    status = _status(hotel_upload_setup, upload)
    assert status['status'] == 'REJECTED'
    assert _codes(status) == ['PROCESSING_TIMEOUT']


def test_failure_handler_records_crash(hotel_upload_setup):
    from process_upload_failure import lambda_handler
    upload = _upload(hotel_upload_setup, VALID_CSV)
    _mark_validating(hotel_upload_setup, upload)

    lambda_handler(_failure_event(upload, 'Runtime.OutOfMemory', 'Runtime exited'), None)
    assert _codes(_status(hotel_upload_setup, upload)) == ['PROCESSING_ERROR']


def test_failure_handler_rolls_back_started_apply(hotel_upload_setup):
    from process_upload_failure import lambda_handler
    engine = hotel_upload_setup['engine']
    _put_allocation(hotel_upload_setup, '2026-02-11', 'R1', '999')
    upload = _upload(hotel_upload_setup, VALID_CSV)
    previous = hotel_upload_setup['dynamodb'].Table(f'test-stack-RoomAllocation-{TOUR_ID}').get_item(
        Key={'stayDate': '2026-02-11', 'riderId': 'R1'}
    )['Item']
    written = [
        ({'stayDate': '2026-02-11', 'riderId': 'R1', 'hotelId': 'HTL-MDU-01', 'roomNo': '101', 'roomCapacity': 2,
          'sharingWith': [], 'source': 'UPLOAD', 'uploadId': upload['uploadId']}, previous),
        ({'stayDate': '2026-02-11', 'riderId': 'R2', 'hotelId': 'HTL-MDU-01', 'roomNo': '102', 'roomCapacity': 2,
          'sharingWith': [], 'source': 'UPLOAD', 'uploadId': upload['uploadId']}, None),
    ]
    engine._write_hotel_upload_snapshot(BUCKET, TOUR_ID, upload['uploadId'], written)
    table = hotel_upload_setup['dynamodb'].Table(f'test-stack-RoomAllocation-{TOUR_ID}')
    for item, _ in written:
        table.put_item(Item=item)
    _mark_validating(hotel_upload_setup, upload, apply_started=True)

    lambda_handler(_failure_event(upload), None)
    items = _allocations(hotel_upload_setup)
    assert _codes(_status(hotel_upload_setup, upload)) == ['PROCESSING_TIMEOUT']
    assert len(items) == 1
    assert items[0]['roomNo'] == '999'
    assert items[0]['source'] == 'MANUAL'


def test_failure_handler_ignores_final_status(hotel_upload_setup):
    from process_upload_failure import lambda_handler
    upload = _upload(hotel_upload_setup, VALID_CSV)
    _process(hotel_upload_setup, upload)

    assert lambda_handler(_failure_event(upload), None)['status'] == 'IGNORED'
    assert _status(hotel_upload_setup, upload)['status'] == 'APPLIED'
