from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import discord

from config import TIMEZONE

_MSK_FALLBACK = timezone(timedelta(hours=3), name="MSK")
_tz: ZoneInfo | timezone | None = None


def get_timezone() -> ZoneInfo | timezone:
    global _tz
    if _tz is not None:
        return _tz
    try:
        _tz = ZoneInfo(TIMEZONE)
    except ZoneInfoNotFoundError:
        _tz = _MSK_FALLBACK
    return _tz


def normalize_datetime(dt: datetime) -> datetime:
    tz = get_timezone()
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def discord_timestamp(dt: datetime, style: str = "F") -> str:
    return f"<t:{int(normalize_datetime(dt).timestamp())}:{style}>"


def format_event_time(dt: datetime) -> str:
    dt = normalize_datetime(dt)
    ts = int(dt.timestamp())
    msk_label = dt.strftime("%d.%m.%Y %H:%M")
    return f"<t:{ts}:F> (<t:{ts}:R>)\n`{msk_label}` МСК"


def format_event_time_web(dt: datetime) -> str:
    dt = normalize_datetime(dt)
    return f"{dt.strftime('%d.%m.%Y %H:%M')} МСК"


def event_time_to_iso(dt: datetime) -> str:
    return normalize_datetime(dt).isoformat()


def event_time_from_iso(value: str) -> datetime:
    return normalize_datetime(datetime.fromisoformat(value))


def validate_future_time(dt: datetime) -> None:
    if normalize_datetime(dt) <= datetime.now(get_timezone()):
        raise ValueError("Время должно быть в будущем.")


def parse_event_time_input(value: str) -> datetime:
    raw = value.strip()
    if not raw:
        raise ValueError("Укажите время.")

    tz = get_timezone()
    now = datetime.now(tz)

    # Only time -> today in Moscow
    time_only = re.fullmatch(r"(\d{1,2}):(\d{2})", raw)
    if time_only:
        hour = int(time_only.group(1))
        minute = int(time_only.group(2))
        if hour > 23 or minute > 59:
            raise ValueError("Неверное время. Используйте ЧЧ:ММ по МСК.")
        return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # dd.mm.yyyy HH:MM
    full_date = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}):(\d{2})", raw)
    if full_date:
        day, month, year, hour, minute = map(int, full_date.groups())
        try:
            return normalize_datetime(
                datetime(year, month, day, hour, minute, tzinfo=tz)
            )
        except ValueError:
            raise ValueError("Неверная дата или время. Используйте ДД.ММ.ГГГГ ЧЧ:ММ.")

    # dd.mm HH:MM -> current year
    short_date = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})", raw)
    if short_date:
        day, month, hour, minute = map(int, short_date.groups())
        try:
            return normalize_datetime(
                datetime(now.year, month, day, hour, minute, tzinfo=tz)
            )
        except ValueError:
            raise ValueError("Неверная дата или время. Используйте ДД.ММ ЧЧ:ММ.")

    raise ValueError("Неверный формат. Используйте ЧЧ:ММ или ДД.ММ.ГГГГ ЧЧ:ММ (МСК).")


def build_message_link(guild_id: int, channel_id: int, message_id: int) -> str:
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


def parse_message_reference(value: str) -> tuple[int, int | None]:
    value = value.strip()
    if value.isdigit():
        return int(value), None
    parts = value.replace("https://", "").replace("http://", "").rstrip("/").split("/")
    if len(parts) >= 3 and parts[-1].isdigit():
        message_id = int(parts[-1])
        channel_id = int(parts[-2]) if parts[-2].isdigit() else None
        return message_id, channel_id
    raise ValueError(
        "Укажите ссылку на сообщение (ПКМ → Копировать ссылку) или ID сообщения."
    )


def build_event_embed(
    title: str,
    description: str,
    roblox_mode: str,
    event_time: str,
    creator: discord.Member | discord.User | None = None,
    creator_id: int | None = None,
    subscriber_count: int = 0,
    cohost_ids: list[int] | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=0x5865F2,
    )
    embed.add_field(name="Режим Roblox", value=roblox_mode, inline=True)
    embed.add_field(name="Начало", value=event_time, inline=True)
    embed.add_field(
        name="Уведомления в ЛС",
        value=str(subscriber_count),
        inline=True,
    )
    if cohost_ids:
        embed.add_field(
            name="Со-хостеры",
            value=" ".join(f"<@{uid}>" for uid in cohost_ids),
            inline=False,
        )
    if creator is not None:
        author = creator.display_name
    elif creator_id is not None:
        author = f"ID {creator_id}"
    else:
        author = "—"
    embed.set_footer(text=f"Создал: {author}")
    return embed


