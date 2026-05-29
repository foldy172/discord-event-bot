import asyncio
from datetime import datetime, timedelta

import discord

import database as db
from event_status import STATUS_ACTIVE, STATUS_CANCELLED, STATUS_ENDED, STATUS_PENDING
from utils import (
    allowed_mentions_for_role,
    format_role_ping,
    build_cancelled_embed,
    build_ended_embed,
    build_event_embed,
    build_started_embed,
    event_time_from_iso,
    event_time_to_iso,
    format_event_time,
    get_timezone,
    normalize_datetime,
)


async def refresh_event_message(
    bot: discord.Client, event_id: int, *, cancelled: bool = False
) -> bool:
    event = await db.get_event(event_id)
    if not event:
        return False

    channel = bot.get_channel(event["channel_id"])
    if channel is None:
        try:
            channel = await bot.fetch_channel(event["channel_id"])
        except (discord.NotFound, discord.Forbidden):
            return False

    if not isinstance(channel, discord.TextChannel):
        return False

    try:
        message = await channel.fetch_message(event["message_id"])
    except (discord.NotFound, discord.Forbidden):
        return False

    status = event.get("status", STATUS_PENDING)

    if cancelled or status == STATUS_CANCELLED:
        embed = build_cancelled_embed(event)
        await message.edit(embed=embed, view=None)
        return True

    if status == STATUS_ACTIVE:
        time_label = format_event_time(event_time_from_iso(event["event_time"]))
        embed = build_started_embed(event, time_label=time_label)
        embed.color = discord.Color.green()
        await message.edit(embed=embed, view=None)
        return True

    if status == STATUS_ENDED:
        embed = build_ended_embed(event)
        await message.edit(embed=embed, view=None)
        return True

    creator = bot.get_user(event["creator_id"])
    if creator is None:
        try:
            creator = await bot.fetch_user(event["creator_id"])
        except discord.NotFound:
            creator = None

    formatted_time = format_event_time(event_time_from_iso(event["event_time"]))
    count = await db.count_subscribers(event_id)
    cohosts = await db.get_event_cohosts(event_id)
    embed = build_event_embed(
        title=event["title"],
        description=event["description"],
        roblox_mode=event["roblox_mode"],
        event_time=formatted_time,
        creator=creator,
        creator_id=event["creator_id"],
        subscriber_count=count,
        cohost_ids=cohosts,
    )
    if status == STATUS_PENDING:
        from views import make_event_view

        view = make_event_view(event_id)
    else:
        view = None
    await message.edit(embed=embed, view=view)
    if view:
        bot.add_view(view)
    return True


async def notify_subscribers_reschedule(
    bot: discord.Client, event_id: int, new_time_label: str, reason: str | None
) -> None:
    event = await db.get_event(event_id)
    if not event:
        return
    subscribers = await db.get_subscribers(event_id)
    text = (
        f"Ивент **{event['title']}** перенесён.\n"
        f"Новое время: {new_time_label}"
    )
    if reason:
        text += f"\nПричина: {reason}"
    for user_id in subscribers:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        if user is None:
            continue
        try:
            await user.send(text)
        except discord.Forbidden:
            pass


async def update_event_time(
    bot: discord.Client,
    event_id: int,
    event_dt: datetime,
    *,
    notify: bool = False,
    reason: str | None = None,
) -> str:
    event_dt = normalize_datetime(event_dt)
    time_label = format_event_time(event_dt)
    fields: dict = {"event_time": event_time_to_iso(event_dt)}
    if notify:
        fields["status"] = STATUS_PENDING
        fields["notified"] = 0
    await db.update_event(event_id, **fields)
    await refresh_event_message(bot, event_id)

    if notify:
        event = await db.get_event(event_id)
        if event:
            channel = bot.get_channel(event["channel_id"])
            if channel and isinstance(channel, discord.TextChannel):
                guild_id = event["guild_id"]
                role_id = event["role_id"]
                ping_text = (
                    f"{format_role_ping(guild_id, role_id)} "
                    f"Ивент **{event['title']}** перенесён.\n"
                    f"Новое время: {time_label}"
                )
                if reason:
                    ping_text += f"\nПричина: {reason}"
                await channel.send(
                    ping_text,
                    allowed_mentions=allowed_mentions_for_role(
                        guild_id, role_id
                    ),
                )
        await notify_subscribers_reschedule(bot, event_id, time_label, reason)

    return time_label


