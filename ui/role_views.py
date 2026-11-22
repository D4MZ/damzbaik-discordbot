"""
UI Component untuk Custom Role System (Dropdown Role).

View ini dibuat persistent (timeout=None, custom_id statis berbasis
dropdown_id di database) agar tetap berfungsi setelah bot restart.
Registrasi ulang seluruh dropdown yang tersimpan dilakukan di bot.py
saat event on_ready / setup_hook.
"""

from __future__ import annotations

import json

import discord

from database import repositories as repo
from utils.embeds import error_embed, success_embed
from utils.logger import get_logger
from utils.permissions import has_role_hierarchy_priority

logger = get_logger(__name__)


def decode_role_dropdown_config(
    raw: str, multi_select: bool
) -> tuple[list[dict], str, int, int]:
    data = json.loads(raw)
    if isinstance(data, list):
        options_data = data
        settings = {}
    else:
        options_data = data.get("options", [])
        settings = data

    placeholder = settings.get("placeholder") or "Pilih role kamu..."
    default_max = len(options_data) if multi_select else 1
    max_values = int(settings.get("max_values", default_max))
    max_values = min(max(1, max_values), max(1, len(options_data)))
    min_values = int(settings.get("min_values", 0))
    min_values = min(max(0, min_values), max_values)
    return options_data, placeholder[:150], min_values, max_values


def encode_role_dropdown_config(
    options_data: list[dict],
    *,
    placeholder: str = "Pilih role kamu...",
    min_values: int = 0,
    max_values: int | None = None,
) -> str:
    return json.dumps(
        {
            "options": options_data,
            "placeholder": placeholder[:150],
            "min_values": min_values,
            "max_values": max_values or len(options_data),
        }
    )


class RoleDropdownSelect(discord.ui.Select):
    def __init__(
        self,
        dropdown_id: int,
        options_data: list[dict],
        placeholder: str,
        min_values: int,
        max_values: int,
    ):
        self.dropdown_id = dropdown_id
        self._role_ids = [opt["role_id"] for opt in options_data]

        select_options = [
            discord.SelectOption(
                label=opt["label"],
                value=str(opt["role_id"]),
                description=opt.get("description") or None,
                emoji=opt.get("emoji") or None,
            )
            for opt in options_data
        ]
        super().__init__(
            custom_id=f"role_dropdown_select:{dropdown_id}",
            placeholder=placeholder,
            min_values=min_values,
            max_values=max_values,
            options=select_options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        assert isinstance(interaction.user, discord.Member)
        member = interaction.user
        guild = interaction.guild
        bot_member = guild.me

        selected_ids = {int(v) for v in self.values}
        all_option_ids = set(self._role_ids)

        to_add: list[discord.Role] = []
        to_remove: list[discord.Role] = []
        skipped: list[str] = []

        for role_id in all_option_ids:
            role = guild.get_role(role_id)
            if role is None:
                continue
            if not has_role_hierarchy_priority(bot_member, role):
                skipped.append(role.name)
                continue
            has_role = role in member.roles
            should_have = role_id in selected_ids
            if should_have and not has_role:
                to_add.append(role)
            elif not should_have and has_role:
                to_remove.append(role)

        try:
            if to_add:
                await member.add_roles(*to_add, reason="Role dropdown selection")
            if to_remove:
                await member.remove_roles(*to_remove, reason="Role dropdown deselection")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=error_embed(
                    "Gagal Update Role",
                    "Bot tidak memiliki izin untuk mengubah role Anda. Hubungi admin server.",
                ),
                ephemeral=True,
            )
            return

        summary_parts = []
        if to_add:
            summary_parts.append("Ditambahkan: " + ", ".join(r.name for r in to_add))
        if to_remove:
            summary_parts.append("Dihapus: " + ", ".join(r.name for r in to_remove))
        if skipped:
            summary_parts.append(
                "Dilewati (role bot lebih rendah dari role ini): " + ", ".join(skipped)
            )
        if not summary_parts:
            summary_parts.append("Tidak ada perubahan role.")

        await interaction.response.send_message(
            embed=success_embed("Role Diperbarui", "\n".join(summary_parts)),
            ephemeral=True,
        )


class RoleDropdownView(discord.ui.LayoutView):
    def __init__(
        self,
        dropdown_id: int,
        options_data: list[dict],
        multi_select: bool,
        *,
        title: str | None = None,
        description: str | None = None,
        placeholder: str = "Pilih role kamu...",
        min_values: int = 0,
        max_values: int | None = None,
    ):
        super().__init__(timeout=None)
        resolved_max = max_values or (len(options_data) if multi_select else 1)
        resolved_max = min(max(1, resolved_max), len(options_data))
        resolved_min = min(max(0, min_values), resolved_max)
        select = RoleDropdownSelect(
                dropdown_id,
                options_data,
                placeholder[:150],
                resolved_min,
                resolved_max,
            )
        content = f"**{title}**" if title else "**Pilih Role**"
        if description:
            content += f"\n\n{description}"
        container = discord.ui.Container(
            discord.ui.TextDisplay(content),
            discord.ui.ActionRow(select),
        )
        self.add_item(container)


async def build_role_dropdown_view(dropdown_row) -> RoleDropdownView:
    options_data, placeholder, min_values, max_values = decode_role_dropdown_config(
        dropdown_row.options_json, dropdown_row.multi_select
    )
    return RoleDropdownView(
        dropdown_row.id,
        options_data,
        dropdown_row.multi_select,
        title=dropdown_row.title,
        description=dropdown_row.description,
        placeholder=placeholder,
        min_values=min_values,
        max_values=max_values,
    )


async def register_all_role_dropdowns(bot: discord.Client) -> None:
    """Dipanggil sekali saat startup untuk memasang kembali seluruh persistent view."""
    dropdowns = await repo.list_all_role_dropdowns()
    for dropdown in dropdowns:
        if dropdown.message_id is None:
            continue
        try:
            view = await build_role_dropdown_view(dropdown)
            bot.add_view(view, message_id=dropdown.message_id)
        except Exception:
            logger.exception("Gagal mendaftarkan ulang role dropdown id=%s", dropdown.id)
