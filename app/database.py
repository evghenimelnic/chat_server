from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from .config import settings


class Mongo:
    """Encapsulate Mongo client and database references."""

    client: AsyncIOMotorClient | None = None
    db: AsyncIOMotorDatabase | None = None


async def connect() -> None:
    """Connect to MongoDB and prepare indexes."""

    Mongo.client = AsyncIOMotorClient(settings.mongo_uri)
    Mongo.db = Mongo.client[settings.mongo_db]
    await Mongo.db.rooms.create_index([("tags", "text"), ("name", "text"), ("description", "text")])
    await Mongo.db.subscriptions.create_index("user_id")
    await Mongo.db.messages.create_index([("scope", 1), ("room_id", 1), ("chat_id", 1), ("created_at", -1)])


async def disconnect() -> None:
    """Close MongoDB connection."""

    if Mongo.client is not None:
        Mongo.client.close()
        Mongo.client = None
        Mongo.db = None


def get_collection(name: str) -> Any:
    """Return a Mongo collection by name."""

    if Mongo.db is None:
        raise RuntimeError("Mongo database is not initialised")
    return Mongo.db[name]