async def start_event_now(
    bot: discord.Client, event_id: int, *, manual: bool = False
) -> bool:
    event = await db.get_event(event_id)
    if not event or event.get("status") != STATUS_PENDING:
        return False

    await db.set_event_status(event_id, STATUS_ACTIVE)
    event = await db.get_event(event_id)
    if not event:
        return False

    start = event_time_from_iso(event["event_time"])
    time_label = format_event_time(start)
    dm_embed = build_started_embed(event, time_label=time_label)
    dm_text = (
        f"Ивент **{event['title']}** начался!\n"
        f"Режим: **{event['roblox_mode']}**\n"
        f"Время: {time_label}"
    )

    subscribers = await db.get_subscribers(event_id)
    for user_id in subscribers:
        user = bot.get_user(user_id)
        if user is None:
            try:
                user = await bot.fetch_user(user_id)
            except discord.NotFound:
                continue
        try:
            await user.send(content=dm_text, embed=dm_embed)
        except discord.Forbidden:
            pass

    channel = bot.get_channel(event["channel_id"])
    if channel is None:
        try:
            channel = await bot.fetch_channel(event["channel_id"])
        except (discord.NotFound, discord.Forbidden):
            channel = None

    if channel and isinstance(channel, discord.TextChannel):
        try:
            message = await channel.fetch_message(event["message_id"])
            started_embed = build_started_embed(event, time_label=time_label)
            started_embed.color = discord.Color.green()
            await message.edit(embed=started_embed, view=None)
            suffix = " (запущен досрочно)" if manual else ""
            guild_id = event["guild_id"]
            role_id = event["role_id"]
            await channel.send(
                f"{format_role_ping(guild_id, role_id)} "
                f"Ивент **{event['title']}** начался!{suffix}",
                allowed_mentions=allowed_mentions_for_role(guild_id, role_id),
            )
        except (discord.NotFound, discord.Forbidden):
            pass

    if manual:
        await notify_hosts_event_closed(
            bot, event, delete_after_seconds=300, reason="запущен"
        )
    return True


async def cancel_event(bot: discord.Client, event_id: int) -> bool:
    event = await db.get_event(event_id)
    if not event:
        return False
    status = event.get("status", STATUS_PENDING)
    if status not in (STATUS_PENDING, STATUS_ACTIVE):
        return False

    await db.set_event_status(event_id, STATUS_CANCELLED)
    await refresh_event_message(bot, event_id, cancelled=True)
    return True


async def end_event(bot: discord.Client, event_id: int) -> bool:
    event = await db.get_event(event_id)
    if not event or event.get("status") != STATUS_ACTIVE:
        return False

    await db.set_event_status(event_id, STATUS_ENDED)
    await refresh_event_message(bot, event_id)
    event = await db.get_event(event_id)
    if event:
        await notify_hosts_event_closed(
            bot, event, delete_after_seconds=300, reason="завершён"
        )
    return True


async def notify_hosts_event_closed(
    bot: discord.Client,
    event: dict,
    *,
    delete_after_seconds: int = 300,
    reason: str = "завершён",
) -> None:
    host_ids = {event["creator_id"], *(await db.get_event_cohosts(event["id"]))}
    delete_at = datetime.now(get_timezone()) + timedelta(
        seconds=delete_after_seconds
    )
    timer = f"<t:{int(delete_at.timestamp())}:R>"
    text = (
        f"Ивент **{event['title']}** {reason}.\n"
        f"Объявление можно архивировать. Сообщение удалится {timer}."
    )
    for user_id in host_ids:
        user = bot.get_user(user_id)
        if user is None:
            try:
                user = await bot.fetch_user(user_id)
            except discord.NotFound:
                continue
        try:
            message = await user.send(text)
        except discord.Forbidden:
            continue
        asyncio.create_task(_delete_message_later(message, delete_after_seconds))


async def _delete_message_later(
    message: discord.Message, delay_seconds: int
) -> None:
    await asyncio.sleep(delay_seconds)
    try:
        await message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass
