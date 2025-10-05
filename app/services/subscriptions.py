from __future__ import annotations

from datetime import datetime
from math import asin, cos, radians, sin, sqrt
from typing import Any, Dict, Iterable

from bson import ObjectId

from ..database import get_collection


EARTH_RADIUS_KM = 6371.0


def _serialize_id(value: ObjectId | str) -> str:
    """Convert Mongo object id to string."""

    if isinstance(value, ObjectId):
        return str(value)
    return value


def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in kilometres between two coordinates."""

    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return EARTH_RADIUS_KM * c


def _normalise_keywords(keywords: Iterable[str]) -> list[str]:
    """Prepare lowercase keyword list."""

    return [word.strip().lower() for word in keywords if word.strip()]


async def create_subscription(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Persist subscription definition."""

    collection = get_collection("subscriptions")
    document = {
        "user_id": payload["user_id"],
        "scope": payload.get("scope", "any"),
        "what": _normalise_keywords(payload.get("what", [])),
        "where": payload.get("where"),
        "when_start": payload.get("when_start"),
        "when_end": payload.get("when_end"),
        "room_id": payload.get("room_id"),
        "chat_id": payload.get("chat_id"),
        "created_at": datetime.utcnow(),
    }
    result = await collection.insert_one(document)
    document["id"] = _serialize_id(result.inserted_id)
    if document.get("when_start"):
        document["when_start"] = document["when_start"].isoformat()
    if document.get("when_end"):
        document["when_end"] = document["when_end"].isoformat()
    document["created_at"] = document["created_at"].isoformat()
    return document


async def list_subscriptions(user_id: str) -> list[Dict[str, Any]]:
    """Return all subscriptions for user."""

    collection = get_collection("subscriptions")
    cursor = collection.find({"user_id": user_id}).sort("created_at", -1)
    subscriptions: list[Dict[str, Any]] = []
    async for item in cursor:
        item["id"] = _serialize_id(item.pop("_id"))
        if item.get("when_start"):
            item["when_start"] = item["when_start"].isoformat()
        if item.get("when_end"):
            item["when_end"] = item["when_end"].isoformat()
        if item.get("created_at"):
            item["created_at"] = item["created_at"].isoformat()
        subscriptions.append(item)
    return subscriptions


def _match_keywords(subscription: Dict[str, Any], message: Dict[str, Any]) -> bool:
    keywords = subscription.get("what") or []
    if not keywords:
        return True
    content = message.get("content", "").lower()
    return any(keyword in content for keyword in keywords)


def _match_scope(subscription: Dict[str, Any], message: Dict[str, Any]) -> bool:
    scope = subscription.get("scope", "any")
    if scope == "any":
        return True
    if message.get("scope") != scope:
        return False
    if scope == "room" and subscription.get("room_id") and subscription["room_id"] != message.get("room_id"):
        return False
    if scope == "p2p" and subscription.get("chat_id") and subscription["chat_id"] != message.get("chat_id"):
        return False
    return True


def _match_location(subscription: Dict[str, Any], message: Dict[str, Any]) -> bool:
    sub_location = subscription.get("where")
    msg_location = message.get("location")
    if not sub_location:
        return True
    if not msg_location:
        return False
    radius = sub_location.get("radius_km") or 0
    if radius <= 0:
        return True
    distance = _haversine_distance(
        sub_location["latitude"],
        sub_location["longitude"],
        msg_location["latitude"],
        msg_location["longitude"],
    )
    return distance <= radius


def _match_time(subscription: Dict[str, Any], message: Dict[str, Any]) -> bool:
    raw_event = message.get("event_time") or message.get("created_at")
    if not raw_event:
        return True
    if isinstance(raw_event, str):
        try:
            event_time = datetime.fromisoformat(raw_event)
        except ValueError:
            return True
    else:
        event_time = raw_event
    start = subscription.get("when_start")
    end = subscription.get("when_end")
    if start and event_time < start:
        return False
    if end and event_time > end:
        return False
    return True


async def find_matching_subscriptions(message: Dict[str, Any]) -> list[Dict[str, Any]]:
    """Return subscriptions matching provided message."""

    collection = get_collection("subscriptions")
    scope = message.get("scope")
    query: Dict[str, Any] = {
        "$or": [
            {"scope": "any"},
            {"scope": scope},
        ]
    }
    if scope == "room" and message.get("room_id"):
        query["$or"].append({"scope": "room", "room_id": message["room_id"]})
    if scope == "p2p" and message.get("chat_id"):
        query["$or"].append({"scope": "p2p", "chat_id": message["chat_id"]})

    cursor = collection.find(query)
    matches: list[Dict[str, Any]] = []
    async for subscription in cursor:
        subscription["id"] = _serialize_id(subscription.pop("_id"))
        if _match_scope(subscription, message) and _match_keywords(subscription, message) and _match_location(subscription, message) and _match_time(subscription, message):
            if subscription.get("when_start"):
                subscription["when_start"] = subscription["when_start"].isoformat()
            if subscription.get("when_end"):
                subscription["when_end"] = subscription["when_end"].isoformat()
            if subscription.get("created_at"):
                subscription["created_at"] = subscription["created_at"].isoformat()
            matches.append(subscription)
    return matches
