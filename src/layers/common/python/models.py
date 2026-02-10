"""
Data models for tour-data-api

These models represent the data structures stored in DynamoDB
and returned by the API endpoints.
"""

from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum


# ============================================================================
# ENUMS
# ============================================================================

class TourStatus(str, Enum):
    """Tour status values"""
    PLANNING = "PLANNING"
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
# DATA CLASSES
# ============================================================================

@dataclass
class RiderProfile:
    """Rider profile data (master data, tour-agnostic)"""
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
        item['PK'] = f"PROFILE#{self.profile_id}"
        item['profileId'] = self.profile_id
        return item


@dataclass
class Tour:
    """Tour definition (yearly tour)"""
    tour_id: str
    year: int
    name: str
    start_date: str
    end_date: str
    status: TourStatus
    description: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data['status'] = self.status.value
        return data
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format"""
        item = self.to_dict()
        item['PK'] = f"TOUR#{self.year}"
        item['tourId'] = self.tour_id
        return item


@dataclass
class TourRider:
    """Rider registration for a specific tour"""
    tour_id: str
    rider_id: str
    profile_id: str
    qr_code_data: str
    status: TourRiderStatus
    registered_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data['status'] = self.status.value
        return data
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format"""
        item = self.to_dict()
        item['PK'] = f"TOUR#{self.tour_id}"
        item['SK'] = f"RIDER#{self.rider_id}"
        item['tourId'] = self.tour_id
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
    """Daily ride configuration"""
    ride_id: str
    tour_id: str
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
        item['PK'] = f"TOUR#{self.tour_id}"
        item['SK'] = f"RIDE#{self.ride_id}"
        item['rideId'] = self.ride_id
        item['tourId'] = self.tour_id
        return item


@dataclass
class CheckIn:
    """Check-in record for a rider at a stage"""
    check_in_id: str
    rider_id: str
    ride_id: str
    tour_id: str
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
        item['PK'] = f"RIDE#{self.ride_id}"
        item['SK'] = f"CHECKIN#{self.rider_id}#{self.stage_number:03d}#{self.timestamp}"
        item['checkInId'] = self.check_in_id
        item['tourIdRiderId'] = f"{self.tour_id}#{self.rider_id}"
        return item


@dataclass
class User:
    """User profile for Check-In App"""
    user_id: str
    tour_id: str
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
        item['PK'] = f"USER#{self.user_id}"
        item['SK'] = f"TOUR#{self.tour_id}"
        item['userId'] = self.user_id
        item['tourId'] = self.tour_id
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
        tour_id=item['tourId'],
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
