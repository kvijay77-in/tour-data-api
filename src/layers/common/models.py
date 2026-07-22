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
from datetime import datetime, timezone
from enum import Enum


def utc_now_iso() -> str:
    """Return current UTC time as ISO 8601 string with Z suffix.
    
    Uses timezone-aware datetime.now(timezone.utc) instead of the
    deprecated datetime.utcnow().
    
    Returns:
        Whole-second UTC timestamp, e.g. '2026-03-01T17:00:00Z'
    """
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def utc_today_iso() -> str:
    """Return current UTC date as ISO 8601 string (YYYY-MM-DD).
    
    Uses timezone-aware datetime to guarantee UTC date regardless of
    server locale.
    
    Returns:
        UTC date string, e.g. '2026-03-01'
    """
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


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
    OPEN = "OPEN"
    STARTED = "STARTED"
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"


class StageType(str, Enum):
    """Stage type values"""
    START = "START"
    PIT_STOP = "PIT_STOP"
    FINISH = "FINISH"


class PitStopStatus(str, Enum):
    """Pit stop status values"""
    OPEN = "OPEN"
    CLOSED = "CLOSED"


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
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    """User role values"""
    ADMINISTRATOR = "ADMINISTRATOR"
    SUPER_USER = "SUPER_USER"
    HOTEL_STAFF = "HOTEL_STAFF"
    GUEST = "GUEST"
    RIDER = "RIDER"


class TourRiderStatus(str, Enum):
    """Tour rider registration status"""
    PENDING = "PENDING"
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class NotificationType(str, Enum):
    """Notification type values"""
    TOUR_ANNOUNCEMENT = "TOUR_ANNOUNCEMENT"
    RIDE_UPDATE = "RIDE_UPDATE"
    SAFETY_ALERT = "SAFETY_ALERT"
    PERSONAL_MESSAGE = "PERSONAL_MESSAGE"
    CHECKIN_REMINDER = "CHECKIN_REMINDER"
    REGISTRATION_STATUS = "REGISTRATION_STATUS"


# ============================================================================
# TOUR-SPECIFIC TABLE TYPES (for dynamic table name resolution)
# ============================================================================

TOUR_TABLE_TYPES = ['TourRider', 'Ride', 'CheckIn', 'User', 'Notification']


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
    profileId: str
    name: str
    email: str
    phone: str
    emergencyContactName: str
    emergencyContactPhone: str
    photoS3Key: Optional[str] = None
    createdAt: str = field(default_factory=utc_now_iso)
    updatedAt: str = field(default_factory=utc_now_iso)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format"""
        return self.to_dict()


@dataclass
class Tour:
    """
    Tour definition (shared TourMaster table).
    Partition key: tourId
    tourId is free-form (e.g., TOT-2026, TDF2026)
    """
    tourId: str
    name: str
    startDate: str
    endDate: str
    status: TourStatus
    description: Optional[str] = None
    provisionedAt: Optional[str] = None
    archivedAt: Optional[str] = None
    createdAt: str = field(default_factory=utc_now_iso)
    updatedAt: str = field(default_factory=utc_now_iso)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data['status'] = self.status.value
        return {k: v for k, v in data.items() if v is not None}
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format"""
        return self.to_dict()


@dataclass
class TourRider:
    """
    Rider registration for a specific tour.
    Stored in tour-specific TourRider-{tourId} table.
    Partition key: riderId
    """
    riderId: str
    profileId: str
    status: TourRiderStatus
    qrCodeData: Optional[str] = None
    registeredAt: str = field(default_factory=utc_now_iso)
    createdAt: str = field(default_factory=utc_now_iso)
    updatedAt: str = field(default_factory=utc_now_iso)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data['status'] = self.status.value
        return {k: v for k, v in data.items() if v is not None}
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format"""
        return self.to_dict()


@dataclass
class Stage:
    """Stage information within a ride"""
    stageId: str
    stageNumber: int
    type: StageType
    name: str
    location: Optional[str] = None
    distanceFromStart: Optional[float] = None
    estimatedOpenTime: Optional[int] = None
    pitStopDuration: Optional[int] = None
    pitStopStatus: Optional[PitStopStatus] = None
    openedAt: Optional[str] = None
    closedAt: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data['type'] = self.type.value
        if self.pitStopStatus is not None:
            data['pitStopStatus'] = self.pitStopStatus.value
        return {k: v for k, v in data.items() if v is not None}


@dataclass
class Ride:
    """
    Daily ride configuration.
    Stored in tour-specific Ride-{tourId} table.
    Partition key: rideId
    """
    rideId: str
    date: str
    rideNo: int
    name: str
    startLocation: str
    finishLocation: str
    totalDistance: float
    flagOffTime: str
    status: RideStatus
    stages: List[Stage]
    openTime: Optional[str] = None
    closeTime: Optional[str] = None
    description: Optional[str] = None
    createdAt: str = field(default_factory=utc_now_iso)
    updatedAt: str = field(default_factory=utc_now_iso)
    startedAt: Optional[str] = None
    openedAt: Optional[str] = None
    completedAt: Optional[str] = None
    closedAt: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data['status'] = self.status.value
        data['stages'] = [stage.to_dict() for stage in self.stages]
        return {k: v for k, v in data.items() if v is not None}
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format"""
        return self.to_dict()


