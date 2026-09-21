"""
Data models for tour-data-api

These models represent the data structures stored in DynamoDB
and returned by the API endpoints.

Table Strategy (Hybrid):
- Shared tables (SAM-managed): RiderProfile, RiderCognitoUser, TourMaster
- Tour-specific tables (runtime-provisioned): TourRider-{tourId}, Ride-{tourId},
    CheckIn-{tourId}, User-{tourId}, Notification-{tourId}, Artifacts-{tourId}
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
    FLOAT = "FLOAT"
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
    EXITED = "EXITED"


class NotificationType(str, Enum):
    """Notification type values"""
    TOUR_ANNOUNCEMENT = "TOUR_ANNOUNCEMENT"
    RIDE_UPDATE = "RIDE_UPDATE"
    SAFETY_ALERT = "SAFETY_ALERT"
    PERSONAL_MESSAGE = "PERSONAL_MESSAGE"
    CHECKIN_REMINDER = "CHECKIN_REMINDER"
    REGISTRATION_STATUS = "REGISTRATION_STATUS"


class RiderGender(str, Enum):
    """Supported rider gender values"""
    MALE = "Male"
    FEMALE = "Female"
    OTHER = "Other"
    PREFER_NOT_TO_SAY = "Prefer not to say"


class ArtifactCategory(str, Enum):
    """Artifact category scope values."""
    TOUR = "tour"
    RIDE = "ride"


class DietaryPreference(str, Enum):
    """Supported rider dietary preferences."""
    VEG = "VEG"
    NON_VEG = "NON_VEG"


class BaggageStatus(str, Enum):
    """Tour rider baggage custody status."""
    ACTIVE = "ACTIVE"
    RETAINED = "RETAINED"
    WITH_RIDER = "WITH_RIDER"


class EventType(str, Enum):
    """Event repetition type values."""
    SINGLE = "SINGLE"
    REPEATING = "REPEATING"


class EventOccurrenceStatus(str, Enum):
    """Event occurrence lifecycle states."""
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EventRecordOutcome(str, Enum):
    """Event activity record outcomes."""
    COMPLETED = "COMPLETED"
    OPTED_OUT = "OPTED_OUT"
    FLAGGED = "FLAGGED"


# ============================================================================
# TOUR-SPECIFIC TABLE TYPES (for dynamic table name resolution)
# ============================================================================

TOUR_TABLE_TYPES = [
    'TourRider',
    'Ride',
    'CheckIn',
    'User',
    'Notification',
    'Artifacts',
    'Event',
    'EventOccurrence',
    'EventActivityLogs',
    'Hotel',
    'RoomAllocation',
]


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
    emergencyContact: Dict[str, str]
    address: Optional[Dict[str, str]] = None
    dateOfBirth: Optional[str] = None
    gender: Optional[str] = None
    dietaryPreference: Optional[str] = None
    personalCode: Optional[str] = None
    photoS3Key: Optional[str] = None
    createdAt: str = field(default_factory=utc_now_iso)
    updatedAt: str = field(default_factory=utc_now_iso)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary with normalized optional personalCode."""
        data = asdict(self)
        personal_code = data.get('personalCode')
        if isinstance(personal_code, str):
            normalized_personal_code = personal_code.strip().upper()
            data['personalCode'] = normalized_personal_code if normalized_personal_code else None
        return {k: v for k, v in data.items() if v is not None}
    
    def to_dynamodb_item(self) -> Dict[str, Any]:
        """Convert to DynamoDB item format"""
        return self.to_dict()


@dataclass
class RiderCognitoUser:
    """
    Cognito username to rider profile mapping.
    Stored in shared RiderCognitoUser table.
    Partition key: cognitoUserName
    """
    cognitoUserName: str
    profileId: str

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
    rideCount: int
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
    prevStatus: Optional[str] = None
    exitedAt: Optional[str] = None
    exitedBy: Optional[str] = None
    baggageStatus: str = BaggageStatus.ACTIVE.value
    baggageExitedAt: Optional[str] = None
    baggageExitedBy: Optional[str] = None
    baggageReleasedAt: Optional[str] = None
    baggageReleasedBy: Optional[str] = None
    baggageExitNote: Optional[str] = None
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
class RideFloat:
    """Float vehicle/stage mapping within a ride."""
    floatNo: int
    floatToStage: int

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return asdict(self)


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
    floats: Optional[List[RideFloat]] = None
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
        if self.floats is not None:
            data['floats'] = [ride_float.to_dict() for ride_float in self.floats]
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
    isFloat: bool = False
    floatNo: Optional[int] = None
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
        elif self.isFloat:
            return CheckInStatus.FLOAT
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
            'isFloat': self.isFloat,
            'floatNo': self.floatNo,
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
    hotelId: Optional[str] = None
    eventAssignments: Optional[List[Dict[str, Any]]] = None
    assignedActivityIds: Optional[List[str]] = None
    createdBy: Optional[str] = None
    createdAt: str = field(default_factory=utc_now_iso)
    updatedBy: Optional[str] = None
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


