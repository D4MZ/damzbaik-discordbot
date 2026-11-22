"""Cog: General commands (/ping, /help)."""

from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from ui.help_view import (
    HelpView,
    build_help_home_content,
    ensure_help_emojis,
    help_banner_file,
)
from ui.modals import SayEditModal
from utils.components import build_plain_container
from utils.permissions import require_permissions


def _component_texts(components) -> list[str]:
    texts = []
    for component in components:
        if isinstance(component, discord.TextDisplay):
            texts.append(component.content)
        texts.extend(_component_texts(getattr(component, "children", [])))
    return texts


class GeneralCog(commands.Cog, name="General"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Cek latency bot.")
    async def ping(self, interaction: discord.Interaction) -> None:
        start = time.perf_counter()
        await interaction.response.send_message("🏓 Mengukur latency...")
        end = time.perf_counter()
        websocket_latency = round(self.bot.latency * 1000)
        roundtrip = round((end - start) * 1000)

        embed = discord.Embed(
            title="🏓 Pong!",
            description="Bot aktif dan siap menerima perintah.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="Gateway", value=f"`{websocket_latency} ms`", inline=True)
        embed.add_field(name="Roundtrip", value=f"`{roundtrip} ms`", inline=True)
        embed.set_footer(text=f"Diminta oleh {interaction.user.display_name}")
        await interaction.edit_original_response(content=None, embed=embed)

    @app_commands.command(name="say", description="Kirim pesan sebagai bot ke channel ini.")
    @app_commands.describe(message="Pesan yang ingin dikirim", embed="Gunakan container atau teks biasa")
    @app_commands.choices(
        embed=[
            app_commands.Choice(name="True — Container", value="true"),
            app_commands.Choice(name="False — Plain Text", value="false"),
        ]
    )
    @require_permissions(manage_messages=True)
    async def say(
        self,
        interaction: discord.Interaction,
        message: str,
        embed: app_commands.Choice[str],
    ) -> None:
        if interaction.channel is None:
            await interaction.response.send_message("Command ini hanya bisa digunakan di channel.", ephemeral=True)
            return

        # Acknowledge first: channel.send can exceed Discord's 3s interaction window.
        await interaction.response.defer(ephemeral=True)
        if embed.value == "true":
            await interaction.channel.send(
                view=build_plain_container(description=message),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await interaction.channel.send(
                message,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        await interaction.followup.send("✅ Pesan berhasil dikirim.", ephemeral=True)

    @app_commands.command(name="say-edit", description="Edit pesan yang dikirim bot lewat /say.")
    @app_commands.describe(message_id="ID pesan bot (klik kanan pesan → Copy Message ID)")
    @require_permissions(manage_messages=True)
    async def say_edit(self, interaction: discord.Interaction, message_id: str) -> None:
        try:
            target = await interaction.channel.fetch_message(int(message_id))
        except (ValueError, discord.NotFound, discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message(
                "❌ Pesan tidak ditemukan. Jalankan command ini di channel yang sama dengan pesannya.",
                ephemeral=True,
            )
            return
        if target.author.id != self.bot.user.id:
            await interaction.response.send_message("❌ Hanya pesan yang dikirim bot ini yang bisa diedit.", ephemeral=True)
            return

        is_container = bool(target.components) and not target.content
        current = "\n".join(_component_texts(target.components)) if is_container else target.content

        async def save(modal_interaction: discord.Interaction, new_text: str) -> None:
            await modal_interaction.response.defer(ephemeral=True)
            if is_container:
                await target.edit(view=build_plain_container(description=new_text), allowed_mentions=discord.AllowedMentions.none())
            else:
                await target.edit(content=new_text, allowed_mentions=discord.AllowedMentions.none())
            await modal_interaction.followup.send("✅ Pesan berhasil diedit.", ephemeral=True)

        # Container text limit is 4000, plain message content is 2000.
        await interaction.response.send_modal(SayEditModal(current, 4000 if is_container else 2000, save))

    @app_commands.command(name="help", description="Tampilkan daftar command bot (administrator).")
    @require_permissions(administrator=True)
    async def help_command(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        emojis = await ensure_help_emojis(self.bot)
        content = build_help_home_content(self.bot.user.display_name, emojis)
        banner = help_banner_file()
        await interaction.edit_original_response(
            content=None,
            attachments=[banner],
            view=HelpView(content=content, emojis=emojis, banner=banner),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GeneralCog(bot))
