import discord

import database as db
from event_message import (
    cancel_event,
    refresh_event_message,
    start_event_now,
    update_event_time,
)
from event_status import STATUS_ACTIVE, STATUS_PENDING
from permissions import (
    MSG_NO_EVENT_ACCESS,
    MSG_NO_PERMISSION,
    MSG_NOT_CONFIGURED,
    is_events_enabled,
    user_can_assign_cohosts,
    user_can_manage,
    user_is_host,
)
from utils import (
    event_time_from_iso,
    format_event_time,
    parse_event_time_input,
    validate_future_time,
)


async def _deny_manage(
    interaction: discord.Interaction, event: dict | None = None
) -> None:
    if interaction.guild and not await is_events_enabled(interaction.guild.id):
        await interaction.response.send_message(MSG_NOT_CONFIGURED, ephemeral=True)
    elif (
        event is not None
        and isinstance(interaction.user, discord.Member)
        and await user_is_host(interaction.user)
        and not await user_can_manage(interaction.user, event)
    ):
        await interaction.response.send_message(MSG_NO_EVENT_ACCESS, ephemeral=True)
    else:
        await interaction.response.send_message(MSG_NO_PERMISSION, ephemeral=True)


async def _require_manage(
    interaction: discord.Interaction, event_id: int
) -> dict | None:
    event = await db.get_event(event_id)
    if not event:
        await interaction.response.send_message(
            "Ивент не найден.", ephemeral=True
        )
        return None
    if not isinstance(interaction.user, discord.Member):
        return None
    if not await user_can_manage(interaction.user, event):
        await _deny_manage(interaction, event)
        return None
    return event


class AddCoHostSelect(discord.ui.UserSelect):
    def __init__(self, event_id: int, bot: discord.Client):
        super().__init__(
            placeholder="Добавить со-хостера",
            min_values=1,
            max_values=1,
            row=0,
        )
        self.event_id = event_id
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
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
                "Назначать со-хостов может только хост ивента или админ.",
                ephemeral=True,
            )
            return

        user = self.values[0]
        if user.bot:
            await interaction.response.send_message(
                "Бота нельзя назначить со-хостом.", ephemeral=True
            )
            return
        if user.id == event["creator_id"]:
            await interaction.response.send_message(
                "Создатель ивента уже главный хост.", ephemeral=True
            )
            return

        added = await db.add_event_cohost(self.event_id, user.id)
        await refresh_event_message(self.bot, self.event_id)
        if added:
            await interaction.response.send_message(
                f"{user.mention} добавлен как со-хост.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{user.mention} уже со-хост этого ивента.", ephemeral=True
            )


class RemoveCoHostSelect(discord.ui.UserSelect):
    def __init__(self, event_id: int, bot: discord.Client):
        super().__init__(
            placeholder="Убрать со-хостера",
            min_values=1,
            max_values=1,
            row=1,
        )
        self.event_id = event_id
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
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
                "Убирать со-хостов может только хост ивента или админ.",
                ephemeral=True,
            )
            return

        user = self.values[0]
        removed = await db.remove_event_cohost(self.event_id, user.id)
        await refresh_event_message(self.bot, self.event_id)
        if removed:
            await interaction.response.send_message(
                f"{user.mention} убран из со-хостов.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Этот пользователь не был со-хостом.", ephemeral=True
            )


class CoHostManageView(discord.ui.View):
    def __init__(self, event_id: int, bot: discord.Client):
        super().__init__(timeout=180)
        self.event_id = event_id
        self.bot = bot
        self.add_item(AddCoHostSelect(event_id, bot))
        self.add_item(RemoveCoHostSelect(event_id, bot))


class EditTimeModal(discord.ui.Modal, title="Изменить время"):
    new_time = discord.ui.TextInput(
        label="Новое время (МСК)",
        placeholder="ЧЧ:ММ или ДД.ММ.ГГГГ ЧЧ:ММ",
        max_length=32,
        required=True,
    )

    def __init__(self, event_id: int, bot: discord.Client):
        super().__init__()
        self.event_id = event_id
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        if await _require_manage(interaction, self.event_id) is None:
            return
        try:
            event_dt = parse_event_time_input(self.new_time.value)
            validate_future_time(event_dt)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        time_label = await update_event_time(self.bot, self.event_id, event_dt)
        await interaction.response.send_message(
            f"Время обновлено: {time_label}", ephemeral=True
        )