@dataclass
class CheckIn:
    """
    Check-in record for a rider at a stage.
    Stored in tour-specific CheckIn-{tourId} table.
    Partition key: rideId, Sort key: checkInId (<riderId>#<stageNumber>#<timestamp>)
    """
    checkInId: str
    riderId: str
    rideId: str
    timestamp: str
    checkedInBy: str
    method: CheckInMethod
    stageNumber: Optional[int] = None
    stageId: Optional[str] = None
    isNotRiding: bool = False
    isQuitRiding: bool = False
    isManualEntry: bool = False
    notes: Optional[str] = None
    location: Optional[Dict[str, float]] = None
    prevStatus: Optional[str] = None
    cancelledBy: Optional[str] = None
    cancelledAt: Optional[str] = None
    createdAt: str = field(default_factory=utc_now_iso)

    def _composite_checkin_id(self) -> str:
        """Build the stable sort key format used in CheckIn DynamoDB table."""
        stage_for_key = self.stageNumber if self.stageNumber is not None else 0
        return f"{self.riderId}#{stage_for_key:03d}#{self.timestamp}"
    
    def get_status(self) -> CheckInStatus:
        """Derive check-in status from flags"""
        if self.cancelledAt is not None:
            return CheckInStatus.CANCELLED
        if self.isNotRiding:
            return CheckInStatus.NOT_RIDING
        elif self.isQuitRiding:
            return CheckInStatus.QUIT_RIDING
        else:
            return CheckInStatus.CHECKED_IN
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to API/DynamoDB dictionary using camelCase attributes."""
        data = {
            'checkInId': self._composite_checkin_id(),
            'riderId': self.riderId,
            'rideId': self.rideId,
            'timestamp': self.timestamp,
            'checkedInBy': self.checkedInBy,
            'method': self.method.value,
            'isNotRiding': self.isNotRiding,
            'isQuitRiding': self.isQuitRiding,
            'isManualEntry': self.isManualEntry,
            'createdAt': self.createdAt,
            'status': self.get_status().value,
            'stageNumber': self.stageNumber,
            'stageId': self.stageId,
            'notes': self.notes,
            'location': self.location,
            'prevStatus': self.prevStatus,
            'cancelledBy': self.cancelledBy,
            'cancelledAt': self.cancelledAt,
        }
        return {k: v for k, v in data.items() if v is not None}
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format"""
        return self.to_dict()


@dataclass
class User:
    """
    User profile for Check-In App.
    Stored in tour-specific User-{tourId} table.
    Partition key: userId
    """
    userId: str
    username: str
    email: str
    name: str
    role: str
    status: str = "ACTIVE"
    assignedStage: Optional[int] = None
    createdAt: str = field(default_factory=utc_now_iso)
    updatedAt: str = field(default_factory=utc_now_iso)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data['role'] = self.role.value if isinstance(self.role, UserRole) else self.role
        return {k: v for k, v in data.items() if v is not None}
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format"""
        return self.to_dict()


@dataclass
class Notification:
    """
    Notification record for tour riders.
    Stored in tour-specific Notification-{tourId} table.
    Partition key: notificationId
    """
    notificationId: str
    type: NotificationType
    title: str
    message: str
    createdBy: str
    targetRiderId: Optional[str] = None
    readBy: Optional[List[str]] = field(default_factory=list)
    createdAt: str = field(default_factory=utc_now_iso)
    expiresAt: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        data['type'] = self.type.value
        return {k: v for k, v in data.items() if v is not None}

    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format"""
        return self.to_dict()


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_stage_from_dict(data: Dict[str, Any]) -> Stage:
    """Create Stage object from dictionary"""
    return Stage(
        stageId=data['stageId'],
        stageNumber=data['stageNumber'],
        type=StageType(data['type']),
        name=data['name'],
        location=data.get('location'),
        distanceFromStart=data.get('distanceFromStart'),
        estimatedOpenTime=data.get('estimatedOpenTime'),
        pitStopDuration=data.get('pitStopDuration'),
        pitStopStatus=(
            PitStopStatus(data['pitStopStatus'])
            if data.get('pitStopStatus') is not None else None
        ),
        openedAt=data.get('openedAt'),
        closedAt=data.get('closedAt')
    )


def create_ride_from_dynamodb_item(item: Dict[str, Any]) -> Ride:
    """Create Ride object from DynamoDB item"""
    stages = [create_stage_from_dict(stage) for stage in item.get('stages', [])]
    
    return Ride(
        rideId=item['rideId'],
        date=item['date'],
        rideNo=item['rideNo'],
        name=item['name'],
        startLocation=item['startLocation'],
        finishLocation=item['finishLocation'],
        totalDistance=item['totalDistance'],
        flagOffTime=item['flagOffTime'],
        status=RideStatus(item['status']),
        stages=stages,
        openTime=item.get('openTime'),
        closeTime=item.get('closeTime'),
        description=item.get('description'),
        createdAt=item.get('createdAt', ''),
        updatedAt=item.get('updatedAt', ''),
        startedAt=item.get('startedAt'),
        openedAt=item.get('openedAt'),
        completedAt=item.get('completedAt'),
        closedAt=item.get('closedAt')
    )


def is_cancelled_checkin_item(item: Dict[str, Any]) -> bool:
    """Return True when a persisted check-in item represents a cancelled record."""
    status = item.get('status') or item.get('Status')
    if status == CheckInStatus.CANCELLED.value:
        return True

    cancelled_at = item.get('cancelledAt')
    if cancelled_at is None:
        cancelled_at = item.get('cancelled_at')

    return cancelled_at is not None
