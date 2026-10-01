from pathlib import Path
import re


TEMPLATE = Path(__file__).resolve().parents[1] / 'template.yaml'


def _resource_block(template, logical_id):
    match = re.search(
        rf'^  {re.escape(logical_id)}:\n(.*?)(?=^  [A-Za-z][A-Za-z0-9]+:\n|\Z)',
        template,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f'Missing SAM resource {logical_id}'
    return match.group(1)


def test_rider_self_checkin_and_cancel_routes_are_deployed():
    template = TEMPLATE.read_text()

    create_route = _resource_block(template, 'SelfCheckInFunction')
    assert 'Handler: self_checkin.lambda_handler' in create_route
    assert 'ApiId: !Ref RiderApi' in create_route
    assert 'Path: /v1/tours/{tourId}/rides/{rideId}/self-checkins' in create_route
    assert 'Method: POST' in create_route

    cancel_route = _resource_block(template, 'CancelSelfCheckInFunction')
    assert 'Handler: cancel_self_checkin.lambda_handler' in cancel_route
    assert 'ApiId: !Ref RiderApi' in cancel_route
    assert 'Path: /v1/tours/{tourId}/rides/{rideId}/self-checkins/{checkInId}/cancel' in cancel_route
    assert 'Method: POST' in cancel_route


def test_event_registration_and_self_record_routes_are_deployed():
    template = TEMPLATE.read_text()
    expected = {
        'CreateSelfEventRecordFunction': ('RiderApi', '/self-records', 'POST'),
        'CancelSelfEventRecordFunction': ('RiderApi', '/self-records/{recordId}/cancel', 'POST'),
        'RegisterForEventFunction': ('RiderApi', '/registration', 'POST'),
        'UnregisterFromEventFunction': ('RiderApi', '/registration', 'DELETE'),
        'ListEventRegistrationsFunction': ('TourDataApi', '/registrations', 'GET'),
        'StaffRegisterEventRiderFunction': ('TourDataApi', '/registrations/{riderId}', 'PUT'),
        'StaffUnregisterEventRiderFunction': ('TourDataApi', '/registrations/{riderId}', 'DELETE'),
    }

    for logical_id, (api, suffix, method) in expected.items():
        block = _resource_block(template, logical_id)
        assert f'ApiId: !Ref {api}' in block
        assert f'Path: /v1/tours/{{tourId}}/events/{{eventId}}/occurrences/{{occurrenceId}}{suffix}' in block
        assert f'Method: {method}' in block


def test_rider_event_reads_are_deployed_on_rider_api():
    template = TEMPLATE.read_text()
    for logical_id, path in (
        ('ListEventsFunction', '/v1/tours/{tourId}/events'),
        ('GetEventFunction', '/v1/tours/{tourId}/events/{eventId}'),
        ('ListEventOccurrencesFunction', '/v1/tours/{tourId}/events/{eventId}/occurrences'),
        ('GetEventOccurrenceFunction', '/v1/tours/{tourId}/events/{eventId}/occurrences/{occurrenceId}'),
        ('GetEventsBootstrapFunction', '/v1/tours/{tourId}/events/bootstrap'),
    ):
        block = _resource_block(template, logical_id)
        rider_route = block.split('RiderHttpApi:', 1)[1]
        assert 'ApiId: !Ref RiderApi' in rider_route
        assert f'Path: {path}' in rider_route