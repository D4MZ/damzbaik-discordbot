"""
Cog: Configuration System (/settings, /config).

Bertindak sebagai dashboard interaktif yang menampilkan ringkasan konfigurasi
guild saat ini per kategori (Welcome, Roles, Logging, Boost).
Perubahan nilai konfigurasi yang detail dilakukan lewat command khusus
masing-masing fitur (/welcome, /role, /log, /boost, dst),
karena masing-masing punya banyak parameter yang tidak realistis
digabung dalam satu modal (modal Discord dibatasi 5 field).
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from database import repositories as repo
from utils.permissions import require_permissions

CATEGORY_HINTS = {
    "welcome": "Gunakan `/welcome` dan `/leave` untuk mengatur pesan member masuk dan keluar.",
    "roles": "Gunakan `/role dropdown`, `/role reaction`, atau `/role autorole` untuk mengatur role.",
    "logging": "Gunakan `/log set-channel` untuk mengatur channel logging.",
    "boost": "Gunakan `/boost enable`, `/boost set-message`, atau `/boost preview`.",
}


def _format_channel(guild: discord.Guild, channel_id: int | None) -> str:
    if not channel_id:
        return "*belum diatur*"
    channel = guild.get_channel(channel_id)
    return channel.mention if channel else f"`{channel_id}` (channel terhapus)"


def _format_role(guild: discord.Guild, role_id: int | None) -> str:
    if not role_id:
        return "*belum diatur*"
    role = guild.get_role(role_id)
    return role.mention if role else f"`{role_id}` (role terhapus)"


class SettingsCategorySelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild, config):
        self.guild = guild
        self.config = config
        options = [
            discord.SelectOption(label="Welcome", value="welcome", emoji="👋"),
            discord.SelectOption(label="Roles", value="roles", emoji="🎭"),
            discord.SelectOption(label="Logging", value="logging", emoji="📝"),
            discord.SelectOption(label="Server Boost", value="boost", emoji="🚀"),
        ]
        super().__init__(placeholder="⚙️ Pilih kategori konfigurasi...", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        key = self.values[0]
        config = self.config
        guild = self.guild

        embed = discord.Embed(title=f"⚙️ Server Configuration — {key.title()}", color=discord.Color.blurple())

        if key == "welcome":
            embed.add_field(name="Status", value="Aktif ✅" if config.welcome_enabled else "Nonaktif ❌", inline=False)
            embed.add_field(name="Channel", value=_format_channel(guild, config.welcome_channel_id), inline=False)
            embed.add_field(name="Tipe", value=config.welcome_type, inline=False)
        elif key == "roles":
            embed.add_field(name="Autorole", value="Aktif ✅" if config.autorole_enabled else "Nonaktif ❌", inline=False)
            role_ids = [r for r in config.autorole_role_ids.split(",") if r]
            roles_display = ", ".join(_format_role(guild, int(r)) for r in role_ids) or "*belum diatur*"
            embed.add_field(name="Autorole Roles", value=roles_display, inline=False)
        elif key == "logging":
            embed.add_field(name="Message Log", value=_format_channel(guild, config.message_log_channel_id), inline=False)
            embed.add_field(name="Voice Log", value=_format_channel(guild, config.voice_log_channel_id), inline=False)
            embed.add_field(name="Member Log", value=_format_channel(guild, config.member_log_channel_id), inline=False)
        elif key == "boost":
            embed.add_field(name="Status", value="Aktif ✅" if config.boost_enabled else "Nonaktif ❌", inline=False)
            embed.add_field(name="Channel", value=_format_channel(guild, config.boost_channel_id), inline=False)
            embed.add_field(name="Judul", value=config.boost_title or "Server Boost", inline=False)
        embed.add_field(name="\u200b", value=CATEGORY_HINTS[key], inline=False)
        await interaction.response.edit_message(embed=embed, view=self.view)


class SettingsView(discord.ui.View):
    def __init__(self, guild: discord.Guild, config):
        super().__init__(timeout=120)
        self.add_item(SettingsCategorySelect(guild, config))


class SettingsCog(commands.Cog, name="Settings"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _show_dashboard(self, interaction: discord.Interaction) -> None:
        config = await repo.get_or_create_guild_config(interaction.guild_id)
        embed = discord.Embed(
            title="⚙️ Server Configuration",
            description="Pilih kategori di bawah untuk melihat konfigurasi saat ini.",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, view=SettingsView(interaction.guild, config), ephemeral=True)

    @app_commands.command(name="settings", description="Lihat & kelola konfigurasi server.")
    @require_permissions(manage_guild=True)
    async def settings_command(self, interaction: discord.Interaction) -> None:
        await self._show_dashboard(interaction)

    @app_commands.command(name="config", description="Alias dari /settings — lihat konfigurasi server.")
    @require_permissions(manage_guild=True)
    async def config_command(self, interaction: discord.Interaction) -> None:
        await self._show_dashboard(interaction)

    @app_commands.command(name="set-status", description="Atur teks status bot (Watching ...). Gunakan {servers} untuk jumlah server.")
    @require_permissions(administrator=True)
    async def set_status(self, interaction: discord.Interaction, text: str) -> None:
        await repo.update_guild_config(interaction.guild_id, status_text=text)
        rendered = text.replace("{servers}", str(len(self.bot.guilds)))
        await interaction.client.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name=rendered)
        )
        await interaction.response.send_message(
            embed=discord.Embed(
                title="✅ Status Diubah", description=f"Status bot sekarang: `Watching {rendered}`", color=discord.Color.green()
            ),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SettingsCog(bot))
