"""
Modul konfigurasi terpusat.

Semua nilai konfigurasi yang berasal dari environment variables (.env)
dibaca dan divalidasi di sini, agar modul lain cukup melakukan
`from config import settings` tanpa perlu memanggil os.getenv berulang kali.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Muat file .env yang berada di root project
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _get_bool(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(key: str, default: int) -> int:
    value = os.getenv(key)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    discord_token: str
    bot_owner_id: int
    dev_guild_id: int | None
    database_url: str
    custom_activities: tuple[str, ...]
    activity_rotation_interval: int
    log_level: str
    local_storage_path: Path
    s3_endpoint_url: str | None
    s3_access_key: str | None
    s3_secret_key: str | None
    s3_bucket_name: str | None
    s3_public_base_url: str | None
    custom_web_enabled: bool
    custom_web_host: str
    custom_web_port: int
    custom_web_public_url: str | None
    dashboard_enabled: bool
    discord_client_id: str | None
    discord_client_secret: str | None
    dashboard_redirect_uri: str | None
    dashboard_session_hours: int
    base_dir: Path = field(default_factory=lambda: BASE_DIR)

    def validate(self) -> None:
        missing = []
        if not self.discord_token:
            missing.append("DISCORD_TOKEN")
        if not self.bot_owner_id:
            missing.append("BOT_OWNER_ID")
        if missing:
            raise RuntimeError(
                "Environment variable wajib belum diisi di .env: "
                + ", ".join(missing)
            )


def load_settings() -> Settings:
    dev_guild_raw = os.getenv("DEV_GUILD_ID", "").strip()
    custom_activities = tuple(
        activity.strip()
        for activity in os.getenv("CUSTOM_ACTIVITIES", "").split("|")
        if activity.strip()
    )
    return Settings(
        discord_token=os.getenv("DISCORD_TOKEN", "").strip(),
        bot_owner_id=_get_int("BOT_OWNER_ID", 0),
        dev_guild_id=int(dev_guild_raw) if dev_guild_raw else None,
        database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./data/bot.db").strip(),
        custom_activities=custom_activities,
        activity_rotation_interval=max(5, _get_int("ACTIVITY_ROTATION_INTERVAL", 60)),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        local_storage_path=Path(os.getenv("LOCAL_STORAGE_PATH", "./data/images")),
        s3_endpoint_url=os.getenv("S3_ENDPOINT_URL", "").strip() or None,
        s3_access_key=os.getenv("S3_ACCESS_KEY", "").strip() or None,
        s3_secret_key=os.getenv("S3_SECRET_KEY", "").strip() or None,
        s3_bucket_name=os.getenv("S3_BUCKET_NAME", "").strip() or None,
        s3_public_base_url=os.getenv("S3_PUBLIC_BASE_URL", "").strip() or None,
        custom_web_enabled=_get_bool("CUSTOM_WEB_ENABLED", False),
        custom_web_host=os.getenv("CUSTOM_WEB_HOST", "0.0.0.0").strip() or "0.0.0.0",
        custom_web_port=max(1, min(65535, _get_int("CUSTOM_WEB_PORT", 8080))),
        custom_web_public_url=os.getenv("CUSTOM_WEB_PUBLIC_URL", "").strip().rstrip("/") or None,
        dashboard_enabled=_get_bool("DASHBOARD_ENABLED", False),
        discord_client_id=os.getenv("DISCORD_CLIENT_ID", "").strip() or None,
        discord_client_secret=os.getenv("DISCORD_CLIENT_SECRET", "").strip() or None,
        dashboard_redirect_uri=os.getenv("DASHBOARD_REDIRECT_URI", "").strip() or None,
        dashboard_session_hours=max(1, min(168, _get_int("DASHBOARD_SESSION_HOURS", 12))),
    )


settings = load_settings()
