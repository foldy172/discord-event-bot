import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GUILD_ID = os.getenv("GUILD_ID")
EVENT_CHANNEL_ID: int | None = None
_event_ch = os.getenv("EVENT_CHANNEL_ID", "").strip()
if _event_ch.isdigit():
    EVENT_CHANNEL_ID = int(_event_ch)
DATABASE_PATH = Path(__file__).parent / "events.db"
TIMEZONE = "Europe/Moscow"


def _parse_id_list(value: str) -> frozenset[int]:
    if not value.strip():
        return frozenset()
    result: set[int] = set()
    for part in value.replace(" ", "").split(","):
        part = part.strip()
        if part.isdigit():
            result.add(int(part))
    return frozenset(result)


ALLOWED_ROLE_IDS = _parse_id_list(os.getenv("ALLOWED_ROLE_IDS", ""))
ALLOWED_USER_IDS = _parse_id_list(os.getenv("ALLOWED_USER_IDS", ""))
ADMIN_ROLE_IDS = _parse_id_list(os.getenv("ADMIN_ROLE_IDS", ""))
ADMIN_USER_IDS = _parse_id_list(os.getenv("ADMIN_USER_IDS", ""))

WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
# Учётная запись разработчика панели (создаёт админов на сайте)
WEB_DEV_USERNAME = (
    os.getenv("WEB_DEV_USERNAME", "").strip()
    or os.getenv("WEB_USERNAME", "developer").strip()
)
WEB_DEV_PASSWORD = os.getenv("WEB_DEV_PASSWORD", "") or os.getenv("WEB_PASSWORD", "")
# Совместимость со старым .env
WEB_USERNAME = WEB_DEV_USERNAME
WEB_PASSWORD = WEB_DEV_PASSWORD
WEB_SECRET = os.getenv("WEB_SECRET", "") or os.getenv("DISCORD_TOKEN", "change-me")[:32]
WEB_ENABLED = os.getenv("WEB_ENABLED", "true").lower() in ("1", "true", "yes", "on")
