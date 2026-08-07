"""
Mock fixtures and test data for unit testing

This module provides mock data and fixtures for testing Lambda functions
without AWS connectivity. Use with pytest and moto for mocking AWS services.

Table Strategy (Hybrid):
- Shared tables: TourMaster, RiderProfile (resolved via env var)
- Tour-specific tables: TourRider-{tourId}, Ride-{tourId}, CheckIn-{tourId}, User-{tourId}
"""

from typing import Dict, Any, List
from models import TourStatus, RideStatus, CheckInMethod, TourRiderStatus, UserRole


MOCK_TOUR_ID = 'TestTour-2026'

# Shared TourMaster table data
MOCK_TOURS = [
    {
        'tourId': MOCK_TOUR_ID,
        'name': 'Test Cycling Tour 2026',
        'status': TourStatus.ACTIVE.value,
        'startDate': '2026-02-10',
        'endDate': '2026-02-17',
        'description': 'Mock cycling tour for testing',
        'provisionedAt': '2026-01-01T00:00:00Z',
        'createdAt': '2026-01-01T00:00:00Z',
        'updatedAt': '2026-01-01T00:00:00Z'
    }
]

# Shared RiderProfile table data
MOCK_RIDER_PROFILES = [
    {
        'profileId': 'P001',
        'name': 'John Doe',
        'email': 'john.doe@example.com',
        'personalCode': 'D220',
        'phone': '+1234567890',
        'emergencyContact': {
            'name': 'Jane Doe',
            'phone': '+0987654321',
            'relation': 'Spouse'
        },
        'address': {
            'line1': '10 Beach Road',
            'line2': 'Apt 2A',
            'city': 'Chennai',
            'state': 'Tamil Nadu',
            'country': 'India',
            'postalCode': '600001'
        },
        'dateOfBirth': '1990-01-15',
        'gender': 'Male',
        'createdAt': '2026-01-01T00:00:00Z',
        'updatedAt': '2026-01-01T00:00:00Z'
    },
    {
        'profileId': 'P002',
        'name': 'Jane Smith',
        'email': 'jane.smith@example.com',
        'personalCode': 'E221',
        'phone': '+1234567891',
        'emergencyContact': {
            'name': 'John Smith',
            'phone': '+0987654322',
            'relation': 'Sibling'
        },
        'createdAt': '2026-01-01T00:00:00Z',
        'updatedAt': '2026-01-01T00:00:00Z'
    }
]

# Tour-specific TourRider-{tourId} table data
MOCK_TOUR_RIDERS = [
    {
        'riderId': 'R1',
        'profileId': 'P001',
        'status': TourRiderStatus.ACTIVE.value,
        'registeredAt': '2026-01-15T00:00:00Z',
        'createdAt': '2026-01-15T00:00:00Z',
        'updatedAt': '2026-01-15T00:00:00Z'
    },
    {
        'riderId': 'R2',
        'profileId': 'P002',
        'status': TourRiderStatus.ACTIVE.value,
        'registeredAt': '2026-01-16T00:00:00Z',
        'createdAt': '2026-01-16T00:00:00Z',
        'updatedAt': '2026-01-16T00:00:00Z'
    }
]

# Tour-specific Ride-{tourId} table data
MOCK_RIDES = [
    {
        'rideId': 'RIDE001',
        'rideNo': 1,
        'date': '2026-02-11',
        'name': 'City A to City B',
        'startLocation': 'City A',
        'finishLocation': 'City B',
        'totalDistance': 120.5,
        'flagOffTime': '08:00',
        'openTime': '08:00',
        'closeTime': '13:15',
        'floats': [
            {
                'floatNo': 1,
                'floatToStage': 1,
            }
        ],
        'status': RideStatus.ACTIVE.value,
        'stages': [
            {
                'stageId': 'S000',
                'stageNumber': 0,
                'type': 'START',
                'name': 'Start Point'
            },
            {
                'stageId': 'S001',
                'stageNumber': 1,
                'type': 'PIT_STOP',
                'name': 'Pit Stop 1',
                'estimatedOpenTime': 90,
                'pitStopDuration': 45
            },
            {
                'stageId': 'S002',
                'stageNumber': 2,
                'type': 'FINISH',
                'name': 'Finish Line'
            }
        ],
        'createdAt': '2026-02-01T00:00:00Z',
        'updatedAt': '2026-02-01T00:00:00Z'
    }
]

# Tour-specific CheckIn-{tourId} table data (rideId + checkInId)
MOCK_CHECKINS = [
    {
        'rideId': 'RIDE001',
        'checkInId': 'R1#000#2026-02-11T10:30:00Z',
        'riderId': 'R1',
        'stageNumber': 0,
        'stageId': 'S000',
        'timestamp': '2026-02-11T10:30:00Z',
        'checkedInBy': 'system',
        'method': CheckInMethod.QR_SCAN.value,
        'isNotRiding': False,
        'isQuitRiding': False,
        'isManualEntry': False,
        'status': 'CHECKED_IN',
        'createdAt': '2026-02-11T10:30:00Z'
    }
]

# Tour-specific User-{tourId} table data
MOCK_USERS = [
    {
        'userId': 'admin-001',
        'username': 'admin',
        'email': 'admin@example.com',
        'name': 'Admin User',
        'role': UserRole.ADMINISTRATOR.value,
        'status': 'ACTIVE',
        'createdAt': '2026-01-01T00:00:00Z',
        'updatedAt': '2026-01-01T00:00:00Z'
    }
]


def get_mock_data(table_type: str) -> List[Dict[str, Any]]:
    """
    Get mock data for a specific table type
    
    Args:
        table_type: Type of table (TOUR, RIDER_PROFILE, TOUR_RIDER, RIDE, CHECKIN, USER)
    
    Returns:
        List of mock items for the table
    """
    mock_data_map = {
        'TOUR': MOCK_TOURS,
        'RIDER_PROFILE': MOCK_RIDER_PROFILES,
        'TOUR_RIDER': MOCK_TOUR_RIDERS,
        'RIDE': MOCK_RIDES,
        'CHECKIN': MOCK_CHECKINS,
        'USER': MOCK_USERS
    }
    
    return mock_data_map.get(table_type, [])
