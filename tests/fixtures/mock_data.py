"""
Mock fixtures and test data for unit testing

This module provides mock data and fixtures for testing Lambda functions
without AWS connectivity. Use with pytest and moto for mocking AWS services.

Table Strategy (Hybrid):
- Shared tables: Tour, RiderProfile (resolved via env var)
- Tour-specific tables: TourRider-{tourId}, Ride-{tourId}, CheckIn-{tourId}, User-{tourId}
"""

from typing import Dict, Any, List
from models import TourStatus, RideStatus, CheckInMethod, TourRiderStatus, UserRole


MOCK_TOUR_ID = 'TestTour-2026'

# Shared Tour table data
MOCK_TOURS = [
    {
        'PK': f'TOUR#{MOCK_TOUR_ID}',
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
        'PK': 'PROFILE#P001',
        'profileId': 'P001',
        'name': 'John Doe',
        'email': 'john.doe@example.com',
        'phone': '+1234567890',
        'emergencyContactName': 'Jane Doe',
        'emergencyContactPhone': '+0987654321',
        'createdAt': '2026-01-01T00:00:00Z',
        'updatedAt': '2026-01-01T00:00:00Z'
    },
    {
        'PK': 'PROFILE#P002',
        'profileId': 'P002',
        'name': 'Jane Smith',
        'email': 'jane.smith@example.com',
        'phone': '+1234567891',
        'emergencyContactName': 'John Smith',
        'emergencyContactPhone': '+0987654322',
        'createdAt': '2026-01-01T00:00:00Z',
        'updatedAt': '2026-01-01T00:00:00Z'
    }
]

# Tour-specific TourRider-{tourId} table data (PK only, no SK)
MOCK_TOUR_RIDERS = [
    {
        'PK': 'RIDER#R1',
        'riderId': 'R1',
        'profileId': 'P001',
        'status': TourRiderStatus.ACTIVE.value,
        'registeredAt': '2026-01-15T00:00:00Z',
        'createdAt': '2026-01-15T00:00:00Z',
        'updatedAt': '2026-01-15T00:00:00Z'
    },
    {
        'PK': 'RIDER#R2',
        'riderId': 'R2',
        'profileId': 'P002',
        'status': TourRiderStatus.ACTIVE.value,
        'registeredAt': '2026-01-16T00:00:00Z',
        'createdAt': '2026-01-16T00:00:00Z',
        'updatedAt': '2026-01-16T00:00:00Z'
    }
]

# Tour-specific Ride-{tourId} table data (PK only, no SK)
MOCK_RIDES = [
    {
        'PK': 'RIDE#RIDE001',
        'rideId': 'RIDE001',
        'rideNo': 1,
        'date': '2026-02-11',
        'name': 'City A to City B',
        'startLocation': 'City A',
        'finishLocation': 'City B',
        'totalDistance': 120.5,
        'flagOffTime': '08:00',
        'status': RideStatus.ACTIVE.value,
        'stages': [
            {
                'stageId': 'S001',
                'stageNumber': 1,
                'type': 'START',
                'name': 'Start Point'
            },
            {
                'stageId': 'S002',
                'stageNumber': 2,
                'type': 'PIT_STOP',
                'name': 'Pit Stop 1'
            },
            {
                'stageId': 'S003',
                'stageNumber': 3,
                'type': 'FINISH',
                'name': 'Finish Line'
            }
        ],
        'createdAt': '2026-02-01T00:00:00Z',
        'updatedAt': '2026-02-01T00:00:00Z'
    }
]

# Tour-specific CheckIn-{tourId} table data (PK + SK)
MOCK_CHECKINS = [
    {
        'PK': 'RIDE#RIDE001',
        'SK': 'CHECKIN#R1#001#2026-02-11T10:30:00Z',
        'checkInId': 'chk-001',
        'rideId': 'RIDE001',
        'riderId': 'R1',
        'stageNumber': 1,
        'stageId': 'S001',
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

# Tour-specific User-{tourId} table data (PK only, no SK)
MOCK_USERS = [
    {
        'PK': 'USER#admin-001',
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
