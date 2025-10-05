from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from bson import ObjectId

from ..database import get_collection


def _serialize_id(value: ObjectId | str) -> str:
    """Convert Mongo object id to string."""

    if isinstance(value, ObjectId):
        return str(value)
    return value


async def store_message(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Persist message and return serialised document."""

    messages = get_collection("messages")
    now = datetime.utcnow()
    event_time = payload.get("event_time")
    document = {
        "user_id": payload["user_id"],
        "content": payload["content"],
        "location": payload.get("location"),
        "event_time": event_time,
        "scope": payload["scope"],
        "room_id": payload.get("room_id"),
        "chat_id": payload.get("chat_id"),
        "created_at": now,
    }
    result = await messages.insert_one(document)
    response = {
        **document,
        "id": _serialize_id(result.inserted_id),
        "created_at": now.isoformat(),
    }
    if event_time:
        response["event_time"] = event_time.isoformat() if isinstance(event_time, datetime) else event_time
    return response


async def fetch_history(
    scope: str,
    room_id: Optional[str] = None,
    chat_id: Optional[str] = None,
    limit: int = 50,
    before: Optional[datetime] = None,
) -> list[Dict[str, Any]]:
    """Return ordered history for given scope."""

    messages = get_collection("messages")
    query: Dict[str, Any] = {"scope": scope}
    if room_id:
        query["room_id"] = room_id
    if chat_id:
        query["chat_id"] = chat_id
    if before:
        query["created_at"] = {"$lt": before}

    cursor = messages.find(query).sort("created_at", -1).limit(limit)
    history: list[Dict[str, Any]] = []
    async for item in cursor:
        event_time = item.get("event_time")
        item["id"] = _serialize_id(item.pop("_id"))
        item["created_at"] = item["created_at"].isoformat()
        if event_time:
            item["event_time"] = event_time.isoformat()
        history.append(item)
    history.reverse()
    return history
