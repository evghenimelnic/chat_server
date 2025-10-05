from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class Location(BaseModel):
    """Geographic location with optional name."""

    name: Optional[str] = Field(default=None, description="Display name of the location")
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    radius_km: Optional[float] = Field(default=None, gt=0)


class RoomCreate(BaseModel):
    """Schema for creating a chat room."""

    name: str
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    topic: Optional[str] = None
    location: Optional[Location] = None
    event_time: Optional[datetime] = None


class RoomOut(RoomCreate):
    """Room representation returned to the client."""

    id: str


class RoomFilter(BaseModel):
    """Filters for querying rooms."""

    tags: List[str] = Field(default_factory=list)
    topic: Optional[str] = None
    q: Optional[str] = None
    near: Optional[Location] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class MessageIn(BaseModel):
    """Incoming chat message payload."""

    user_id: str
    content: str
    location: Optional[Location] = None
    event_time: Optional[datetime] = None


class MessageOut(MessageIn):
    """Message returned to clients."""

    id: str
    scope: str
    room_id: Optional[str] = None
    chat_id: Optional[str] = None
    created_at: datetime


class SubscriptionIn(BaseModel):
    """Subscription filter for notifications."""

    user_id: str
    scope: str = Field(default="any", description="any/common/room/p2p")
    what: List[str] = Field(default_factory=list, description="Keywords to monitor")
    where: Optional[Location] = None
    when_start: Optional[datetime] = None
    when_end: Optional[datetime] = None
    room_id: Optional[str] = None
    chat_id: Optional[str] = None


class SubscriptionOut(SubscriptionIn):
    """Subscription with identifier."""

    id: str


class P2PSessionCreate(BaseModel):
    """Payload for creating a P2P session."""

    participants: List[str] = Field(..., min_length=2, max_length=10)
    topic: Optional[str] = None
    expires_at: Optional[datetime] = None


class P2PSessionOut(P2PSessionCreate):
    """P2P session with identifier."""

    id: str
    created_at: datetime


class HistoryQuery(BaseModel):
    """Query params for history requests."""

    limit: int = 50
    before: Optional[datetime] = None
