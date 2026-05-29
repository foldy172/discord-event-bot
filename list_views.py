import discord

import database as db
from event_message import cancel_event, end_event, start_event_now
from event_status import (
    FINISHED_STATUSES,
    STATUS_ACTIVE,
    STATUS_CANCELLED,
    STATUS_ENDED,
    STATUS_PENDING,
)
from permissions import (
    MSG_NO_EVENT_ACCESS,
    user_can_assign_cohosts,
    user_can_manage,
)
from utils import (
    build_message_link,
    event_status_label,
    event_time_from_iso,
    format_event_time,
)
from views import CoHostManageView


def _event_option_label(event: dict) -> str:
    title = event["title"][:80]
    status = event_status_label(event.get("status", STATUS_PENDING))
    return f"#{event['id']} {title} — {status}"


def build_events_list_embed(events: list[dict], category_label: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"Ивенты: {category_label}",
        color=0x5865F2,
    )
    if not events:
        embed.description = "Нет ивентов в этой категории."
        return embed

    lines = []
    for event in events[:25]:
        when = format_event_time(event_time_from_iso(event["event_time"]))
        link = build_message_link(
            event["guild_id"], event["channel_id"], event["message_id"]
        )
        status = event_status_label(event.get("status", STATUS_PENDING))
        lines.append(
            f"**#{event['id']} {event['title']}** — {status}\n"
            f"Время: {when}\n"
            f"[Открыть объявление]({link})"
        )
    embed.description = "\n\n".join(lines)
    if len(events) > 25:
        embed.set_footer(text=f"Показаны первые 25 из {len(events)}")
    return embed


class EventPickSelect(discord.ui.Select):
    def __init__(self, events: list[dict], bot: discord.Client):
        self.bot = bot
        options = []
        for event in events[:25]:
            options.append(
                discord.SelectOption(
                    label=_event_option_label(event)[:100],
                    value=str(event["id"]),
                    description=event["roblox_mode"][:100],
                )
            )
        super().__init__(
            placeholder="Выберите ивент для управления",
            min_values=1,
            max_values=1,
            options=options,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        event = await db.get_event(int(self.values[0]))
        if not event or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Ивент не найден.", ephemeral=True
            )
            return

        can_manage = await user_can_manage(interaction.user, event)
        can_cohosts = await user_can_assign_cohosts(interaction.user, event)
        embed = _build_event_panel_embed(event, can_manage)
        view = EventPanelView(
            event,
            self.bot,
            can_manage=can_manage,
            can_cohosts=can_cohosts,
        )
        await interaction.response.send_message(
            embed=embed, view=view, ephemeral=True
        )


