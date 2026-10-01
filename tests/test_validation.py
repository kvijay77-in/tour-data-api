"""
Unit tests for validation utilities
"""

import pytest
import sys
import os

# Add common layer to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'layers', 'common'))

from validation import (
    validate_activity_id,
    validate_event_id,
    validate_hotel_id,
    validate_occurrence_id,
    validate_upload_id,
    validate_rider_id,
    validate_tour_id,
    validate_ride_id,
    validate_stage_id,
    validate_iso_date,
    validate_iso_datetime,
    validate_time_hhmm,
    validate_ride_stages,
    validate_email,
    ValidationError
)


class TestRiderIdValidation:
    """Test Rider ID validation"""
    
    def test_valid_rider_ids(self):
        """Test valid Rider ID formats"""
        valid_ids = ['R1', 'R2', 'R10', 'R57', 'R87', 'R102', 'R999']
        for rider_id in valid_ids:
            validate_rider_id(rider_id)  # Should not raise
    
    def test_invalid_rider_id_format(self):
        """Test invalid Rider ID formats"""
        invalid_ids = ['R01', 'R001', 'r1', 'R', '1', 'R1000', 'RIDER1']
        for rider_id in invalid_ids:
            with pytest.raises(ValidationError):
                validate_rider_id(rider_id)
    
    def test_rider_id_out_of_range(self):
        """Test Rider ID number out of range"""
        with pytest.raises(ValidationError):
            validate_rider_id('R0')
        with pytest.raises(ValidationError):
            validate_rider_id('R1000')


class TestTourIdValidation:
    """Test Tour ID validation (free-form format)"""
    
    def test_valid_tour_ids(self):
        """Test valid Tour ID formats"""
        valid_ids = [
            'TOUR2024', 'TOUR2025', 'TOT-2026',
            'TDF2026', 'TestTour-2026', 'my.tour.2025',
            'abc'
        ]
        for tour_id in valid_ids:
            validate_tour_id(tour_id)  # Should not raise
    
    def test_invalid_tour_id_format(self):
        """Test invalid Tour ID formats"""
        invalid_ids = [
            'ab',         # too short (< 3 chars)
            '-invalid',   # starts with hyphen
            '.invalid',   # starts with dot
            '_invalid',   # starts with underscore
            'a' * 51,     # too long (> 50 chars)
            'has space',  # contains space
            'has@symbol', # contains @
        ]
        for tour_id in invalid_ids:
            with pytest.raises(ValidationError):
                validate_tour_id(tour_id)


class TestRideIdValidation:
    """Test Ride ID validation"""
    
    def test_valid_ride_ids(self):
        """Test valid Ride ID formats"""
        valid_ids = ['RIDE001', 'RIDE010', 'RIDE100', 'RIDE999']
        for ride_id in valid_ids:
            validate_ride_id(ride_id)  # Should not raise
    
    def test_invalid_ride_id_format(self):
        """Test invalid Ride ID formats"""
        invalid_ids = ['ride001', 'RIDE1', 'RIDE01', 'R001', 'RIDE1000']
        for ride_id in invalid_ids:
            with pytest.raises(ValidationError):
                validate_ride_id(ride_id)


class TestStageIdValidation:
    """Test Stage ID validation"""
    
    def test_valid_stage_ids(self):
        """Test valid Stage ID formats"""
        valid_ids = ['S000', 'S010', 'S100', 'S999']
        for stage_id in valid_ids:
            validate_stage_id(stage_id)  # Should not raise
    
    def test_invalid_stage_id_format(self):
        """Test invalid Stage ID formats"""
        invalid_ids = ['s001', 'S1', 'S01', 'STAGE001', 'S1000']
        for stage_id in invalid_ids:
            with pytest.raises(ValidationError):
                validate_stage_id(stage_id)


class TestEventIdValidation:
    def test_valid_event_ids(self):
        for event_id in ['EVT-REG', 'EVT-BAGLOAD', 'EVT-A1']:
            validate_event_id(event_id)

    def test_invalid_event_ids(self):
        for event_id in ['evt-reg', 'EVT-', 'EVT-BAG_LOAD', 'EVENT-1']:
            with pytest.raises(ValidationError):
                validate_event_id(event_id)


class TestActivityIdValidation:
    def test_valid_activity_ids(self):
        for activity_id in ['ACT-001', 'ACT-010', 'ACT-999']:
            validate_activity_id(activity_id)

    def test_invalid_activity_ids(self):
        for activity_id in ['ACT-1', 'act-001', 'ACT001']:
            with pytest.raises(ValidationError):
                validate_activity_id(activity_id)


