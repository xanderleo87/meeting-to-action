"""Settings read from the environment. The only place a model name lives."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str | None
    claude_model: str
    database_url: str | None
    access_key: str | None


def load_settings() -> Settings:
    return Settings(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        claude_model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
        database_url=os.getenv("DATABASE_URL"),
        access_key=os.getenv("APP_ACCESS_KEY") or None,
    )
