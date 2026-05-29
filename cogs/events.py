import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

import database as db
from event_message import cancel_event, refresh_event_message, update_event_time
from event_status import FINISHED_STATUSES, STATUS_ACTIVE, STATUS_PENDING
from list_views import (
    build_events_list_embed,
    make_end_event_view,
    make_events_list_view,
)
from config import (
    ADMIN_ROLE_IDS,
    ADMIN_USER_IDS,
    ALLOWED_ROLE_IDS,
    ALLOWED_USER_IDS,
)
from permissions import (
    MSG_NOT_CONFIGURED,
    MSG_NO_PERMISSION,
    is_events_enabled,
    user_can_create,
    user_can_manage,
)
from utils import (
    allowed_mentions_for_role,
    build_event_embed,
    build_message_link,
    event_time_to_iso,
    format_event_time,
    format_role_ping_from_role,
    parse_event_time_input,
    parse_message_reference,
    resolve_ping_role,
    validate_future_time,
    validate_ping_role,
)
from views import make_event_view


class EventsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    event_group = app_commands.Group(
        name="ивент",
        description="Управление объявлениями об ивентах",
    )

    async def _resolve_event(self, ref: str) -> tuple[dict | None, str | None]:
        try:
            message_id, _ = parse_message_reference(ref)
        except ValueError as e:
            return None, str(e)
        event = await db.get_event_by_message(message_id)
        if not event:
            return None, "Объявление не найдено."
        return event, None

    @event_group.command(name="создать", description="Создать объявление об ивенте")
    @app_commands.describe(
        название="Название ивента",
        описание="Описание ивента",
        режим="Название режима в Roblox",
        время="Время по МСК: ЧЧ:ММ (сегодня) или ДД.ММ.ГГГГ ЧЧ:ММ",
        роль="Роль для упоминания в объявлении",
    )
    async def create_event(
        self,
        interaction: discord.Interaction,
        название: str,
        описание: str,
        режим: str,
        время: str,
        роль: discord.Role,
    ):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return

        if not await is_events_enabled(interaction.guild.id):
            await interaction.response.send_message(
                MSG_NOT_CONFIGURED, ephemeral=True
            )
            return

        if not await user_can_create(interaction.user):
            await interaction.response.send_message(
                MSG_NO_PERMISSION, ephemeral=True
            )
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "Создавать ивент можно только в текстовом канале.",
                ephemeral=True,
            )
            return

        ping_role = resolve_ping_role(interaction.guild, роль)
        role_error = validate_ping_role(
            ping_role, interaction.guild, interaction.channel
        )
        if role_error:
            await interaction.response.send_message(role_error, ephemeral=True)
            return

        try:
            event_dt = parse_event_time_input(время)
            validate_future_time(event_dt)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        await interaction.response.defer()

        formatted_time = format_event_time(event_dt)
        time_iso = event_time_to_iso(event_dt)
        embed = build_event_embed(
            title=название,
            description=описание,
            roblox_mode=режим,
            event_time=formatted_time,
            creator=interaction.user,
        )

        ping = format_role_ping_from_role(ping_role)
        try:
            message = await interaction.followup.send(
                content=f"{ping} Новый ивент!",
                embed=embed,
                allowed_mentions=allowed_mentions_for_role(
                    interaction.guild.id, ping_role.id
                ),
                wait=True,
            )
        except discord.HTTPException as e:
            await interaction.followup.send(
                "Не удалось отправить объявление. "
                "Проверьте права бота и настройки роли для упоминания.\n"
                f"Discord: {e}",
                ephemeral=True,
            )
            return

        event_id = await db.create_event(
            guild_id=interaction.guild.id,
            channel_id=interaction.channel.id,
            message_id=message.id,
            title=название,
            description=описание,
            roblox_mode=режим,
            event_time=time_iso,
            role_id=ping_role.id,
            creator_id=interaction.user.id,
        )

        view = make_event_view(event_id)
        try:
            await message.edit(view=view)
            self.bot.add_view(view)
        except discord.HTTPException:
            await interaction.followup.send(
                "Объявление отправлено, но кнопки не прикрепились. "
                "Проверьте право «Использовать внешние эмодзи» / компоненты.",
                ephemeral=True,
            )

    @event_group.command(
        name="список",
        description="Список ивентов: активные, завершённые, предстоящие",
    )
    @app_commands.describe(
        категория="Какие ивенты показать",
    )
    @app_commands.choices(
        категория=[
            app_commands.Choice(name="Сейчас проходят", value="active"),
            app_commands.Choice(name="Завершённые", value="finished"),
            app_commands.Choice(name="Предстоящие", value="pending"),
        ]
    )
    async def list_events(
        self,
        interaction: discord.Interaction,
        категория: app_commands.Choice[str],
    ):
        if not interaction.guild:
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return

        if категория.value == "active":
            statuses = (STATUS_ACTIVE,)
            label = "Сейчас проходят"
        elif категория.value == "finished":
            statuses = FINISHED_STATUSES
            label = "Завершённые"
        else:
            statuses = (STATUS_PENDING,)
            label = "Предстоящие"

        events = await db.get_events_by_status(interaction.guild.id, statuses)
        embed = build_events_list_embed(events, label)
        view = make_events_list_view(events, self.bot)
        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True,
        )

    @event_group.command(
        name="отменить", description="Отменить ивент по сообщению объявления"
    )
    @app_commands.describe(
        сообщение="Ссылка на сообщение или его ID"
    )
    async def cancel_event(
        self,
        interaction: discord.Interaction,
        сообщение: str,
    ):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return

        try:
            message_id, _ = parse_message_reference(сообщение)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        event = await db.get_event_by_message(message_id)
        if not event:
            await interaction.response.send_message(
                "Объявление не найдено.", ephemeral=True
            )
            return

        if not await user_can_manage(interaction.user, event):
            await interaction.response.send_message(
                "Недостаточно прав.", ephemeral=True
            )
            return

        if await cancel_event(self.bot, event["id"]):
            await interaction.response.send_message("Ивент отменён.", ephemeral=True)
        else:
            await interaction.response.send_message(
                "Не удалось отменить ивент.", ephemeral=True
            )

    @event_group.command(
        name="перенос",
        description="Перенести ивент с уведомлением",
    )
    @app_commands.describe(
        сообщение="Ссылка на объявление или ID сообщения",
        время="Новое время по МСК: ЧЧ:ММ (сегодня) или ДД.ММ.ГГГГ ЧЧ:ММ",
        причина="Причина переноса (необязательно)",
    )
    async def postpone_event(
        self,
        interaction: discord.Interaction,
        сообщение: str,
        время: str,
        причина: str | None = None,
    ):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return

        event, err = await self._resolve_event(сообщение)
        if err:
            await interaction.response.send_message(err, ephemeral=True)
            return

        if not await user_can_manage(interaction.user, event):
            await interaction.response.send_message(
                MSG_NO_PERMISSION, ephemeral=True
            )
            return

        try:
            event_dt = parse_event_time_input(время)
            validate_future_time(event_dt)
        except ValueError as e:
            await interaction.response.send_message(str(e), ephemeral=True)
            return

        reason = причина.strip() if причина else None
        time_label = await update_event_time(
            self.bot,
            event["id"],
            event_dt,
            notify=True,
            reason=reason,
        )
        await interaction.response.send_message(
            f"Ивент перенесён на {time_label}. Участники уведомлены.",
            ephemeral=True,
        )

    @event_group.command(
        name="завершить",
        description="Завершить ивент, который идёт сейчас",
    )
    async def finish_event(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return

        active = await db.get_events_by_status(
            interaction.guild.id, (STATUS_ACTIVE,)
        )
        manageable = []
        for event in active:
            if await user_can_manage(interaction.user, event):
                manageable.append(event)

        if not manageable:
            await interaction.response.send_message(
                "Нет активных ивентов, которые вы можете завершить.",
                ephemeral=True,
            )
            return

        view = make_end_event_view(manageable, self.bot)
        await interaction.response.send_message(
            "Выберите ивент для завершения:",
            view=view,
            ephemeral=True,
        )

    @event_group.command(
        name="организаторы",
        description="Список хостеров и админов ивентов",
    )
    @app_commands.default_permissions(administrator=True)
    async def list_organizers(self, interaction: discord.Interaction):
        if not interaction.guild:
            await interaction.response.send_message(
                "Команда доступна только на сервере.", ephemeral=True
            )
            return

        host_roles = await db.get_manager_roles(interaction.guild.id)
        host_users = await db.get_manager_users(interaction.guild.id)
        admin_roles = await db.get_admin_roles(interaction.guild.id)
        admin_users = await db.get_admin_users(interaction.guild.id)
        enabled = await is_events_enabled(interaction.guild.id)

        if not enabled:
            await interaction.response.send_message(
                "Хостеры и админы не назначены. Ивенты отключены.",
                ephemeral=True,
            )
            return

        lines = []

        lines.append("**Админы ивентов** (все ивенты):")
        lines.append(
            "_Также: участники с правом «Администратор» на сервере Discord._"
        )
        if ADMIN_ROLE_IDS or ADMIN_USER_IDS:
            lines.append("_Из .env:_")
            for role_id in sorted(ADMIN_ROLE_IDS):
                role = interaction.guild.get_role(role_id)
                lines.append(role.mention if role else f"роль `{role_id}`")
            for user_id in sorted(ADMIN_USER_IDS):
                lines.append(f"<@{user_id}>")
        for role_id in admin_roles:
            role = interaction.guild.get_role(role_id)
            lines.append(role.mention if role else f"`{role_id}`")
        for user_id in admin_users:
            lines.append(f"<@{user_id}>")
        if not (
            ADMIN_ROLE_IDS
            or ADMIN_USER_IDS
            or admin_roles
            or admin_users
        ):
            lines.append("_только через права Discord_")

        lines.append("")
        lines.append("**Ивент-хостеры** (свои ивенты + со-хостеры):")
        if ALLOWED_ROLE_IDS or ALLOWED_USER_IDS:
            lines.append("_Из .env:_")
            for role_id in sorted(ALLOWED_ROLE_IDS):
                role = interaction.guild.get_role(role_id)
                lines.append(role.mention if role else f"роль `{role_id}`")
            for user_id in sorted(ALLOWED_USER_IDS):
                lines.append(f"<@{user_id}>")
        for role_id in host_roles:
            role = interaction.guild.get_role(role_id)
            lines.append(role.mention if role else f"`{role_id}`")
        for user_id in host_users:
            lines.append(f"<@{user_id}>")
        if not (
            ALLOWED_ROLE_IDS
            or ALLOWED_USER_IDS
            or host_roles
            or host_users
        ):
            lines.append("_не назначены_")

        await interaction.response.send_message(
            "\n".join(lines), ephemeral=True
        )

    async def cog_app_command_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ):
        logger.exception("Ошибка slash-команды", exc_info=error)
        text = "Произошла ошибка при выполнении команды."
        if isinstance(error, app_commands.CommandInvokeError) and error.original:
            orig = error.original
            if isinstance(orig, discord.HTTPException):
                text = (
                    "Discord отклонил действие. Проверьте права бота и роль для пинга."
                )
            elif isinstance(orig, ValueError):
                text = str(orig)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(text, ephemeral=True)
            else:
                await interaction.response.send_message(text, ephemeral=True)
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(EventsCog(bot))
