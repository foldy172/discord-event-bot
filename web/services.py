import database as db
from config import (
    ADMIN_ROLE_IDS,
    ADMIN_USER_IDS,
    ALLOWED_ROLE_IDS,
    ALLOWED_USER_IDS,
)
from event_status import STATUS_LABELS
from utils import (
    build_message_link,
    event_status_label,
    event_time_from_iso,
    format_event_time_web,
)
from web.discord_resolve import (
    fetch_role_label,
    fetch_user_label,
    resolve_user_labels,
)


async def get_event_full(event_id: int) -> dict | None:
    event = await db.get_event(event_id)
    if not event:
        return None
    subscribers = await db.get_subscribers(event_id)
    cohosts = await db.get_event_cohosts(event_id)
    sub_count = await db.count_subscribers(event_id)
    guild_id = event["guild_id"]

    event_dt = None
    event_time_unix = 0
    time_web = "—"
    try:
        event_dt = event_time_from_iso(event["event_time"])
        time_web = format_event_time_web(event_dt)
        event_time_unix = int(event_dt.timestamp())
    except (ValueError, KeyError):
        time_web = str(event.get("event_time", "—"))

    if sub_count > 0 and not subscribers:
        subscribers = await db.get_subscribers(event_id)

    creator_id = int(event["creator_id"])
    creator_label = await fetch_user_label(creator_id, guild_id)
    role_label = await fetch_role_label(guild_id, int(event["role_id"]))
    subscriber_labels = await resolve_user_labels(subscribers, guild_id)
    cohost_labels = await resolve_user_labels(cohosts, guild_id)

    subscribers_display = [
        {
            "id": int(uid),
            "label": subscriber_labels.get(int(uid), f"Пользователь {uid}"),
        }
        for uid in subscribers
    ]
    cohosts_display = [
        {
            "id": int(uid),
            "label": cohost_labels.get(int(uid), f"Пользователь {uid}"),
        }
        for uid in cohosts
    ]

    return {
        **event,
        "subscribers": [int(u) for u in subscribers],
        "cohosts": [int(u) for u in cohosts],
        "subscribers_display": subscribers_display,
        "cohosts_display": cohosts_display,
        "subscriber_count": sub_count,
        "status_label": event_status_label(event.get("status", "pending")),
        "time_web": time_web,
        "event_time_unix": event_time_unix,
        "creator_id": creator_id,
        "creator_label": creator_label,
        "role_label": role_label,
        "message_link": build_message_link(
            event["guild_id"], event["channel_id"], event["message_id"]
        ),
    }


async def list_events_for_web(
    guild_id: int, status: str | None = None
) -> list[dict]:
    events = await db.list_events(guild_id, status=status)
    result = []
    for event in events:
        try:
            time_short = format_event_time_web(
                event_time_from_iso(event["event_time"])
            ).replace(" МСК", "")
        except (ValueError, KeyError):
            time_short = event.get("event_time", "—")
        sub_count = await db.count_subscribers(event["id"])
        result.append(
            {
                **event,
                "status_label": event_status_label(
                    event.get("status", "pending")
                ),
                "time_short": time_short,
                "subscriber_count": sub_count,
                "message_link": build_message_link(
                    event["guild_id"],
                    event["channel_id"],
                    event["message_id"],
                ),
            }
        )
    return result


async def get_organizers_summary(guild_id: int) -> dict:
    host_roles_db = await db.get_manager_roles(guild_id)
    host_users_db = await db.get_manager_users(guild_id)
    admin_roles_db = await db.get_admin_roles(guild_id)
    admin_users_db = await db.get_admin_users(guild_id)

    async def role_items(role_ids: list[int]) -> list[dict]:
        items = []
        for rid in role_ids:
            items.append(
                {"id": rid, "label": await fetch_role_label(guild_id, rid)}
            )
        return items

    async def user_items(user_ids: list[int]) -> list[dict]:
        items = []
        for uid in user_ids:
            items.append(
                {"id": uid, "label": await fetch_user_label(uid, guild_id)}
            )
        return items

    return {
        "admin_roles_env": await role_items(sorted(ADMIN_ROLE_IDS)),
        "admin_users_env": await user_items(sorted(ADMIN_USER_IDS)),
        "host_roles_env": await role_items(sorted(ALLOWED_ROLE_IDS)),
        "host_users_env": await user_items(sorted(ALLOWED_USER_IDS)),
        "admin_roles_db": await role_items(admin_roles_db),
        "admin_users_db": await user_items(admin_users_db),
        "host_roles_db": await role_items(host_roles_db),
        "host_users_db": await user_items(host_users_db),
        "status_labels": STATUS_LABELS,
    }
