from __future__ import annotations

from datetime import datetime
import math
from typing import Any, Dict, List

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .chat import CommonChat, RoomManager
from .config import settings
from .database import connect as connect_db
from .database import disconnect as disconnect_db
from .database import get_collection
from .schemas import (
    MessageIn,
    MessageOut,
    P2PSessionCreate,
    P2PSessionOut,
    RoomCreate,
    RoomOut,
    SubscriptionIn,
    SubscriptionOut,
)
from .services.messages import fetch_history, store_message
from .services.subscriptions import create_subscription, find_matching_subscriptions, list_subscriptions
from .websocket_manager import (
    ConnectionManager,
    P2PConnectionManager,
    RoomConnectionManager,
    SubscriptionConnectionManager,
)

app = FastAPI(title="Async Chat Platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

common_chat = CommonChat(ConnectionManager())
room_manager = RoomManager(RoomConnectionManager())
common_manager = ConnectionManager()
room_manager = RoomConnectionManager()
p2p_manager = P2PConnectionManager()
subscription_manager = SubscriptionConnectionManager()


@app.on_event("startup")
async def on_startup() -> None:
    """Initialise database connection."""

    await connect_db()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Terminate database connection."""

    await disconnect_db()


@app.get("/")
async def root() -> FileResponse:
    """Serve the single-page React application."""

    return FileResponse("app/static/index.html")


@app.post("/rooms", response_model=RoomOut)
async def create_room(room: RoomCreate) -> RoomOut:
    """Create a chat room with extended metadata."""

    return await room_manager.create(room)
    rooms = get_collection("rooms")
    document = room.model_dump()
    document["tags"] = [tag.lower() for tag in document.get("tags", [])]
    result = await rooms.insert_one(document)
    return RoomOut(id=str(result.inserted_id), **room.model_dump())


@app.get("/rooms", response_model=List[RoomOut])
async def list_rooms(
    tags: List[str] = Query(default_factory=list),
    topic: str | None = None,
    q: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> List[RoomOut]:
    """Return rooms filtered by tags, location, or time."""

    return await room_manager.list(
        tags=tags,
        topic=topic,
        q=q,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        start_time=start_time,
        end_time=end_time,
    )
    rooms = get_collection("rooms")
    query: Dict[str, Any] = {}
    if tags:
        query["tags"] = {"$all": [tag.lower() for tag in tags]}
    if topic:
        query["topic"] = topic
    text_filters: List[Dict[str, Any]] = []
    if q:
        text_filters.append({"$text": {"$search": q}})
    if latitude is not None and longitude is not None and radius_km is not None:
        # This is a simple bounding box filter for demo purposes.
        lat_delta = radius_km / 110.574
        lon_delta = radius_km / (111.320 * max(abs(math.cos(math.radians(latitude))), 0.0001))
        text_filters.append(
            {
                "location.latitude": {"$gte": latitude - lat_delta, "$lte": latitude + lat_delta},
                "location.longitude": {"$gte": longitude - lon_delta, "$lte": longitude + lon_delta},
            }
        )
    if start_time or end_time:
        time_query: Dict[str, Any] = {}
        if start_time:
            time_query["$gte"] = start_time
        if end_time:
            time_query["$lte"] = end_time
        query["event_time"] = time_query

    if text_filters:
        query["$and"] = text_filters if query else text_filters

    cursor = rooms.find(query)
    response: List[RoomOut] = []
    async for document in cursor:
        document["id"] = str(document.pop("_id"))
        response.append(RoomOut(**document))
    return response


@app.get("/rooms/{room_id}/history", response_model=List[MessageOut])
async def room_history(room_id: str, limit: int = 50) -> List[MessageOut]:
    """Return history for a specific room."""

    return await room_manager.history(room_id=room_id, limit=limit)
    history = await fetch_history(scope="room", room_id=room_id, limit=limit)
    return [MessageOut(**item) for item in history]


@app.get("/common/history", response_model=List[MessageOut])
async def common_history(limit: int = 50) -> List[MessageOut]:
    """Return common chat history."""

    return await common_chat.history(limit=limit)
    history = await fetch_history(scope="common", limit=limit)
    return [MessageOut(**item) for item in history]


@app.get("/p2p/{session_id}/history", response_model=List[MessageOut])
async def p2p_history(session_id: str, limit: int = 50) -> List[MessageOut]:
    """Return history for a P2P session."""

    history = await fetch_history(scope="p2p", chat_id=session_id, limit=limit)
    return [MessageOut(**item) for item in history]


@app.post("/subscriptions", response_model=SubscriptionOut)
async def add_subscription(subscription: SubscriptionIn) -> SubscriptionOut:
    """Create a subscription for mention notifications."""

    document = await create_subscription(subscription.model_dump())
    return SubscriptionOut(**document)


@app.get("/subscriptions/{user_id}", response_model=List[SubscriptionOut])
async def get_subscriptions(user_id: str) -> List[SubscriptionOut]:
    """List subscriptions for a user."""

    subscriptions = await list_subscriptions(user_id)
    return [SubscriptionOut(**item) for item in subscriptions]


@app.post("/p2p/sessions", response_model=P2PSessionOut)
async def create_p2p_session(session: P2PSessionCreate) -> P2PSessionOut:
    """Create a P2P session document."""

    sessions = get_collection("p2p_sessions")
    document = session.model_dump()
    document["created_at"] = datetime.utcnow()
    result = await sessions.insert_one(document)
    document["id"] = str(result.inserted_id)
    return P2PSessionOut(**document)


async def _notify_subscribers(message: Dict[str, Any]) -> None:
    """Notify subscribers whose filters match the message."""

    matches = await find_matching_subscriptions(message)
    for subscription in matches:
        await subscription_manager.notify(
            subscription["user_id"],
            {
                "type": "subscription",
                "subscription": subscription,
                "message": message,
            },
        )


@app.websocket("/ws/common")
async def websocket_common(websocket: WebSocket) -> None:
    """Realtime endpoint for the common chat."""

    await common_chat.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            stored = await common_chat.handle_incoming(data)
            await _notify_subscribers(stored)
    except WebSocketDisconnect:
        common_chat.disconnect(websocket)
    await common_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            message = MessageIn(**data)
            stored = await store_message({**message.model_dump(), "scope": "common"})
            await common_manager.broadcast(stored)
            await _notify_subscribers(stored)
    except WebSocketDisconnect:
        common_manager.disconnect(websocket)


@app.websocket("/ws/rooms/{room_id}")
async def websocket_room(websocket: WebSocket, room_id: str) -> None:
    """Realtime endpoint for room chat."""

    await room_manager.connect(room_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            stored = await room_manager.handle_incoming(room_id, data)
            message = MessageIn(**data)
            stored = await store_message({**message.model_dump(), "scope": "room", "room_id": room_id})
            await room_manager.broadcast(room_id, stored)
            await _notify_subscribers(stored)
    except WebSocketDisconnect:
        room_manager.disconnect(room_id, websocket)


@app.websocket("/ws/p2p/{session_id}/{user_id}")
async def websocket_p2p(websocket: WebSocket, session_id: str, user_id: str) -> None:
    """Realtime endpoint for P2P chats."""

    await p2p_manager.connect(session_id, user_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            message = MessageIn(**data)
            stored = await store_message({**message.model_dump(), "scope": "p2p", "chat_id": session_id})
            await p2p_manager.send(session_id, stored, exclude={message.user_id})
            await _notify_subscribers(stored)
    except WebSocketDisconnect:
        p2p_manager.disconnect(session_id, user_id)


@app.websocket("/ws/subscriptions/{user_id}")
async def websocket_subscription(websocket: WebSocket, user_id: str) -> None:
    """Deliver subscription notifications to users."""

    await subscription_manager.connect(user_id, websocket)
    try:
        while True:
            # Keep connection alive waiting for ping/pong
            await websocket.receive_text()
    except WebSocketDisconnect:
        subscription_manager.disconnect(user_id, websocket)


@app.get("/health")
async def healthcheck() -> Dict[str, str]:
    """Simple health check endpoint."""

    return {"status": "ok"}
