"""
Global error handler untuk application commands (slash commands).

Prinsip:
- User selalu mendapat pesan yang mudah dipahami (ephemeral).
- Developer/console mendapat traceback lengkap di logs/bot.log.
"""

from __future__ import annotations

import asyncio
import traceback

import discord
from discord import app_commands

from utils.embeds import error_embed
from utils.logger import get_logger
from utils.permissions import MissingBotPermission

logger = get_logger(__name__)


async def _resync_commands(interaction: discord.Interaction) -> None:
    resync = getattr(interaction.client, "resync_commands", None)
    if resync is None:
        return
    try:
        await resync(guild_id=interaction.guild_id)
    except Exception:
        logger.exception(
            "Gagal melakukan recovery sync untuk guild %s.", interaction.guild_id
        )


async def _send_error(interaction: discord.Interaction, message: str) -> None:
    embed = error_embed("Terjadi Kesalahan", message)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except discord.HTTPException:
        # Interaction sudah expired / tidak bisa direspon lagi, cukup dicatat di log.
        logger.warning("Gagal mengirim pesan error ke interaction (kemungkinan sudah expired).")


async def handle_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    if isinstance(error, app_commands.CommandSignatureMismatch):
        asyncio.create_task(_resync_commands(interaction))
        await _send_error(
            interaction,
            "Command Discord masih memakai versi lama. Command untuk server ini sedang "
            "disinkronkan ulang; tunggu beberapa detik, lalu jalankan ulang command yang sama "
            "dari autocomplete Discord.",
        )
        logger.warning(
            "Signature command '%s' berbeda dari registrasi Discord; resync command dipicu.",
            interaction.command.qualified_name if interaction.command else "unknown",
        )
        return

    if isinstance(error, MissingBotPermission):
        await _send_error(
            interaction,
            "Anda tidak memiliki izin untuk menggunakan command ini.\n"
            f"Izin yang dibutuhkan: `{', '.join(error.required)}`",
        )
        return

    if isinstance(error, app_commands.MissingPermissions):
        await _send_error(
            interaction,
            "Anda tidak memiliki izin Discord yang dibutuhkan untuk command ini.",
        )
        return

    if isinstance(error, app_commands.BotMissingPermissions):
        await _send_error(
            interaction,
            "Bot tidak memiliki izin yang dibutuhkan untuk menjalankan command ini. "
            f"Izin yang diperlukan: `{', '.join(error.missing_permissions)}`",
        )
        return

    if isinstance(error, app_commands.CommandOnCooldown):
        await _send_error(
            interaction,
            f"Command ini sedang cooldown. Coba lagi dalam {error.retry_after:.1f} detik.",
        )
        return

    if isinstance(error, app_commands.NoPrivateMessage):
        await _send_error(interaction, "Command ini hanya bisa digunakan di dalam server.")
        return

    if isinstance(error, app_commands.CheckFailure):
        await _send_error(interaction, "Anda tidak memenuhi syarat untuk menjalankan command ini.")
        return

    if isinstance(error, discord.NotFound):
        await _send_error(interaction, "Interaksi sudah tidak berlaku (expired). Silakan coba lagi.")
        return

    # Error tak terduga -> log lengkap untuk developer, pesan generik untuk user
    original = getattr(error, "original", error)
    logger.error(
        "Unhandled application command error pada command '%s': %s",
        interaction.command.qualified_name if interaction.command else "unknown",
        "".join(traceback.format_exception(type(original), original, original.__traceback__)),
    )
    await _send_error(
        interaction,
        "Terjadi kesalahan tak terduga saat menjalankan command ini. "
        "Developer sudah diberi tahu melalui log.",
    )