def event_status_label(status: str) -> str:
    from event_status import STATUS_LABELS

    return STATUS_LABELS.get(status, status)


def build_ended_embed(event: dict) -> discord.Embed:
    try:
        time_label = format_event_time(event_time_from_iso(event["event_time"]))
    except (ValueError, KeyError):
        time_label = "—"
    embed = discord.Embed(
        title=f"Завершён: {event['title']}",
        description=event["description"],
        color=0x95A5A6,
    )
    embed.add_field(name="Режим Roblox", value=event["roblox_mode"], inline=True)
    embed.add_field(name="Время", value=time_label, inline=True)
    return embed


def build_cancelled_embed(event: dict) -> discord.Embed:
    try:
        time_label = format_event_time(event_time_from_iso(event["event_time"]))
    except (ValueError, KeyError):
        time_label = "—"
    embed = discord.Embed(
        title=f"Отменено: {event['title']}",
        description=event["description"],
        color=0xED4245,
    )
    embed.add_field(name="Режим Roblox", value=event["roblox_mode"], inline=True)
    embed.add_field(name="Было запланировано", value=time_label, inline=True)
    return embed


def is_everyone_role(guild_id: int, role_id: int) -> bool:
    return role_id == guild_id


def format_role_ping(guild_id: int, role_id: int) -> str:
    if is_everyone_role(guild_id, role_id):
        return "@everyone"
    return f"<@&{role_id}>"


def format_role_ping_from_role(role: discord.Role) -> str:
    if role.is_default():
        return "@everyone"
    return f"<@&{role.id}>"


def allowed_mentions_for_role(
    guild_id: int, role_id: int
) -> discord.AllowedMentions:
    if is_everyone_role(guild_id, role_id):
        return discord.AllowedMentions(everyone=True)
    # roles=True — разрешить пинги из текста (<@&id>), совместимо с discord.py 2.4+
    return discord.AllowedMentions(roles=True)


def resolve_ping_role(guild: discord.Guild, role: discord.Role) -> discord.Role:
    return guild.get_role(role.id) or role


def validate_ping_role(
    role: discord.Role,
    guild: discord.Guild,
    channel: discord.abc.GuildChannel,
) -> str | None:
    role = resolve_ping_role(guild, role)
    me = guild.me
    if me is None:
        return "Бот не найден на сервере."

    perms = channel.permissions_for(me)
    if not perms.send_messages:
        return "У бота нет права отправлять сообщения в этот канал."

    if role.is_default():
        if not perms.mention_everyone:
            return (
                "У бота нет права «Упоминать @everyone» в этом канале. "
                "Выдайте его роли бота или выберите другую роль."
            )
        return None

    if role.managed:
        return (
            f"Роль «{role.name}» **управляется ботом или приложением** — "
            "Discord не даёт включить для неё пинг. Создайте обычную роль "
            "для ивентов или выберите @everyone / другую роль."
        )

    if not role.mentionable:
        return (
            f"Роль «{role.name}» сейчас **не упоминается**.\n\n"
            "**Где включить (обычная роль):**\n"
            "1. Настройки сервера → **Роли**\n"
            "2. Нажми на роль **{name}**\n"
            "3. Вкладка **Права** (Permissions)\n"
            "4. Внизу списка — переключатель **«Упоминание»** / "
            "**«Разрешить всем упоминать эту роль»** (Mentionable)\n\n"
            "В новом интерфейсе Discord иногда это во вкладке **Оформление** "
            "(Display) — пункт про @mention этой роли.\n\n"
            "Если переключателя **нет вообще** — роль системная или от бота, "
            "её пинговать нельзя. Сделай отдельную роль «Ивент» и выдай её людям."
        ).format(name=role.name)
    return None


def build_started_embed(event: dict, time_label: str | None = None) -> discord.Embed:
    if time_label is None:
        try:
            time_label = format_event_time(event_time_from_iso(event["event_time"]))
        except (ValueError, KeyError):
            time_label = event.get("event_time", "—")
    embed = discord.Embed(
        title=f"Ивент начался: {event['title']}",
        description=event["description"],
        color=0x57F287,
    )
    embed.add_field(name="Режим Roblox", value=event["roblox_mode"], inline=True)
    embed.add_field(name="Время", value=time_label, inline=True)
    return embed
