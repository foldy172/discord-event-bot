import discord

import database as db
from config import ALLOWED_ROLE_IDS, ALLOWED_USER_IDS
from permissions import user_can_manage_organizers


async def _require_organizer_admin(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    if not await user_can_manage_organizers(interaction.user):
        await interaction.response.send_message(
            "Управлять организаторами могут администраторы сервера и админы ивентов.",
            ephemeral=True,
        )
        return False
    return True


def _role_line(guild: discord.Guild, role_id: int) -> str:
    role = guild.get_role(role_id)
    return role.mention if role else f"`{role_id}`"


async def format_organizers_list_text(guild: discord.Guild) -> str:
    guild_id = guild.id
    host_roles = await db.get_manager_roles(guild_id)
    host_users = await db.get_manager_users(guild_id)

    lines = [
        "Ивент-хостеры — могут создавать ивенты (/ивент создать) и назначать со-хостов на своих ивентах.",
        "",
        "——— Из .env (удалить только вручную в .env) ———",
    ]
    if ALLOWED_ROLE_IDS or ALLOWED_USER_IDS:
        for role_id in sorted(ALLOWED_ROLE_IDS):
            lines.append(f"Роль: {_role_line(guild, role_id)}")
        for user_id in sorted(ALLOWED_USER_IDS):
            lines.append(f"Пользователь: <@{user_id}>")
    else:
        lines.append("(не задано)")

    lines.append("")
    lines.append("——— Добавлены через бота ———")
    if host_roles or host_users:
        for role_id in host_roles:
            lines.append(f"Роль: {_role_line(guild, role_id)}")
        for user_id in host_users:
            member = guild.get_member(user_id)
            name = member.display_name if member else str(user_id)
            lines.append(f"Пользователь: {name} (<@{user_id}>)")
    else:
        lines.append("(пока никого)")

    lines.append("")
    lines.append("Удаление: выпадающий список «Удалить» на панели (только записи из бота).")
    return "\n".join(lines)


async def build_organizers_embed(guild: discord.Guild) -> discord.Embed:
    guild_id = guild.id
    host_roles = await db.get_manager_roles(guild_id)
    host_users = await db.get_manager_users(guild_id)

    embed = discord.Embed(
        title="Организаторы ивентов",
        description=(
            "Ниже — кто может **создавать** ивенты. "
            "Добавьте пользователя или роль, откройте список в модальном окне или удалите запись из базы."
        ),
        color=0x00D4FF,
    )

    env_lines: list[str] = []
    for role_id in sorted(ALLOWED_ROLE_IDS):
        env_lines.append(_role_line(guild, role_id))
    for user_id in sorted(ALLOWED_USER_IDS):
        env_lines.append(f"<@{user_id}>")
    embed.add_field(
        name="Из .env",
        value="\n".join(env_lines) if env_lines else "_не задано_",
        inline=False,
    )

    db_lines: list[str] = []
    for role_id in host_roles:
        db_lines.append(f"🎭 {_role_line(guild, role_id)}")
    for user_id in host_users:
        db_lines.append(f"👤 <@{user_id}>")
    embed.add_field(
        name="Через бота",
        value="\n".join(db_lines) if db_lines else "_пока никого — добавьте ниже_",
        inline=False,
    )
    embed.set_footer(text="Админы ивентов (.env / Discord Admin) тоже могут создавать ивенты.")
    return embed


async def build_remove_options(
    guild: discord.Guild,
) -> list[discord.SelectOption]:
    guild_id = guild.id
    options: list[discord.SelectOption] = []
    for user_id in await db.get_manager_users(guild_id):
        member = guild.get_member(user_id)
        label = (member.display_name if member else f"ID {user_id}")[:100]
        options.append(
            discord.SelectOption(
                label=label,
                value=f"u:{user_id}",
                description="Пользователь",
                emoji="👤",
            )
        )
    for role_id in await db.get_manager_roles(guild_id):
        role = guild.get_role(role_id)
        label = (role.name if role else f"ID {role_id}")[:100]
        options.append(
            discord.SelectOption(
                label=label,
                value=f"r:{role_id}",
                description="Роль",
                emoji="🎭",
            )
        )
    return options[:25]


async def refresh_organizers_message(
    interaction: discord.Interaction,
    *,
    notice: str | None = None,
) -> None:
    if not interaction.guild:
        return
    embed = await build_organizers_embed(interaction.guild)
    view = await make_organizers_panel_view(interaction.guild, interaction.client)
    if interaction.response.is_done():
        await interaction.edit_original_response(embed=embed, view=view)
    else:
        await interaction.response.edit_message(embed=embed, view=view)
    if notice:
        await interaction.followup.send(notice, ephemeral=True)


class OrganizersListModal(discord.ui.Modal, title="Список организаторов"):
    listing = discord.ui.TextInput(
        label="Ивент-хостеры",
        style=discord.TextStyle.paragraph,
        max_length=4000,
        required=False,
    )

    def __init__(self, text: str):
        super().__init__()
        self.listing.default = text[:4000]

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "Для удаления выберите запись в списке **«Удалить организатора»** на панели.",
            ephemeral=True,
        )


