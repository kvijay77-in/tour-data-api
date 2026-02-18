"""
Unit tests for validation utilities
"""

import pytest
import sys
import os

# Add common layer to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'layers', 'common'))

from validation import (
    validate_rider_id,
    validate_tour_id,
    validate_ride_id,
    validate_stage_id,
    validate_iso_date,
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
            'TOUR2024', 'TOUR2025', 'India-Coast-2026',
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
        valid_ids = ['S001', 'S010', 'S100', 'S999']
        for stage_id in valid_ids:
            validate_stage_id(stage_id)  # Should not raise
    
    def test_invalid_stage_id_format(self):
        """Test invalid Stage ID formats"""
        invalid_ids = ['s001', 'S1', 'S01', 'STAGE001', 'S1000']
        for stage_id in invalid_ids:
            with pytest.raises(ValidationError):
                validate_stage_id(stage_id)


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
