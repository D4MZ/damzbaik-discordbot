"""Cog: Custom prefix commands (contoh: !rules) yang dikelola lewat /prefix."""

from __future__ import annotations

import re

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy.exc import IntegrityError

from database import repositories as repo
from utils.components import build_plain_container
from utils.permissions import require_permissions

prefix_group = app_commands.Group(name="prefix", description="Kelola prefix command custom.")
NAME_PATTERN = re.compile(r"^[a-z0-9_-]{1,32}$")


def _normalize(name: str) -> str:
    return name.strip().lower().removeprefix("!")


def _prefix(interaction: discord.Interaction) -> str:
    return interaction.client.command_prefix


async def _reply(interaction: discord.Interaction, title: str, description: str) -> None:
    await interaction.response.send_message(
        view=build_plain_container(title=title, description=description),
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


async def _not_found(interaction: discord.Interaction, name: str) -> None:
    await _reply(interaction, "❌ Tidak Ditemukan", f"Command `{_prefix(interaction)}{name}` tidak ada.")


@prefix_group.command(name="add", description="Tambah prefix command baru")
@app_commands.describe(
    name="Nama command tanpa prefix (contoh: rules)",
    response="Balasan bot. Gunakan \\n untuk baris baru",
    description="Deskripsi singkat (opsional)",
)
@require_permissions(manage_guild=True)
async def prefix_add(
    interaction: discord.Interaction,
    name: str,
    response: app_commands.Range[str, 1, 2000],
    description: app_commands.Range[str, 1, 100] | None = None,
) -> None:
    name = _normalize(name)
    if not NAME_PATTERN.fullmatch(name):
        await _reply(interaction, "❌ Nama Tidak Valid", "Gunakan 1-32 karakter: huruf kecil, angka, `-`, atau `_`.")
        return
    if interaction.client.get_command(name):
        await _reply(interaction, "❌ Nama Dipakai", f"`{name}` sudah dipakai command bawaan bot.")
        return
    try:
        await repo.add_prefix_command(
            guild_id=interaction.guild_id,
            name=name,
            response=response.replace("\\n", "\n"),
            description=description,
            creator_id=interaction.user.id,
        )
    except IntegrityError:
        await _reply(
            interaction, "❌ Sudah Ada", f"`{_prefix(interaction)}{name}` sudah terdaftar. Gunakan `/prefix edit`."
        )
        return
    await _reply(interaction, "✅ Command Ditambahkan", f"Ketik `{_prefix(interaction)}{name}` untuk memakainya.")


@prefix_group.command(name="delete", description="Hapus prefix command dari daftar")
@app_commands.describe(name="Nama command yang akan dihapus")
@require_permissions(manage_guild=True)
async def prefix_delete(interaction: discord.Interaction, name: str) -> None:
    name = _normalize(name)
    if not await repo.delete_prefix_command(interaction.guild_id, name):
        await _not_found(interaction, name)
        return
    await _reply(interaction, "✅ Command Dihapus", f"`{_prefix(interaction)}{name}` telah dihapus.")


@prefix_group.command(name="edit", description="Edit response atau deskripsi command yang sudah ada")
@app_commands.describe(
    name="Nama command yang akan diedit",
    response="Response baru. Gunakan \\n untuk baris baru",
    description="Deskripsi baru",
)
@require_permissions(manage_guild=True)
async def prefix_edit(
    interaction: discord.Interaction,
    name: str,
    response: app_commands.Range[str, 1, 2000] | None = None,
    description: app_commands.Range[str, 1, 100] | None = None,
) -> None:
    name = _normalize(name)
    fields = {}
    if response is not None:
        fields["response"] = response.replace("\\n", "\n")
    if description is not None:
        fields["description"] = description
    if not fields:
        await _reply(interaction, "❌ Tidak Ada Perubahan", "Isi `response` atau `description`.")
        return
    if await repo.update_prefix_command(interaction.guild_id, name, **fields) is None:
        await _not_found(interaction, name)
        return
    await _reply(interaction, "✅ Command Diperbarui", f"`{_prefix(interaction)}{name}` berhasil diedit.")


@prefix_group.command(name="list", description="Tampilkan semua prefix command yang terdaftar")
@require_permissions(manage_guild=True)
async def prefix_list(interaction: discord.Interaction) -> None:
    items = await repo.list_prefix_commands(interaction.guild_id)
    if not items:
        await _reply(interaction, "ℹ️ Kosong", "Belum ada prefix command. Tambahkan dengan `/prefix add`.")
        return
    prefix = _prefix(interaction)
    lines = [f"`{prefix}{item.name}` — {item.description or '-'}" for item in items]
    lines.append(f"\n-# Total: {len(items)} command")
    # shortcut: container text stops at 4000 chars, add pagination if a server stores ~80+ commands.
    await _reply(interaction, "📜 Prefix Commands", "\n".join(lines)[:3900])


@prefix_group.command(name="view", description="Lihat detail response sebuah command")
@app_commands.describe(name="Nama command")
@require_permissions(manage_guild=True)
async def prefix_view(interaction: discord.Interaction, name: str) -> None:
    name = _normalize(name)
    item = await repo.get_prefix_command(interaction.guild_id, name)
    if item is None:
        await _not_found(interaction, name)
        return
    details = (
        f"{item.response}\n\n"
        f"**Deskripsi:** {item.description or '-'}\n"
        f"**Dibuat oleh:** <@{item.creator_id}>\n"
        f"**Dibuat:** {discord.utils.format_dt(item.created_at, style='R')}"
    )
    await _reply(interaction, f"🔎 {_prefix(interaction)}{item.name}", details)


async def _name_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    items = await repo.list_prefix_commands(interaction.guild_id)
    current = _normalize(current)
    return [app_commands.Choice(name=item.name, value=item.name) for item in items if current in item.name][:25]


for _command in (prefix_delete, prefix_edit, prefix_view):
    _command.autocomplete("name")(_name_autocomplete)


class PrefixCommandsCog(commands.Cog, name="PrefixCommands"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        prefix = self.bot.command_prefix
        if message.author.bot or message.guild is None or not message.content.startswith(prefix):
            return
        words = message.content[len(prefix):].split(maxsplit=1)
        name = words[0].lower() if words else ""
        if not name or self.bot.get_command(name):
            return
        item = await repo.get_prefix_command(message.guild.id, name)
        if item is not None:
            await message.channel.send(item.response, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot) -> None:
    bot.tree.add_command(prefix_group)
    await bot.add_cog(PrefixCommandsCog(bot))
