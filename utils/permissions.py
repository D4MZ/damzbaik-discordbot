"""
Permission checker reusable untuk slash command.

Dipakai sebagai decorator (app_commands.check) sehingga setiap command
cukup menambahkan satu baris, misalnya:

    @app_commands.command(...)
    @require_permissions(manage_guild=True)
    async def config(self, interaction: discord.Interaction): ...
"""

from __future__ import annotations

import discord
from discord import app_commands


class MissingBotPermission(app_commands.CheckFailure):
    """Dilempar ketika user tidak memiliki permission yang dibutuhkan."""

    def __init__(self, required: list[str]):
        self.required = required
        super().__init__(
            "Anda tidak memiliki izin yang dibutuhkan: " + ", ".join(required)
        )


def require_permissions(**perms: bool):
    """
    Decorator generik untuk memvalidasi permission Discord milik user
    (bukan permission bot). Contoh: require_permissions(manage_guild=True)
    """

    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            raise app_commands.NoPrivateMessage()

        member_perms = interaction.channel.permissions_for(interaction.user)
        missing = [name for name, required in perms.items() if required and not getattr(member_perms, name, False)]
        if missing:
            raise MissingBotPermission(missing)
        return True

    return app_commands.check(predicate)


def require_owner():
    """Hanya bisa dipakai oleh owner bot (BOT_OWNER_ID di .env)."""

    async def predicate(interaction: discord.Interaction) -> bool:
        from config import settings

        if interaction.user.id != settings.bot_owner_id:
            raise MissingBotPermission(["Bot Owner"])
        return True

    return app_commands.check(predicate)


def has_role_hierarchy_priority(bot_member: discord.Member, target_role: discord.Role) -> bool:
    """
    Mengecek apakah role tertinggi bot berada di atas target_role,
    sehingga bot secara teknis mampu memberikan/mencabut role tersebut.
    """
    return bot_member.top_role > target_role
