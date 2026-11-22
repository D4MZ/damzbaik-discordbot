"""Cog: Custom Announcement System."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ui.modals import AnnouncementModal
from utils.embeds import error_embed
from utils.permissions import require_permissions

announcement_group = app_commands.Group(name="announcement", description="Buat pengumuman ke sebuah channel.")


class AnnouncementConfirmView(discord.ui.View):
    def __init__(self, channel: discord.TextChannel, embed: discord.Embed, mention_content: str | None):
        super().__init__(timeout=120)
        self.channel = channel
        self.embed = embed
        self.mention_content = mention_content

    @discord.ui.button(label="Kirim", style=discord.ButtonStyle.success, emoji="📢")
    async def send_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        bot_member = interaction.guild.me if interaction.guild else None
        if bot_member is None:
            await interaction.response.send_message(
                embed=error_embed("Gagal", "Bot belum siap di server ini. Silakan coba lagi."),
                ephemeral=True,
            )
            return
        bot_perms = self.channel.permissions_for(bot_member)
        if not bot_perms.send_messages or not bot_perms.embed_links:
            await interaction.response.send_message(
                embed=error_embed("Gagal", f"Bot tidak memiliki izin mengirim pesan/embed di {self.channel.mention}."),
                ephemeral=True,
            )
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.defer()
        try:
            await self.channel.send(content=self.mention_content, embed=self.embed)
        except discord.HTTPException as exc:
            for item in self.children:
                item.disabled = False
            await interaction.edit_original_response(
                content=f"❌ Announcement gagal dikirim: {exc}",
                embed=self.embed,
                view=self,
            )
            return
        await interaction.edit_original_response(
            content="✅ Announcement terkirim.",
            embed=None,
            view=self,
        )
        self.stop()

    @discord.ui.button(label="Batal", style=discord.ButtonStyle.danger, emoji="✖️")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content="❌ Dibatalkan.", embed=None, view=self)
        self.stop()


@announcement_group.command(name="create", description="Buat announcement (dengan preview sebelum dikirim).")
@app_commands.describe(
    channel="Channel tujuan announcement",
    mention_role="Role yang ingin di-mention (opsional)",
    mention_everyone="Mention @everyone (butuh izin Mention Everyone)",
)
@require_permissions(manage_guild=True)
async def announcement_create(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    mention_role: discord.Role | None = None,
    mention_everyone: bool = False,
) -> None:
    if mention_everyone and not interaction.channel.permissions_for(interaction.user).mention_everyone:
        await interaction.response.send_message(
            embed=error_embed("Ditolak", "Anda tidak memiliki izin `Mention Everyone`."), ephemeral=True
        )
        return

    mention_content = None
    if mention_everyone:
        mention_content = "@everyone"
    elif mention_role:
        mention_content = mention_role.mention

    async def on_submit(modal_interaction: discord.Interaction, embed: discord.Embed) -> None:
        view = AnnouncementConfirmView(channel, embed, mention_content)
        await modal_interaction.response.send_message(
            content=f"**Preview** (akan dikirim ke {channel.mention}):",
            embed=embed,
            view=view,
            ephemeral=True,
        )

    await interaction.response.send_modal(AnnouncementModal(on_submit))


async def setup(bot: commands.Bot) -> None:
    bot.tree.add_command(announcement_group)
