from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SANCTIONS_FEED_URL: str = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"
    FUZZY_MATCH_THRESHOLD: float = 0.85
    DATABASE_URL: str = "sqlite+aiosqlite:///data/sanctions.db"
    DB_PATH: str = "data/sanctions.db"
    LOG_LEVEL: str = "INFO"
    REQUEST_TIMEOUT_SECONDS: float = 30.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def sqlite_path(self) -> Path:
        return Path(self.DB_PATH)


settings = Settings()
