"""Server boost thank-you message."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from database import repositories as repo
from ui.modals import BoostMessageModal
from utils.permissions import require_permissions
from utils.placeholders import resolve_member_placeholders

boost_group = app_commands.Group(name="boost", description="Kelola pesan server boost.")


def build_boost_payload(config, member: discord.Member, *, preview: bool = False) -> dict:
    guild = member.guild
    server_name = guild.name if guild else "Server"
    boost_count = guild.premium_subscription_count or 0 if guild else 0
    message = resolve_member_placeholders(config.boost_message, member)
    custom_title = resolve_member_placeholders(config.boost_title or "", member)
    content = (
        f"**{server_name} currently has {boost_count} boosts!**"
        f"{f'\\n\\n**{custom_title}**' if custom_title else ''}\n\n"
        f"{message}\n\n"
        f"💎  **{member.display_name}** boosted the server :)"
    )
    if preview:
        content = f"*Preview pesan boost*\n\n{content}"
    embed = discord.Embed(description=content, color=discord.Color.from_rgb(255, 105, 220))
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    embed.set_thumbnail(url=config.boost_image or member.display_avatar.url)
    footer = getattr(config, "boost_footer", None)
    if footer:
        embed.set_footer(text=resolve_member_placeholders(footer, member))
    return {"embed": embed}


@boost_group.command(name="enable", description="Aktifkan pesan terima kasih saat server di-boost.")
@app_commands.describe(channel="Channel tujuan pesan boost")
@require_permissions(manage_guild=True)
async def boost_enable(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
    await repo.update_guild_config(interaction.guild_id, boost_enabled=True, boost_channel_id=channel.id)
    await interaction.response.send_message(
        embed=discord.Embed(title="✅ Boost Diaktifkan", description=f"Pesan boost dikirim ke {channel.mention}."),
        ephemeral=True,
    )


@boost_group.command(name="disable", description="Nonaktifkan pesan boost.")
@require_permissions(manage_guild=True)
async def boost_disable(interaction: discord.Interaction) -> None:
    await repo.update_guild_config(interaction.guild_id, boost_enabled=False)
    await interaction.response.send_message(
        embed=discord.Embed(title="✅ Boost Dinonaktifkan", description="Pesan boost tidak dikirim lagi."),
        ephemeral=True,
    )


@boost_group.command(name="set-message", description="Edit judul, isi, dan gambar pesan boost.")
@require_permissions(manage_guild=True)
async def boost_set_message(interaction: discord.Interaction) -> None:
    config = await repo.get_or_create_guild_config(interaction.guild_id)

    async def on_submit(modal_interaction: discord.Interaction, data: dict) -> None:
        await repo.update_guild_config(modal_interaction.guild_id, **data)
        await modal_interaction.response.send_message(
            embed=discord.Embed(title="✅ Pesan Boost Disimpan", description="Konfigurasi pesan boost berhasil disimpan."),
            ephemeral=True,
        )

    await interaction.response.send_modal(BoostMessageModal(config, on_submit))


@boost_group.command(name="preview", description="Preview pesan boost.")
@require_permissions(manage_guild=True)
async def boost_preview(interaction: discord.Interaction) -> None:
    config = await repo.get_or_create_guild_config(interaction.guild_id)
    await interaction.response.send_message(ephemeral=True, **build_boost_payload(config, interaction.user, preview=True))


class BoostCog(commands.Cog, name="Boost"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.premium_since is not None or after.premium_since is None:
            return
        config = await repo.get_or_create_guild_config(after.guild.id)
        if not config.boost_enabled or not config.boost_channel_id:
            return
        channel = after.guild.get_channel(config.boost_channel_id)
        if channel is None:
            return
        await channel.send(**build_boost_payload(config, after))


async def setup(bot: commands.Bot) -> None:
    bot.tree.add_command(boost_group)
    await bot.add_cog(BoostCog(bot))
