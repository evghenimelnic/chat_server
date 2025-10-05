from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Set

from fastapi import WebSocket


class ConnectionManager:
    """Base connection manager for broadcasting messages."""

    def __init__(self) -> None:
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register websocket connection."""

        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove websocket connection."""

        self.active_connections.discard(websocket)

    async def send_personal_message(self, websocket: WebSocket, message: dict) -> None:
        """Send message to a single websocket."""

        await websocket.send_json(message)

    async def broadcast(self, message: dict) -> None:
        """Broadcast message to all active connections."""

        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except RuntimeError:
                self.active_connections.discard(connection)


class RoomConnectionManager:
    """Connection manager for topic-based rooms."""

    def __init__(self) -> None:
        self.rooms: Dict[str, Set[WebSocket]] = defaultdict(set)

    async def connect(self, room_id: str, websocket: WebSocket) -> None:
        """Register websocket to a room."""

        await websocket.accept()
        self.rooms[room_id].add(websocket)

    def disconnect(self, room_id: str, websocket: WebSocket) -> None:
        """Remove websocket from room."""

        if room_id in self.rooms:
            self.rooms[room_id].discard(websocket)
            if not self.rooms[room_id]:
                del self.rooms[room_id]

    async def broadcast(self, room_id: str, message: dict) -> None:
        """Broadcast message to specific room."""

        for connection in list(self.rooms.get(room_id, [])):
            try:
                await connection.send_json(message)
            except RuntimeError:
                self.rooms[room_id].discard(connection)
        if room_id in self.rooms and not self.rooms[room_id]:
            del self.rooms[room_id]


class P2PConnectionManager:
    """Connection manager for P2P sessions."""

    def __init__(self) -> None:
        self.sessions: Dict[str, Dict[str, WebSocket]] = defaultdict(dict)

    async def connect(self, session_id: str, user_id: str, websocket: WebSocket) -> None:
        """Register websocket for user in P2P session."""

        await websocket.accept()
        self.sessions[session_id][user_id] = websocket

    def disconnect(self, session_id: str, user_id: str) -> None:
        """Remove websocket from session."""

        if session_id in self.sessions and user_id in self.sessions[session_id]:
            del self.sessions[session_id][user_id]
            if not self.sessions[session_id]:
                del self.sessions[session_id]

    async def send(self, session_id: str, message: dict, exclude: Iterable[str] | None = None) -> None:
        """Send message to session participants."""

        exclude_set = set(exclude or [])
        for user, connection in list(self.sessions.get(session_id, {}).items()):
            if user in exclude_set:
                continue
            try:
                await connection.send_json(message)
            except RuntimeError:
                if session_id in self.sessions and user in self.sessions[session_id]:
                    del self.sessions[session_id][user]
                    if not self.sessions[session_id]:
                        del self.sessions[session_id]


class SubscriptionConnectionManager:
    """Manager for subscription notifications."""

    def __init__(self) -> None:
        self.users: Dict[str, Set[WebSocket]] = defaultdict(set)

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        """Attach websocket to user subscription stream."""

        await websocket.accept()
        self.users[user_id].add(websocket)

    def disconnect(self, user_id: str, websocket: WebSocket) -> None:
        """Remove websocket from subscription stream."""

        if user_id in self.users:
            self.users[user_id].discard(websocket)
            if not self.users[user_id]:
                del self.users[user_id]

    async def notify(self, user_id: str, payload: dict) -> None:
        """Notify a user about matched subscription."""

        for connection in list(self.users.get(user_id, [])):
            try:
                await connection.send_json(payload)
            except RuntimeError:
                self.users[user_id].discard(connection)

    async def broadcast(self, payload: dict) -> None:
        """Notify all connected users."""

        for user_connections in list(self.users.values()):
            for connection in list(user_connections):
                try:
                    await connection.send_json(payload)
                except RuntimeError:
                    user_connections.discard(connection)