class TestOccurrenceIdValidation:
    def test_valid_occurrence_ids(self):
        validate_occurrence_id('EVT-BAGLOAD#2026-02-12#1')

    def test_invalid_occurrence_ids(self):
        for occurrence_id in ['EVT-BAGLOAD#2026/02/12#1', 'EVT-BAGLOAD#2026-02-12#0', 'BAD#2026-02-12#1']:
            with pytest.raises(ValidationError):
                validate_occurrence_id(occurrence_id)


class TestHotelIdValidation:
    def test_valid_hotel_ids(self):
        for hotel_id in ['HTL-MDU-01', 'HTL-CHE-10']:
            validate_hotel_id(hotel_id)

    def test_invalid_hotel_ids(self):
        for hotel_id in ['HTL-MD-01', 'HTL-mdu-01', 'HOTEL-MDU-01']:
            with pytest.raises(ValidationError):
                validate_hotel_id(hotel_id)


class TestUploadIdValidation:
    def test_valid_upload_ids(self):
        validate_upload_id('UPL-000042')
        validate_upload_id('UPL-123456789012')

    def test_invalid_upload_ids(self):
        for upload_id in ['UPL-42', 'upload-000042', 'UPL000042']:
            with pytest.raises(ValidationError):
                validate_upload_id(upload_id)


class TestDateValidation:
    """Test date validation"""
    
    def test_valid_iso_dates(self):
        """Test valid ISO 8601 dates"""
        valid_dates = ['2026-02-10', '2025-12-31', '2024-01-01']
        for date_str in valid_dates:
            validate_iso_date(date_str)  # Should not raise
    
    def test_invalid_date_formats(self):
        """Test invalid date formats"""
        invalid_dates = ['2026/02/10', '02-10-2026', '2026-2-10', 'Feb 10 2026']
        for date_str in invalid_dates:
            with pytest.raises(ValidationError):
                validate_iso_date(date_str)


class TestEmailValidation:
    """Test email validation"""
    
    def test_valid_emails(self):
        """Test valid email addresses"""
        valid_emails = [
            'user@example.com',
            'test.user@example.com',
            'user+tag@example.co.uk'
        ]
        for email in valid_emails:
            validate_email(email)  # Should not raise
    
    def test_invalid_emails(self):
        """Test invalid email addresses"""
        invalid_emails = [
            'invalid',
            '@example.com',
            'user@',
            'user@.com',
            'user@example'
        ]
        for email in invalid_emails:
            with pytest.raises(ValidationError):
                validate_email(email)


class TestDatetimeValidation:
    """Test ISO 8601 datetime validation with UTC Z-suffix enforcement"""
    
    def test_valid_utc_datetimes(self):
        """Test valid UTC datetime strings with Z suffix"""
        valid = [
            '2026-02-11T10:30:00Z',
            '2026-02-11T10:30:00.123456Z',
            '2026-01-01T00:00:00Z',
            '2026-12-31T23:59:59Z'
        ]
        for dt in valid:
            validate_iso_datetime(dt)  # Should not raise
    
    def test_reject_non_utc_offsets(self):
        """Datetime with non-UTC offset should be rejected"""
        non_utc = [
            '2026-02-11T10:30:00+05:30',
            '2026-02-11T10:30:00+00:00',
            '2026-02-11T10:30:00-04:00'
        ]
        for dt in non_utc:
            with pytest.raises(ValidationError):
                validate_iso_datetime(dt)
    
    def test_reject_invalid_datetimes(self):
        """Invalid datetime strings should be rejected"""
        invalid = [
            'not-a-datetime',
            '2026-02-11',
            '10:30:00Z',
            '',
            '2026-13-01T00:00:00Z'
        ]
        for dt in invalid:
            with pytest.raises(ValidationError):
                validate_iso_datetime(dt)


class TestTimeValidation:
    """Test HH:MM time validation"""
    
    def test_valid_times(self):
        """Test valid HH:MM time strings"""
        valid = ['00:00', '06:30', '08:00', '12:00', '14:30', '23:59']
        for t in valid:
            validate_time_hhmm(t)  # Should not raise
    
    def test_invalid_times(self):
        """Test invalid time strings"""
        invalid = [
            '24:00',    # Hour too large
            '25:00',    # Hour out of range
            '12:60',    # Minute too large
            '99:99',    # Both out of range
            '8:00',     # Missing leading zero
            '08:0',     # Missing trailing digit
            'abc',      # Not a time
            '08:00:00', # Seconds not allowed
            '',         # Empty
        ]
        for t in invalid:
            with pytest.raises(ValidationError):
                validate_time_hhmm(t)


