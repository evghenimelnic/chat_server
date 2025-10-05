from functools import lru_cache
from typing import List
import os


class Settings:
    """Application settings loaded from environment variables."""

    def __init__(self) -> None:
        self.mongo_uri: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
        self.mongo_db: str = os.getenv("MONGO_DB", "chat_server")
        self.allowed_origins: List[str] = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "*").split(",")]
        self.debug: bool = os.getenv("DEBUG", "false").lower() == "true"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance."""

    return Settings()


settings = get_settings()