class EventPanelView(discord.ui.View):
    def __init__(
        self,
        event: dict,
        bot: discord.Client,
        *,
        can_manage: bool,
        can_cohosts: bool,
    ):
        super().__init__(timeout=300)
        self.event_id = event["id"]
        self.event = event
        self.bot = bot
        self.can_manage = can_manage
        self.can_cohosts = can_cohosts
        status = event.get("status", STATUS_PENDING)

        link = build_message_link(
            event["guild_id"], event["channel_id"], event["message_id"]
        )
        self.add_item(
            discord.ui.Button(
                label="Открыть объявление",
                style=discord.ButtonStyle.link,
                url=link,
                row=0,
            )
        )

        row = 1
        if can_manage and status == STATUS_PENDING:
            start = discord.ui.Button(
                label="Начать сейчас",
                style=discord.ButtonStyle.danger,
                row=row,
            )
            start.callback = self._start_callback
            self.add_item(start)

        if can_manage and status == STATUS_ACTIVE:
            end = discord.ui.Button(
                label="Завершить",
                style=discord.ButtonStyle.success,
                row=row,
            )
            end.callback = self._end_callback
            self.add_item(end)
            row = 2

        if can_manage and status in (STATUS_PENDING, STATUS_ACTIVE):
            cancel = discord.ui.Button(
                label="Отменить",
                style=discord.ButtonStyle.secondary,
                row=row,
            )
            cancel.callback = self._cancel_callback
            self.add_item(cancel)

        if can_cohosts and status in (STATUS_PENDING, STATUS_ACTIVE):
            cohosts = discord.ui.Button(
                label="Со-хостеры",
                style=discord.ButtonStyle.primary,
                row=row,
            )
            cohosts.callback = self._cohosts_callback
            self.add_item(cohosts)

    async def _ensure_manage(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        event = await db.get_event(self.event_id)
        if not event:
            await interaction.response.send_message(
                "Ивент не найден.", ephemeral=True
            )
            return False
        if not await user_can_manage(interaction.user, event):
            await interaction.response.send_message(
                "Недостаточно прав для этого ивента.", ephemeral=True
            )
            return False
        return True

    async def _start_callback(self, interaction: discord.Interaction):
        if not await self._ensure_manage(interaction):
            return
        if await start_event_now(self.bot, self.event_id, manual=True):
            await interaction.response.send_message(
                "Ивент запущен.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Не удалось запустить.", ephemeral=True
            )

    async def _end_callback(self, interaction: discord.Interaction):
        if not await self._ensure_manage(interaction):
            return
        if await end_event(self.bot, self.event_id):
            await interaction.response.send_message(
                "Ивент завершён.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Не удалось завершить.", ephemeral=True
            )

    async def _cancel_callback(self, interaction: discord.Interaction):
        if not await self._ensure_manage(interaction):
            return
        if await cancel_event(self.bot, self.event_id):
            await interaction.response.send_message(
                "Ивент отменён.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Не удалось отменить.", ephemeral=True
            )

    async def _cohosts_callback(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            return
        event = await db.get_event(self.event_id)
        if not event:
            await interaction.response.send_message(
                "Ивент не найден.", ephemeral=True
            )
            return
        if not await user_can_assign_cohosts(interaction.user, event):
            await interaction.response.send_message(
                "Назначать со-хостов может только хост или админ.",
                ephemeral=True,
            )
            return
        cohost_ids = await db.get_event_cohosts(self.event_id)
        list_text = " ".join(f"<@{uid}>" for uid in cohost_ids) if cohost_ids else "нет"
        await interaction.response.send_message(
            f"Со-хостеры: {list_text}",
            view=CoHostManageView(self.event_id, self.bot),
            ephemeral=True,
        )


def _build_event_panel_embed(event: dict, can_manage: bool) -> discord.Embed:
    status = event_status_label(event.get("status", STATUS_PENDING))
    when = format_event_time(event_time_from_iso(event["event_time"]))
    link = build_message_link(
        event["guild_id"], event["channel_id"], event["message_id"]
    )
    embed = discord.Embed(
        title=f"#{event['id']} {event['title']}",
        description=event["description"],
        color=0x5865F2,
    )
    embed.add_field(name="Статус", value=status, inline=True)
    embed.add_field(name="Режим", value=event["roblox_mode"], inline=True)
    embed.add_field(name="Время", value=when, inline=False)
    embed.add_field(
        name="Права",
        value="Можете управлять" if can_manage else "Только просмотр",
        inline=False,
    )
    embed.add_field(name="Объявление", value=f"[Перейти]({link})", inline=False)
    return embed


class EventsListView(discord.ui.View):
    def __init__(self, events: list[dict], bot: discord.Client):
        super().__init__(timeout=300)
        if events:
            self.add_item(EventPickSelect(events, bot))


def make_events_list_view(
    events: list[dict], bot: discord.Client
) -> EventsListView | None:
    if not events:
        return None
    return EventsListView(events, bot)


class EndEventSelect(discord.ui.Select):
    def __init__(self, events: list[dict], bot: discord.Client):
        options = []
        for event in events[:25]:
            label = f"#{event['id']} {event['title']}"[:100]
            options.append(
                discord.SelectOption(
                    label=label,
                    value=str(event["id"]),
                )
            )
        super().__init__(
            placeholder="Выберите ивент",
            min_values=1,
            max_values=1,
            options=options,
        )
        self._events = {str(e["id"]): e for e in events}
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Доступно только на сервере.", ephemeral=True
            )
            return

        event = self._events.get(self.values[0])
        if not event:
            await interaction.response.send_message(
                "Ивент не найден.", ephemeral=True
            )
            return

        if not await user_can_manage(interaction.user, event):
            await interaction.response.send_message(
                MSG_NO_EVENT_ACCESS, ephemeral=True
            )
            return

        if await end_event(self.bot, event["id"]):
            await interaction.response.edit_message(
                content=f"Ивент **{event['title']}** завершён.",
                view=None,
            )
        else:
            await interaction.response.send_message(
                "Не удалось завершить ивент (возможно, он уже завершён).",
                ephemeral=True,
            )


class EndEventView(discord.ui.View):
    def __init__(self, events: list[dict], bot: discord.Client):
        super().__init__(timeout=120)
        self.add_item(EndEventSelect(events, bot))


def make_end_event_view(
    events: list[dict], bot: discord.Client
) -> EndEventView:
    return EndEventView(events, bot)
