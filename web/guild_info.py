import logging
import time

import httpx

from config import DISCORD_TOKEN, GUILD_ID

logger = logging.getLogger(__name__)

_cache: dict[str, tuple[str | None, float]] = {}
_CACHE_TTL = 300.0


async def fetch_guild_name(guild_id: int) -> str | None:
    if not DISCORD_TOKEN:
        return None
    key = str(guild_id)
    now = time.monotonic()
    if key in _cache and _cache[key][1] > now:
        return _cache[key][0]

    name: str | None = None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"https://discord.com/api/v10/guilds/{guild_id}",
                headers={"Authorization": f"Bot {DISCORD_TOKEN}"},
            )
            if response.status_code == 200:
                name = response.json().get("name")
    except httpx.HTTPError:
        logger.warning("Не удалось получить название сервера %s", guild_id)

    _cache[key] = (name, now + _CACHE_TTL)
    return name


def resolve_guild_id() -> int | None:
    if not GUILD_ID:
        return None
    try:
        return int(GUILD_ID)
    except ValueError:
        return None


async def get_guild_display() -> dict:
    guild_id = resolve_guild_id()
    guild_name = None
    if guild_id:
        guild_name = await fetch_guild_name(guild_id)
    return {
        "guild_id": guild_id,
        "guild_name": guild_name,
    }