class TestRideSelfServiceStageValidation:
    def test_stage_self_service_flags_require_booleans(self):
        stages = [
            {'stageId': 'S000', 'stageNumber': 0, 'type': 'START', 'name': 'Start'},
            {'stageId': 'S001', 'stageNumber': 1, 'type': 'FINISH', 'name': 'Finish'},
        ]

        normalized = validate_ride_stages([
            {**stages[0], 'selfNotRidingAllowed': False, 'selfCheckInAllowed': True},
            {**stages[1], 'selfCheckInAllowed': False},
        ])
        assert normalized[0]['selfNotRidingAllowed'] is False
        assert normalized[0]['selfCheckInAllowed'] is True
        assert normalized[1]['selfCheckInAllowed'] is False

        with pytest.raises(ValidationError):
            validate_ride_stages([{**stages[0], 'selfNotRidingAllowed': None}, stages[1]])
        with pytest.raises(ValidationError):
            validate_ride_stages([stages[0], {**stages[1], 'selfCheckInAllowed': None}])

    def test_not_riding_setting_is_start_only(self):
        stages = [
            {'stageId': 'S000', 'stageNumber': 0, 'type': 'START', 'name': 'Start'},
            {'stageId': 'S001', 'stageNumber': 1, 'type': 'PIT_STOP', 'name': 'Pit stop'},
            {'stageId': 'S002', 'stageNumber': 2, 'type': 'FINISH', 'name': 'Finish'},
        ]

        with pytest.raises(ValidationError) as exc_info:
            validate_ride_stages([stages[0], {**stages[1], 'selfNotRidingAllowed': True}, stages[2]])
        assert exc_info.value.error_code == 'VALIDATION_ERROR'

    def test_stage_number_must_not_be_a_boolean(self):
        stages = [
            {'stageId': 'S000', 'stageNumber': 0, 'type': 'START', 'name': 'Start'},
            {'stageId': 'S001', 'stageNumber': True, 'type': 'PIT_STOP', 'name': 'Pit stop'},
            {'stageId': 'S002', 'stageNumber': 2, 'type': 'FINISH', 'name': 'Finish'},
        ]

        with pytest.raises(ValidationError):
            validate_ride_stages(stages)

    @pytest.mark.parametrize('stages', [
        [
            {'stageId': 'S000', 'stageNumber': 0, 'type': 'PIT_STOP', 'name': 'Pit stop'},
            {'stageId': 'S001', 'stageNumber': 1, 'type': 'FINISH', 'name': 'Finish'},
        ],
        [
            {'stageId': 'S000', 'stageNumber': 0, 'type': 'START', 'name': 'Start'},
            {'stageId': 'S001', 'stageNumber': 1, 'type': 'START', 'name': 'Second start'},
            {'stageId': 'S002', 'stageNumber': 2, 'type': 'FINISH', 'name': 'Finish'},
        ],
        [
            {'stageId': 'S000', 'stageNumber': 0, 'type': 'PIT_STOP', 'name': 'Pit stop'},
            {'stageId': 'S001', 'stageNumber': 1, 'type': 'START', 'name': 'Start'},
            {'stageId': 'S002', 'stageNumber': 2, 'type': 'FINISH', 'name': 'Finish'},
        ],
        [
            {'stageId': 'S000', 'stageNumber': 0, 'type': 'START', 'name': 'Start'},
            {'stageId': 'S001', 'stageNumber': 1, 'type': 'PIT_STOP', 'name': 'Pit stop'},
        ],
        [
            {'stageId': 'S000', 'stageNumber': 0, 'type': 'START', 'name': 'Start'},
            {'stageId': 'S001', 'stageNumber': 1, 'type': 'FINISH', 'name': 'Finish'},
            {'stageId': 'S002', 'stageNumber': 2, 'type': 'FINISH', 'name': 'Second finish'},
        ],
        [
            {'stageId': 'S000', 'stageNumber': 0, 'type': 'START', 'name': 'Start'},
            {'stageId': 'S001', 'stageNumber': 1, 'type': 'FINISH', 'name': 'Finish'},
            {'stageId': 'S002', 'stageNumber': 2, 'type': 'PIT_STOP', 'name': 'Pit stop'},
        ],
    ])
    def test_start_finish_layout_errors_have_specific_code(self, stages):
        with pytest.raises(ValidationError) as exc_info:
            validate_ride_stages(stages)
        assert exc_info.value.error_code == 'INVALID_STAGE_LAYOUT'
