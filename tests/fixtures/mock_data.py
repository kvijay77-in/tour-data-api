"""
Mock fixtures and test data for unit testing

This module provides mock data and fixtures for testing Lambda functions
without AWS connectivity. Use with pytest and moto for mocking AWS services.
"""

from typing import Dict, Any, List
from models import TourStatus, RideStatus, CheckInMethod


# Mock data fixtures
MOCK_TOURS = [
    {
        'PK': 'TOUR#001',
        'tourId': 'TOUR#001',
        'tourName': 'Mock Tour 2026',
        'status': TourStatus.ACTIVE.value,
        'startDate': '2026-02-10',
        'endDate': '2026-02-17',
        'totalRides': 7,
        'totalRiders': 100,
        'description': 'Mock cycling tour for testing'
    }
]

MOCK_RIDERS = [
    {
        'PK': 'RIDER#R001',
        'riderId': 'R001',
        'profileId': 'PROFILE#P001',
        'firstName': 'John',
        'lastName': 'Doe',
        'email': 'john.doe@example.com',
        'phoneNumber': '+1234567890',
        'emergencyContact': 'Jane Doe: +0987654321'
    },
    {
        'PK': 'RIDER#R002',
        'riderId': 'R002',
        'profileId': 'PROFILE#P002',
        'firstName': 'Jane',
        'lastName': 'Smith',
        'email': 'jane.smith@example.com',
        'phoneNumber': '+1234567891',
        'emergencyContact': 'John Smith: +0987654322'
    }
]

MOCK_TOUR_RIDERS = [
    {
        'PK': 'TOUR#001',
        'SK': 'RIDER#R001',
        'tourId': 'TOUR#001',
        'riderId': 'R001',
        'profileId': 'PROFILE#P001',
        'bibNumber': '001',
        'groupNumber': '1',
        'registrationDate': '2026-01-15'
    },
    {
        'PK': 'TOUR#001',
        'SK': 'RIDER#R002',
        'tourId': 'TOUR#001',
        'riderId': 'R002',
        'profileId': 'PROFILE#P002',
        'bibNumber': '002',
        'groupNumber': '1',
        'registrationDate': '2026-01-16'
    }
]

MOCK_RIDES = [
    {
        'PK': 'TOUR#001',
        'SK': 'RIDE#001',
        'tourId': 'TOUR#001',
        'rideId': 'RIDE#001',
        'rideNumber': 1,
        'date': '2026-02-11',
        'startPoint': 'City A',
        'endPoint': 'City B',
        'distance': 120.5,
        'status': RideStatus.ACTIVE.value,
        'stages': 3
    }
]

MOCK_CHECKINS = [
    {
        'PK': 'RIDE#001',
        'SK': '2026-02-11T10:30:00#R001',
        'rideId': 'RIDE#001',
        'riderId': 'R001',
        'tourId': 'TOUR#001',
        'notRiding': None,  # Normal check-in
        'quitRiding': None,  # Normal check-in
        'stageNumber': 1,
        'timestamp': '2026-02-11T10:30:00Z',
        'method': CheckInMethod.QR_SCAN.value
    }
]

MOCK_USERS = [
    {
        'PK': 'USER#admin@example.com',
        'SK': 'TOUR#001',
        'userId': 'USER#admin',
        'email': 'admin@example.com',
        'name': 'Admin User',
        'role': 'ADMIN',
        'tourId': 'TOUR#001'
    }
]


def get_mock_data(table_type: str) -> List[Dict[str, Any]]:
    """
    Get mock data for a specific table type
    
    Args:
        table_type: Type of table (TOUR, RIDER, TOUR_RIDER, RIDE, CHECKIN, USER)
    
    Returns:
        List of mock items for the table
    """
    mock_data_map = {
        'TOUR': MOCK_TOURS,
        'RIDER': MOCK_RIDERS,
        'TOUR_RIDER': MOCK_TOUR_RIDERS,
        'RIDE': MOCK_RIDES,
        'CHECKIN': MOCK_CHECKINS,
        'USER': MOCK_USERS
    }
    
    return mock_data_map.get(table_type, [])
