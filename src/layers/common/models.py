"""
Data models for tour-data-api

These models represent the data structures stored in DynamoDB
and returned by the API endpoints.

Table Strategy (Hybrid):
- Shared tables (SAM-managed): RiderProfile, TourMaster
- Tour-specific tables (runtime-provisioned): TourRider-{tourId}, Ride-{tourId},
  CheckIn-{tourId}, User-{tourId}
"""

from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum


# ============================================================================
# ENUMS
# ============================================================================

class TourStatus(str, Enum):
    """Tour status values - flow: PLANNING -> PROVISIONING -> ACTIVE -> COMPLETED -> ARCHIVED"""
    PLANNING = "PLANNING"
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class RideStatus(str, Enum):
    """Ride status values"""
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"


class StageType(str, Enum):
    """Stage type values"""
    START = "START"
    PIT_STOP = "PIT_STOP"
    FINISH = "FINISH"


class CheckInMethod(str, Enum):
    """Check-in method values"""
    QR_SCAN = "QR_SCAN"
    MANUAL = "MANUAL"
    FALLBACK = "FALLBACK"


class CheckInStatus(str, Enum):
    """Check-in status values (derived)"""
    NOT_CHECKED_IN = "NOT_CHECKED_IN"
    CHECKED_IN = "CHECKED_IN"
    NOT_RIDING = "NOT_RIDING"
    QUIT_RIDING = "QUIT_RIDING"


class UserRole(str, Enum):
    """User role values"""
    ADMINISTRATOR = "ADMINISTRATOR"
    SUPER_USER = "SUPER_USER"
    PIT_STOP_CREW = "PIT_STOP_CREW"
    HOTEL_STAFF = "HOTEL_STAFF"
    GUEST = "GUEST"


class TourRiderStatus(str, Enum):
    """Tour rider registration status"""
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


# ============================================================================
# TOUR-SPECIFIC TABLE TYPES (for dynamic table name resolution)
# ============================================================================

TOUR_TABLE_TYPES = ['TourRider', 'Ride', 'CheckIn', 'User']


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class RiderProfile:
    """
    Rider profile data (master data, tour-agnostic)
    Stored in shared RiderProfile table.
    Partition key: profileId
    """
    profile_id: str
    name: str
    email: str
    phone: str
    emergency_contact_name: str
    emergency_contact_phone: str
    photo_s3_key: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format"""
        item = self.to_dict()
        item['profileId'] = self.profile_id
        return item


@dataclass
class Tour:
    """
    Tour definition (shared TourMaster table).
    Partition key: tourId
    tourId is free-form (e.g., TOT-2026, TDF2026)
    """
    tour_id: str
    name: str
    start_date: str
    end_date: str
    status: TourStatus
    description: Optional[str] = None
    provisioned_at: Optional[str] = None
    archived_at: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data['status'] = self.status.value
        return {k: v for k, v in data.items() if v is not None}
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format"""
        item = self.to_dict()
        item['tourId'] = self.tour_id
        return item


@dataclass
class TourRider:
    """
    Rider registration for a specific tour.
    Stored in tour-specific TourRider-{tourId} table.
    Partition key: riderId
    """
    rider_id: str
    profile_id: str
    status: TourRiderStatus
    qr_code_data: Optional[str] = None
    registered_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data['status'] = self.status.value
        return {k: v for k, v in data.items() if v is not None}
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format"""
        item = self.to_dict()
        item['riderId'] = self.rider_id
        item['profileId'] = self.profile_id
        return item


@dataclass
class Stage:
    """Stage information within a ride"""
    stage_id: str
    stage_number: int
    type: StageType
    name: str
    location: Optional[str] = None
    distance_from_start: Optional[float] = None
    estimated_time_from_start: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data['type'] = self.type.value
        return {k: v for k, v in data.items() if v is not None}


@dataclass
class Ride:
    """
    Daily ride configuration.
    Stored in tour-specific Ride-{tourId} table.
    Partition key: rideId
    """
    ride_id: str
    date: str
    ride_no: int
    name: str
    start_location: str
    finish_location: str
    total_distance: float
    flag_off_time: str
    status: RideStatus
    stages: List[Stage]
    description: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    closed_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data['status'] = self.status.value
        data['stages'] = [stage.to_dict() for stage in self.stages]
        return {k: v for k, v in data.items() if v is not None}
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format"""
        item = self.to_dict()
        item['rideId'] = self.ride_id
        return item


@dataclass
class CheckIn:
    """
    Check-in record for a rider at a stage.
    Stored in tour-specific CheckIn-{tourId} table.
    Partition key: rideId, Sort key: checkInId (<riderId>#<stageNumber>#<timestamp>)
    """
    check_in_id: str
    rider_id: str
    ride_id: str
    stage_number: int
    stage_id: str
    timestamp: str
    checked_in_by: str
    method: CheckInMethod
    is_not_riding: bool = False
    is_quit_riding: bool = False
    is_manual_entry: bool = False
    notes: Optional[str] = None
    location: Optional[Dict[str, float]] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def get_status(self) -> CheckInStatus:
        """Derive check-in status from flags"""
        if self.is_not_riding:
            return CheckInStatus.NOT_RIDING
        elif self.is_quit_riding:
            return CheckInStatus.QUIT_RIDING
        else:
            return CheckInStatus.CHECKED_IN
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data['method'] = self.method.value
        data['status'] = self.get_status().value
        return {k: v for k, v in data.items() if v is not None}
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format"""
        item = self.to_dict()
        item['rideId'] = self.ride_id
        item['checkInId'] = f"{self.rider_id}#{self.stage_number:03d}#{self.timestamp}"
        item['riderId'] = self.rider_id
        return item


@dataclass
class User:
    """
    User profile for Check-In App.
    Stored in tour-specific User-{tourId} table.
    Partition key: userId
    """
    user_id: str
    username: str
    email: str
    name: str
    role: UserRole
    status: str = "ACTIVE"
    assigned_stage: Optional[int] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data['role'] = self.role.value
        return {k: v for k, v in data.items() if v is not None}
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format"""
        item = self.to_dict()
        item['userId'] = self.user_id
        return item


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_stage_from_dict(data: Dict[str, Any]) -> Stage:
    """Create Stage object from dictionary"""
    return Stage(
        stage_id=data['stageId'],
        stage_number=data['stageNumber'],
        type=StageType(data['type']),
        name=data['name'],
        location=data.get('location'),
        distance_from_start=data.get('distanceFromStart'),
        estimated_time_from_start=data.get('estimatedTimeFromStart')
    )


def create_ride_from_dynamodb_item(item: Dict[str, Any]) -> Ride:
    """Create Ride object from DynamoDB item"""
    stages = [create_stage_from_dict(stage) for stage in item.get('stages', [])]
    
    return Ride(
        ride_id=item['rideId'],
        date=item['date'],
        ride_no=item['rideNo'],
        name=item['name'],
        start_location=item['startLocation'],
        finish_location=item['finishLocation'],
        total_distance=item['totalDistance'],
        flag_off_time=item['flagOffTime'],
        status=RideStatus(item['status']),
        stages=stages,
        description=item.get('description'),
        created_at=item.get('createdAt', ''),
        updated_at=item.get('updatedAt', ''),
        started_at=item.get('startedAt'),
        completed_at=item.get('completedAt'),
        closed_at=item.get('closedAt')
    )