class PostponeModal(discord.ui.Modal, title="Перенести ивент"):
    new_time = discord.ui.TextInput(
        label="Новое время (МСК)",
        placeholder="ЧЧ:ММ или ДД.ММ.ГГГГ ЧЧ:ММ",
        max_length=32,
        required=True,
    )
    reason = discord.ui.TextInput(
        label="Причина (необязательно)",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=False,
    )

    def __init__(self, event_id: int, bot: discord.Client):
        super().__init__()
        self.event_id = event_id
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        if await _require_manage(interaction, self.event_id) is None:
            return
        try:
            event_dt = parse_event_time_input(self.new_time.value)
            validate_future_time(event_dt)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        reason_text = self.reason.value.strip() if self.reason.value else None
        time_label = await update_event_time(
            self.bot,
            self.event_id,
            event_dt,
            notify=True,
            reason=reason_text,
        )
        await interaction.response.send_message(
            f"Ивент перенесён на {time_label}. Участники уведомлены.",
            ephemeral=True,
        )


class EditInfoModal(discord.ui.Modal, title="Изменить информацию"):
    def __init__(self, event_id: int, bot: discord.Client, event: dict):
        super().__init__()
        self.event_id = event_id
        self.bot = bot
        self.title_input = discord.ui.TextInput(
            label="Название",
            default=event["title"],
            max_length=256,
            required=True,
        )
        self.description_input = discord.ui.TextInput(
            label="Описание",
            style=discord.TextStyle.paragraph,
            default=event["description"],
            max_length=2000,
            required=True,
        )
        self.mode_input = discord.ui.TextInput(
            label="Режим Roblox",
            default=event["roblox_mode"],
            max_length=128,
            required=True,
        )
        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.mode_input)

    async def on_submit(self, interaction: discord.Interaction):
        if await _require_manage(interaction, self.event_id) is None:
            return
        await db.update_event(
            self.event_id,
            title=self.title_input.value,
            description=self.description_input.value,
            roblox_mode=self.mode_input.value,
        )
        await refresh_event_message(self.bot, self.event_id)
        await interaction.response.send_message(
            "Информация об ивенте обновлена.", ephemeral=True
        )


