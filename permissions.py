import discord

import database as db
from config import (
    ADMIN_ROLE_IDS,
    ADMIN_USER_IDS,
    ALLOWED_ROLE_IDS,
    ALLOWED_USER_IDS,
    EVENT_CHANNEL_ID,
)

MSG_NOT_CONFIGURED = (
    "Создание ивентов отключено. Укажите хостеров или админов в `.env`: "
    "`ALLOWED_ROLE_IDS`, `ALLOWED_USER_IDS`, `ADMIN_ROLE_IDS`, `ADMIN_USER_IDS`."
)
MSG_NO_PERMISSION = "У вас нет прав для этого действия."
MSG_WRONG_EVENT_CHANNEL = (
    "Создавать объявления можно только в канале <#{channel_id}>."
)


def is_allowed_event_channel(channel_id: int) -> bool:
    if EVENT_CHANNEL_ID is None:
        return True
    return channel_id == EVENT_CHANNEL_ID
MSG_NO_EVENT_ACCESS = "Вы можете управлять только своими ивентами или теми, где вы со-хост."


def _member_has_roles(member: discord.Member, role_ids: frozenset[int]) -> bool:
    if not role_ids:
        return False
    member_role_ids = {role.id for role in member.roles}
    return bool(member_role_ids & role_ids)


def member_is_host_in_config(member: discord.Member) -> bool:
    if member.id in ALLOWED_USER_IDS:
        return True
    return _member_has_roles(member, ALLOWED_ROLE_IDS)


def member_is_admin_in_config(member: discord.Member) -> bool:
    if member.id in ADMIN_USER_IDS:
        return True
    return _member_has_roles(member, ADMIN_ROLE_IDS)


async def member_is_host_in_database(member: discord.Member) -> bool:
    if member.id in await db.get_manager_users(member.guild.id):
        return True
    role_ids = await db.get_manager_roles(member.guild.id)
    return _member_has_roles(member, frozenset(role_ids))


async def member_is_admin_in_database(member: discord.Member) -> bool:
    if member.id in await db.get_admin_users(member.guild.id):
        return True
    role_ids = await db.get_admin_roles(member.guild.id)
    return _member_has_roles(member, frozenset(role_ids))


async def is_host_configured(guild_id: int) -> bool:
    if ALLOWED_USER_IDS or ALLOWED_ROLE_IDS:
        return True
    return bool(
        await db.get_manager_roles(guild_id) or await db.get_manager_users(guild_id)
    )


async def is_admin_configured(guild_id: int) -> bool:
    if ADMIN_USER_IDS or ADMIN_ROLE_IDS:
        return True
    return bool(
        await db.get_admin_roles(guild_id) or await db.get_admin_users(guild_id)
    )


async def is_events_enabled(guild_id: int) -> bool:
    return await is_host_configured(guild_id) or await is_admin_configured(guild_id)


async def user_is_host(member: discord.Member) -> bool:
    if not await is_host_configured(member.guild.id):
        return False
    return member_is_host_in_config(member) or await member_is_host_in_database(member)


async def user_is_event_admin(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    if await is_admin_configured(member.guild.id):
        return member_is_admin_in_config(member) or await member_is_admin_in_database(
            member
        )
    return False


async def user_can_create(member: discord.Member) -> bool:
    if not await is_events_enabled(member.guild.id):
        return False
    return await user_is_event_admin(member) or await user_is_host(member)


async def user_can_manage(
    member: discord.Member, event: dict | None = None
) -> bool:
    if event is None:
        return await user_is_event_admin(member)

    if await user_is_event_admin(member):
        return True
    if member.id == event["creator_id"]:
        return True
    if await db.is_event_cohost(event["id"], member.id):
        return True
    return False


async def user_can_assign_cohosts(
    member: discord.Member, event: dict
) -> bool:
    if await user_is_event_admin(member):
        return True
    return member.id == event["creator_id"]


async def user_can_manage_organizers(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    return await user_is_event_admin(member)
