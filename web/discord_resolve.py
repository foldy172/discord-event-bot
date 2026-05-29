import logging
import time

import httpx

from config import DISCORD_TOKEN
from utils import is_everyone_role

logger = logging.getLogger(__name__)
API = "https://discord.com/api/v10"
_CACHE_TTL = 300.0
_user_cache: dict[int, tuple[str, float]] = {}
_role_cache: dict[tuple[int, int], tuple[str, float]] = {}


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bot {DISCORD_TOKEN}"}


async def fetch_user_label(user_id: int, guild_id: int | None = None) -> str:
    if not user_id:
        return "—"

    if not DISCORD_TOKEN:
        return f"Пользователь {user_id}"

    now = time.monotonic()
    if user_id in _user_cache and _user_cache[user_id][1] > now:
        return _user_cache[user_id][0]

    username: str | None = None
    display: str | None = None
    nick: str | None = None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{API}/users/{user_id}",
                headers=_headers(),
            )
            if response.status_code == 200:
                user = response.json()
                username = user.get("username")
                display = user.get("global_name") or username

            if guild_id:
                member_resp = await client.get(
                    f"{API}/guilds/{guild_id}/members/{user_id}",
                    headers=_headers(),
                )
                if member_resp.status_code == 200:
                    data = member_resp.json()
                    user = data.get("user", {})
                    nick = data.get("nick")
                    username = user.get("username") or username
                    display = nick or user.get("global_name") or username or display
    except httpx.HTTPError:
        logger.warning("Не удалось получить пользователя %s", user_id)

    if display and username:
        label = f"{display} (@{username})"
    elif display:
        label = display
    elif username:
        label = f"@{username}"
    else:
        label = f"Пользователь {user_id}"

    _user_cache[user_id] = (label, now + _CACHE_TTL)
    return label


async def fetch_role_label(guild_id: int, role_id: int) -> str:
    if is_everyone_role(guild_id, role_id):
        return "@everyone"

    if not DISCORD_TOKEN:
        return str(role_id)

    key = (guild_id, role_id)
    now = time.monotonic()
    if key in _role_cache and _role_cache[key][1] > now:
        return _role_cache[key][0]

    label = str(role_id)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{API}/guilds/{guild_id}/roles/{role_id}",
                headers=_headers(),
            )
            if response.status_code == 200:
                name = response.json().get("name")
                if name:
                    label = f"@{name}"
    except httpx.HTTPError:
        logger.warning("Не удалось получить роль %s", role_id)

    _role_cache[key] = (label, now + _CACHE_TTL)
    return label


async def resolve_user_labels(
    user_ids: list[int], guild_id: int | None
) -> dict[int, str]:
    result: dict[int, str] = {}
    for uid in user_ids:
        result[uid] = await fetch_user_label(uid, guild_id)
    return result
