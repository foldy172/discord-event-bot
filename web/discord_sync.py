import logging

import discord
import httpx

import database as db
from config import DISCORD_TOKEN
from event_status import STATUS_ACTIVE, STATUS_CANCELLED, STATUS_ENDED, STATUS_PENDING
from utils import (
    build_cancelled_embed,
    build_ended_embed,
    build_event_embed,
    build_started_embed,
    event_time_from_iso,
    format_event_time,
)

logger = logging.getLogger(__name__)
API = "https://discord.com/api/v10"


async def sync_event_to_discord(event_id: int) -> tuple[bool, str]:
    if not DISCORD_TOKEN:
        return False, "DISCORD_TOKEN не задан — изменения только в базе."

    event = await db.get_event(event_id)
    if not event:
        return False, "Ивент не найден."

    embed, clear_components = await _build_embed_for_event(event)
    channel_id = event["channel_id"]
    message_id = event["message_id"]

    payload: dict = {"embeds": [embed.to_dict()]}
    if clear_components:
        payload["components"] = []

    headers = {"Authorization": f"Bot {DISCORD_TOKEN}"}
    url = f"{API}/channels/{channel_id}/messages/{message_id}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.patch(url, headers=headers, json=payload)
            if response.status_code == 404:
                return False, "Сообщение в Discord не найдено."
            if response.status_code == 403:
                return False, "Нет прав редактировать сообщение."
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.exception("Discord sync failed for event %s", event_id)
        return False, f"Ошибка Discord API: {exc}"

    return True, "Объявление в Discord обновлено."


async def _build_embed_for_event(event: dict) -> tuple[discord.Embed, bool]:
    status = event.get("status", STATUS_PENDING)
    event_id = event["id"]

    if status == STATUS_CANCELLED:
        return build_cancelled_embed(event), True
    if status == STATUS_ENDED:
        return build_ended_embed(event), True
    if status == STATUS_ACTIVE:
        time_label = format_event_time(event_time_from_iso(event["event_time"]))
        embed = build_started_embed(event, time_label=time_label)
        embed.color = discord.Color.green()
        return embed, True

    formatted_time = format_event_time(event_time_from_iso(event["event_time"]))
    count = await db.count_subscribers(event_id)
    cohosts = await db.get_event_cohosts(event_id)
    embed = build_event_embed(
        title=event["title"],
        description=event["description"],
        roblox_mode=event["roblox_mode"],
        event_time=formatted_time,
        creator_id=event["creator_id"],
        subscriber_count=count,
        cohost_ids=cohosts,
    )
    return embed, False