@dataclass
class ActivityDefinition:
    """Embedded activity configuration for an event definition."""
    activityId: str
    name: str
    sequenceNo: int
    enabled: bool = True
    mandatory: bool = False
    allowedTypeCodes: List[str] = field(default_factory=list)
    allowOptOut: bool = False
    prerequisiteActivityIds: List[str] = field(default_factory=list)
    restrictToAssignedUsers: bool = True
    variantOptions: List[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EventDefinition:
    """Event definition item stored in Event-{tourId}."""
    eventId: str
    eventName: str
    eventType: EventType
    location: str
    sequenceEnforced: bool
    defaultAllowedTypeCodes: List[str]
    allowSelfService: bool = False
    activities: List[ActivityDefinition] = field(default_factory=list)
    createdAt: str = field(default_factory=utc_now_iso)
    updatedAt: str = field(default_factory=utc_now_iso)
    updatedBy: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['eventType'] = self.eventType.value
        data['activities'] = [activity.to_dict() for activity in self.activities]
        return {k: v for k, v in data.items() if v is not None}


@dataclass
class ActivityOverride:
    """Per-activity occurrence override."""
    activityId: str
    enabled: Optional[bool] = None
    selfServiceEnabled: Optional[bool] = None
    allowedTypeCodes: Optional[List[str]] = None
    note: Optional[str] = None
    updatedAt: Optional[str] = None
    updatedBy: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class EventOccurrence:
    """Concrete event occurrence item."""
    eventId: str
    dateSeq: str
    occurrenceId: str
    date: str
    seq: int
    status: EventOccurrenceStatus = EventOccurrenceStatus.PLANNED
    activityOverrides: List[ActivityOverride] = field(default_factory=list)
    selfServiceEnabled: bool = False
    linkedOccurrenceRef: Optional[str] = None
    restrictToAssignedUsers: bool = True
    startedAt: Optional[str] = None
    completedAt: Optional[str] = None
    cancelledAt: Optional[str] = None
    cancelledBy: Optional[str] = None
    cancelReason: Optional[str] = None
    createdAt: str = field(default_factory=utc_now_iso)
    updatedAt: str = field(default_factory=utc_now_iso)
    updatedBy: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['status'] = self.status.value
        data['activityOverrides'] = [override.to_dict() for override in self.activityOverrides]
        return {k: v for k, v in data.items() if v is not None}


@dataclass
class EventActivityRecord:
    """Activity completion/scan record item."""
    occurrenceId: str
    recordId: str
    eventId: str
    activityId: str
    activityName: str
    riderId: str
    scannedBy: str
    timestamp: str
    method: str
    outcome: EventRecordOutcome = EventRecordOutcome.COMPLETED
    typeCode: Optional[str] = None
    bagLabel: Optional[str] = None
    variantSelected: Optional[str] = None
    hotelId: Optional[str] = None
    syncedAt: Optional[str] = None
    isFlagged: bool = False
    flagReason: Optional[str] = None
    cancelledAt: Optional[str] = None
    cancelledBy: Optional[str] = None
    cancelReason: Optional[str] = None
    createdAt: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['outcome'] = self.outcome.value
        return {k: v for k, v in data.items() if v is not None}


@dataclass
class Hotel:
    """Hotel master item."""
    hotelId: str
    name: str
    city: str
    address: str
    contact: Optional[str] = None
    notes: Optional[str] = None
    createdAt: str = field(default_factory=utc_now_iso)
    updatedAt: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class RoomAllocation:
    """Per-rider per-night hotel allocation item."""
    stayDate: str
    riderId: str
    hotelId: str
    roomNo: str
    roomCapacity: int = 2
    sharingWith: List[str] = field(default_factory=list)
    source: str = "MANUAL"
    checkInDate: Optional[str] = None
    checkOutDate: Optional[str] = None
    uploadId: Optional[str] = None
    createdAt: str = field(default_factory=utc_now_iso)
    updatedAt: str = field(default_factory=utc_now_iso)
    updatedBy: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


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


def create_ride_float_from_dict(data: Dict[str, Any]) -> RideFloat:
    """Create RideFloat object from dictionary"""
    return RideFloat(
        floatNo=data['floatNo'],
        floatToStage=data['floatToStage']
    )


def create_ride_from_dynamodb_item(item: Dict[str, Any]) -> Ride:
    """Create Ride object from DynamoDB item"""
    stages = [create_stage_from_dict(stage) for stage in item.get('stages', [])]
    floats = [create_ride_float_from_dict(ride_float) for ride_float in item.get('floats', [])]
    
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
        floats=floats or None,
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
