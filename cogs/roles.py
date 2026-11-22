"""Cog: Role System sederhana (dropdown role, reaction role, autorole)."""

from __future__ import annotations

import re

import discord
from discord import app_commands
from discord.ext import commands

from database import repositories as repo
from ui.role_views import RoleDropdownView, encode_role_dropdown_config
from utils.components import build_plain_container
from utils.logger import get_logger
from utils.permissions import has_role_hierarchy_priority, require_permissions

logger = get_logger(__name__)

role_group = app_commands.Group(name="role", description="Buat panel role untuk member.")
# "🎮 @Gamer 🎨 @Artist" -> [("🎮", id), ("🎨", id)]; spasi antara emoji dan role opsional.
REACTION_PAIR = re.compile(r"(\S+?)\s*<@&(\d+)>")
MAX_REACTIONS = 20  # batas reaction per pesan dari Discord


def _container(title: str, description: str, *items: discord.ui.Item) -> discord.ui.LayoutView:
    return build_plain_container(title=title, description=description, items=items)


async def _error(interaction: discord.Interaction, message: str) -> None:
    view = _container("❌ Gagal", message)
    if interaction.response.is_done():
        await interaction.followup.send(view=view, ephemeral=True)
    else:
        await interaction.response.send_message(view=view, ephemeral=True)


def _role_problem(guild: discord.Guild, role: discord.Role) -> str | None:
    if role.is_default() or role.managed:
        return f"{role.mention} adalah role bawaan atau role bot, tidak bisa dipakai."
    if not has_role_hierarchy_priority(guild.me, role):
        return f"Role bot harus berada di atas {role.mention}. Atur di Server Settings → Roles."
    return None


class DropdownRolePicker(discord.ui.RoleSelect):
    def __init__(self, channel: discord.TextChannel, title: str, description: str | None):
        super().__init__(placeholder="Pilih role untuk dropdown (maks. 25)...", min_values=1, max_values=25)
        self.channel = channel
        self.panel_title = title
        self.panel_description = description

    async def callback(self, interaction: discord.Interaction) -> None:
        roles = self.values
        problem = next((p for p in (_role_problem(interaction.guild, r) for r in roles) if p), None)
        if problem:
            await _error(interaction, problem)
            return

        options = [
            {"emoji": role.unicode_emoji, "label": role.name[:100], "role_id": role.id, "description": None}
            for role in roles
        ]
        dropdown = await repo.create_role_dropdown(
            guild_id=interaction.guild_id,
            channel_id=self.channel.id,
            title=self.panel_title,
            description=self.panel_description,
            options_json=encode_role_dropdown_config(options, min_values=0, max_values=len(options)),
            multi_select=True,
        )
        view = RoleDropdownView(
            dropdown.id,
            options,
            True,
            title=self.panel_title,
            description=self.panel_description,
            max_values=len(options),
        )
        try:
            message = await self.channel.send(view=view)
        except discord.HTTPException:
            await repo.delete_role_dropdown(dropdown.id)
            await _error(interaction, f"Bot tidak bisa mengirim pesan ke {self.channel.mention}.")
            return
        await repo.set_role_dropdown_message(dropdown.id, message.id)
        await interaction.response.edit_message(
            view=_container(
                "✅ Dropdown Role Dibuat",
                f"Panel dikirim ke {message.jump_url}\n-# Hapus pesan panelnya jika sudah tidak dipakai.",
            )
        )


@role_group.command(name="dropdown", description="Buat panel dropdown role. Pilih role-nya setelah ini.")
@app_commands.describe(
    channel="Channel tujuan panel",
    title="Judul panel",
    description="Teks tambahan di panel (opsional)",
)
@require_permissions(manage_roles=True)
async def role_dropdown(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    title: app_commands.Range[str, 1, 200],
    description: app_commands.Range[str, 1, 1000] | None = None,
) -> None:
    await interaction.response.send_message(
        view=_container(
            "🎭 Pilih Role",
            "Pilih role yang akan muncul di dropdown. Member bisa memilih lebih dari satu.",
            discord.ui.ActionRow(DropdownRolePicker(channel, title, description)),
        ),
        ephemeral=True,
    )


