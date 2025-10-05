"""Chat domain services for common and room conversations."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, Iterable, List

from fastapi import WebSocket

from .database import get_collection
from .schemas import MessageIn, MessageOut, RoomCreate, RoomOut
from .services.messages import fetch_history, store_message
from .websocket_manager import ConnectionManager, RoomConnectionManager


class CommonChat:
    """Coordinator for the global chat channel."""

    def __init__(self, connection_manager: ConnectionManager) -> None:
        self._connections = connection_manager

    async def connect(self, websocket: WebSocket) -> None:
        """Register an incoming websocket connection."""

        await self._connections.connect(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a websocket connection from the pool."""

        self._connections.disconnect(websocket)

    async def history(self, limit: int = 50) -> List[MessageOut]:
        """Return the most recent messages for the common chat."""

        history = await fetch_history(scope="common", limit=limit)
        return [MessageOut(**item) for item in history]

    async def handle_incoming(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Persist a new message and broadcast it to all subscribers."""

        message = MessageIn(**payload)
        stored = await store_message({**message.model_dump(), "scope": "common"})
        await self._connections.broadcast(stored)
        return stored


class RoomManager:
    """Manage room metadata and realtime messaging."""

    def __init__(self, connection_manager: RoomConnectionManager) -> None:
        self._connections = connection_manager

    async def create(self, room: RoomCreate) -> RoomOut:
        """Persist a room and return its representation."""

        rooms = get_collection("rooms")
        document = room.model_dump()
        document["tags"] = [tag.lower() for tag in document.get("tags", [])]
        result = await rooms.insert_one(document)
        document["id"] = str(result.inserted_id)
        return RoomOut(**document)

    async def list(
        self,
        *,
        tags: Iterable[str] | None = None,
        topic: str | None = None,
        q: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        radius_km: float | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> List[RoomOut]:
        """Return rooms that match the requested filters."""

        rooms = get_collection("rooms")
        query: Dict[str, Any] = {}

        if tags:
            query["tags"] = {"$all": [tag.lower() for tag in tags]}
        if topic:
            query["topic"] = topic

        filters: List[Dict[str, Any]] = []
        if q:
            filters.append({"$text": {"$search": q}})

        if latitude is not None and longitude is not None and radius_km is not None:
            lat_delta = radius_km / 110.574
            lon_delta = radius_km / (111.320 * max(abs(math.cos(math.radians(latitude))), 0.0001))
            filters.append(
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

        if filters:
            query["$and"] = filters if query else filters

        cursor = rooms.find(query)
        response: List[RoomOut] = []
        async for document in cursor:
            document["id"] = str(document.pop("_id"))
            response.append(RoomOut(**document))
        return response

    async def history(self, room_id: str, limit: int = 50) -> List[MessageOut]:
        """Return the most recent messages for a room."""

        history = await fetch_history(scope="room", room_id=room_id, limit=limit)
        return [MessageOut(**item) for item in history]

    async def connect(self, room_id: str, websocket: WebSocket) -> None:
        """Attach a websocket to a room stream."""

        await self._connections.connect(room_id, websocket)

    def disconnect(self, room_id: str, websocket: WebSocket) -> None:
        """Detach a websocket from a room stream."""

        self._connections.disconnect(room_id, websocket)

    async def handle_incoming(self, room_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Persist and broadcast a room message."""

        message = MessageIn(**payload)
        stored = await store_message({**message.model_dump(), "scope": "room", "room_id": room_id})
        await self._connections.broadcast(room_id, stored)
        return stored