class EventView(discord.ui.View):
    def __init__(self, event_id: int):
        super().__init__(timeout=None)
        self.event_id = event_id

    @discord.ui.button(
        label="Уведомить в ЛС",
        style=discord.ButtonStyle.primary,
        custom_id="event_notify_placeholder",
        row=0,
    )
    async def notify_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        event = await db.get_event(self.event_id)
        if not event:
            await interaction.response.send_message(
                "Это объявление больше не активно.", ephemeral=True
            )
            return

        if event.get("status") != STATUS_PENDING:
            await interaction.response.send_message(
                "Ивент уже начался или отменён.", ephemeral=True
            )
            return

        subscribed = await db.is_subscribed(self.event_id, interaction.user.id)
        if subscribed:
            await db.remove_subscriber(self.event_id, interaction.user.id)
            await interaction.response.send_message(
                "Уведомление в ЛС отключено.", ephemeral=True
            )
        else:
            added = await db.add_subscriber(self.event_id, interaction.user.id)
            if added:
                try:
                    dm = await interaction.user.create_dm()
                    when = format_event_time(
                        event_time_from_iso(event["event_time"])
                    )
                    await dm.send(
                        f"Вы подписались на ивент **{event['title']}**. "
                        f"Напишу в ЛС, когда он начнётся — {when}."
                    )
                except discord.Forbidden:
                    await db.remove_subscriber(self.event_id, interaction.user.id)
                    await interaction.response.send_message(
                        "Не удалось отправить ЛС. Откройте личные сообщения от участников сервера.",
                        ephemeral=True,
                    )
                    return
                await interaction.response.send_message(
                    "Вы получите уведомление в ЛС при начале ивента.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Вы уже подписаны на этот ивент.", ephemeral=True
                )

        await refresh_event_message(interaction.client, self.event_id)

    @discord.ui.button(
        label="Начать ивент сейчас",
        style=discord.ButtonStyle.danger,
        custom_id="event_start_now_placeholder",
        row=0,
    )
    async def start_now_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Доступно только на сервере.", ephemeral=True
            )
            return

        event = await db.get_event(self.event_id)
        if not event:
            await interaction.response.send_message(
                "Ивент не найден.", ephemeral=True
            )
            return

        if event.get("status") != STATUS_PENDING:
            await interaction.response.send_message(
                "Ивент уже завершён или отменён.", ephemeral=True
            )
            return

        if not await user_can_manage(interaction.user, event):
            await _deny_manage(interaction, event)
            return

        started = await start_event_now(interaction.client, self.event_id, manual=True)
        if started:
            await interaction.response.send_message(
                "Ивент запущен досрочно. Подписчики получили ЛС, хостам отправлено приватное сообщение на 5 минут.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "Не удалось запустить ивент.", ephemeral=True
            )

    @discord.ui.select(
        placeholder="Управление ивентом",
        min_values=1,
        max_values=1,
        options=[
            discord.SelectOption(
                label="Изменить время",
                value="edit_time",
                description="ЧЧ:ММ или ДД.ММ.ГГГГ ЧЧ:ММ (МСК)",
            ),
            discord.SelectOption(
                label="Перенести ивент",
                value="postpone",
                description="Новое время + уведомление",
            ),
            discord.SelectOption(
                label="Изменить информацию",
                value="edit_info",
                description="Название, описание, режим",
            ),
            discord.SelectOption(
                label="Со-хостеры",
                value="cohosts",
                description="Назначить помощников",
            ),
            discord.SelectOption(
                label="Отменить ивент",
                value="cancel",
                description="Закрыть объявление",
            ),
        ],
        custom_id="event_manage_placeholder",
        row=1,
    )
    async def manage_select(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Доступно только на сервере.", ephemeral=True
            )
            return

        event = await db.get_event(self.event_id)
        if not event:
            await interaction.response.send_message(
                "Ивент не найден.", ephemeral=True
            )
            return

        status = event.get("status", STATUS_PENDING)
        if status not in (STATUS_PENDING, STATUS_ACTIVE):
            await interaction.response.send_message(
                "Ивент уже завершён или отменён.", ephemeral=True
            )
            return

        if not await user_can_manage(interaction.user, event):
            await _deny_manage(interaction, event)
            return

        action = select.values[0]
        bot = interaction.client

        if action == "cohosts":
            if not await user_can_assign_cohosts(interaction.user, event):
                await interaction.response.send_message(
                    "Назначать со-хостов может только хост ивента или админ.",
                    ephemeral=True,
                )
                return
            cohosts = await db.get_event_cohosts(self.event_id)
            if cohosts:
                list_text = " ".join(f"<@{uid}>" for uid in cohosts)
            else:
                list_text = "нет"
            await interaction.response.send_message(
                f"Со-хостеры: {list_text}\nВыберите участника ниже.",
                view=CoHostManageView(self.event_id, bot),
                ephemeral=True,
            )
            return

        if action == "edit_time":
            await interaction.response.send_modal(EditTimeModal(self.event_id, bot))
        elif action == "postpone":
            await interaction.response.send_modal(PostponeModal(self.event_id, bot))
        elif action == "edit_info":
            await interaction.response.send_modal(
                EditInfoModal(self.event_id, bot, event)
            )
        elif action == "cancel":
            if await cancel_event(bot, self.event_id):
                await interaction.response.send_message(
                    "Ивент отменён.", ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    "Не удалось отменить ивент.", ephemeral=True
                )


def make_event_view(event_id: int) -> EventView:
    view = EventView(event_id)
    view.notify_button.custom_id = f"event_notify_{event_id}"
    view.start_now_button.custom_id = f"event_start_now_{event_id}"
    view.manage_select.custom_id = f"event_manage_{event_id}"
    return view