@role_group.command(name="reaction", description="Buat panel reaction role.")
@app_commands.describe(
    channel="Channel tujuan panel",
    title="Judul panel",
    roles="Emoji lalu role, contoh: 🎮 @Gamer 🎨 @Artist",
    description="Teks tambahan di panel (opsional)",
)
@require_permissions(manage_roles=True)
async def role_reaction(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    title: app_commands.Range[str, 1, 200],
    roles: str,
    description: app_commands.Range[str, 1, 1000] | None = None,
) -> None:
    pairs = REACTION_PAIR.findall(roles)
    if not pairs:
        await _error(interaction, "Tulis emoji lalu role, contoh: `🎮 @Gamer 🎨 @Artist`.")
        return
    if len(pairs) > MAX_REACTIONS:
        await _error(interaction, f"Maksimal {MAX_REACTIONS} role per panel.")
        return
    emojis = [emoji for emoji, _ in pairs]
    if len(set(emojis)) != len(emojis):
        await _error(interaction, "Setiap role harus memakai emoji yang berbeda.")
        return

    resolved: list[tuple[str, discord.Role]] = []
    for emoji, role_id in pairs:
        role = interaction.guild.get_role(int(role_id))
        problem = "Role tidak ditemukan di server ini." if role is None else _role_problem(interaction.guild, role)
        if problem:
            await _error(interaction, problem)
            return
        resolved.append((emoji, role))

    # Mengirim panel + menambah banyak reaction bisa melewati batas 3 detik interaction.
    await interaction.response.defer(ephemeral=True)
    lines = "\n".join(f"{emoji} — {role.mention}" for emoji, role in resolved)
    body = f"{description}\n\n{lines}" if description else lines
    body += "\n\n-# Klik reaction untuk mengambil role, klik lagi untuk melepasnya."

    message = None
    try:
        message = await channel.send(
            view=build_plain_container(title=title, description=body),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        for emoji, _ in resolved:
            await message.add_reaction(emoji)
    except discord.HTTPException:
        if message is not None:
            await message.delete()
        await _error(
            interaction,
            f"Panel dibatalkan. Pastikan semua emoji valid dan bot punya izin kirim pesan & reaction di {channel.mention}.",
        )
        return

    for emoji, role in resolved:
        await repo.add_reaction_role(
            guild_id=interaction.guild_id,
            channel_id=channel.id,
            message_id=message.id,
            emoji=emoji,
            role_id=role.id,
        )
    await interaction.followup.send(
        view=_container(
            "✅ Reaction Role Dibuat",
            f"Panel dikirim ke {message.jump_url}\n-# Hapus pesan panelnya jika sudah tidak dipakai.",
        ),
        ephemeral=True,
    )


@role_group.command(name="autorole", description="Role otomatis untuk member baru. Kosongkan untuk mematikan.")
@app_commands.describe(roles="Mention role, contoh: @Member @Verified. Kosongkan untuk mematikan autorole")
@require_permissions(manage_roles=True)
async def role_autorole(interaction: discord.Interaction, roles: str | None = None) -> None:
    if not roles:
        await repo.update_guild_config(interaction.guild_id, autorole_enabled=False, autorole_role_ids="")
        await interaction.response.send_message(
            view=_container("✅ Autorole Dimatikan", "Member baru tidak lagi mendapat role otomatis."), ephemeral=True
        )
        return

    found = [interaction.guild.get_role(int(role_id)) for role_id in re.findall(r"<@&(\d+)>", roles)]
    found = list(dict.fromkeys(role for role in found if role))
    if not found:
        await _error(interaction, "Mention minimal satu role, contoh: `@Member`.")
        return
    problem = next((p for p in (_role_problem(interaction.guild, r) for r in found) if p), None)
    if problem:
        await _error(interaction, problem)
        return

    await repo.update_guild_config(
        interaction.guild_id,
        autorole_enabled=True,
        autorole_role_ids=",".join(str(role.id) for role in found),
    )
    await interaction.response.send_message(
        view=_container("✅ Autorole Aktif", "Member baru akan mendapat: " + ", ".join(r.mention for r in found)),
        ephemeral=True,
    )


class RolesCog(commands.Cog, name="Roles"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        config = await repo.get_or_create_guild_config(member.guild.id)
        if not config.autorole_enabled or not config.autorole_role_ids:
            return
        role_ids = [int(r) for r in config.autorole_role_ids.split(",") if r]
        roles_to_add = []
        for role_id in role_ids:
            role = member.guild.get_role(role_id)
            if role and has_role_hierarchy_priority(member.guild.me, role):
                roles_to_add.append(role)
        if roles_to_add:
            try:
                await member.add_roles(*roles_to_add, reason="Autorole")
            except discord.Forbidden:
                logger.warning("Gagal memberikan autorole di guild %s (izin kurang).", member.guild.id)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.member is None or payload.member.bot:
            return
        emoji_str = str(payload.emoji)
        reaction_role = await repo.get_reaction_role(payload.message_id, emoji_str)
        if reaction_role is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        role = guild.get_role(reaction_role.role_id) if guild else None
        if guild and role and has_role_hierarchy_priority(guild.me, role):
            try:
                await payload.member.add_roles(role, reason="Reaction role")
            except discord.Forbidden:
                logger.warning("Gagal memberi reaction role di guild %s (izin kurang).", guild.id)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        emoji_str = str(payload.emoji)
        reaction_role = await repo.get_reaction_role(payload.message_id, emoji_str)
        if reaction_role is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        member = guild.get_member(payload.user_id)
        role = guild.get_role(reaction_role.role_id)
        if member and role and has_role_hierarchy_priority(guild.me, role):
            try:
                await member.remove_roles(role, reason="Reaction role dilepas")
            except discord.Forbidden:
                logger.warning("Gagal melepas reaction role di guild %s (izin kurang).", guild.id)


async def setup(bot: commands.Bot) -> None:
    bot.tree.add_command(role_group)
    await bot.add_cog(RolesCog(bot))