class AddOrganizerUserSelect(discord.ui.UserSelect):
    def __init__(self, guild_id: int):
        super().__init__(
            placeholder="Добавить пользователя (может создавать ивенты)",
            min_values=1,
            max_values=1,
            row=0,
        )
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        if not await _require_organizer_admin(interaction):
            return
        user = self.values[0]
        if user.bot:
            await interaction.response.send_message(
                "Бота нельзя назначить организатором.", ephemeral=True
            )
            return
        added = await db.add_manager_user(self.guild_id, user.id)
        await interaction.response.defer(ephemeral=True)
        notice = (
            f"{user.mention} добавлен как ивент-хостер."
            if added
            else f"{user.mention} уже в списке организаторов."
        )
        await refresh_organizers_message(interaction, notice=notice)


class AddOrganizerRoleSelect(discord.ui.RoleSelect):
    def __init__(self, guild_id: int):
        super().__init__(
            placeholder="Добавить роль (все с ролью могут создавать ивенты)",
            min_values=1,
            max_values=1,
            row=1,
        )
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        if not await _require_organizer_admin(interaction):
            return
        role = self.values[0]
        if role.is_default():
            await interaction.response.send_message(
                "Роль @everyone нельзя назначить.", ephemeral=True
            )
            return
        added = await db.add_manager_role(self.guild_id, role.id)
        await interaction.response.defer(ephemeral=True)
        notice = (
            f"Роль {role.mention} добавлена — её участники могут создавать ивенты."
            if added
            else f"Роль {role.mention} уже в списке."
        )
        await refresh_organizers_message(interaction, notice=notice)


class RemoveOrganizerSelect(discord.ui.Select):
    def __init__(
        self,
        guild_id: int,
        options: list[discord.SelectOption],
    ):
        self.guild_id = guild_id
        if options:
            super().__init__(
                placeholder="Удалить организатора",
                min_values=1,
                max_values=1,
                options=options,
                row=2,
            )
        else:
            super().__init__(
                placeholder="Некого удалять (добавьте через меню выше)",
                min_values=1,
                max_values=1,
                options=[
                    discord.SelectOption(
                        label="—",
                        value="_none",
                        description="Нет записей в базе",
                    )
                ],
                row=2,
                disabled=True,
            )
        self._has_removable = bool(options)

    async def callback(self, interaction: discord.Interaction):
        if not self._has_removable:
            await interaction.response.send_message(
                "Сначала добавьте организатора через меню выше. Записи из .env удаляются только вручную.",
                ephemeral=True,
            )
            return
        if not await _require_organizer_admin(interaction):
            return

        raw = self.values[0]
        kind, _, id_str = raw.partition(":")
        entity_id = int(id_str)

        if kind == "u":
            removed = await db.remove_manager_user(self.guild_id, entity_id)
            notice = (
                f"<@{entity_id}> убран из организаторов."
                if removed
                else "Пользователь не найден в списке."
            )
        elif kind == "r":
            removed = await db.remove_manager_role(self.guild_id, entity_id)
            role = interaction.guild.get_role(entity_id) if interaction.guild else None
            label = role.mention if role else f"роль `{entity_id}`"
            notice = (
                f"{label} убрана из организаторов."
                if removed
                else "Роль не найдена в списке."
            )
        else:
            await interaction.response.send_message("Неизвестная запись.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        await refresh_organizers_message(interaction, notice=notice)


class OrganizersPanelView(discord.ui.View):
    def __init__(
        self,
        guild_id: int,
        remove_options: list[discord.SelectOption],
    ):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.add_item(AddOrganizerUserSelect(guild_id))
        self.add_item(AddOrganizerRoleSelect(guild_id))
        self.add_item(RemoveOrganizerSelect(guild_id, remove_options))

    @discord.ui.button(
        label="Список",
        style=discord.ButtonStyle.secondary,
        emoji="📋",
        row=3,
    )
    async def show_list(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not interaction.guild:
            return
        if not await _require_organizer_admin(interaction):
            return
        text = await format_organizers_list_text(interaction.guild)
        await interaction.response.send_modal(OrganizersListModal(text))


async def make_organizers_panel_view(
    guild: discord.Guild,
    bot: discord.Client,
) -> OrganizersPanelView:
    options = await build_remove_options(guild)
    return OrganizersPanelView(guild.id, options)
