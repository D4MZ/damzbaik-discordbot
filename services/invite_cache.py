"""
Cache invite in-memory per-guild.

Discord tidak mengirim event "invite mana yang dipakai" secara langsung saat
member join. Cara standar & stabil untuk mendeteksinya adalah membandingkan
jumlah 'uses' setiap invite sebelum dan sesudah member join. Modul ini
menyimpan snapshot invite tiap guild di memori bot.
"""

from __future__ import annotations

import discord


class InviteCache:
    def __init__(self) -> None:
        # guild_id -> {invite_code: uses}
        self._cache: dict[int, dict[str, int]] = {}
        # guild_id -> {invite_code: inviter_id}
        self._inviters: dict[int, dict[str, int | None]] = {}

    async def cache_guild(self, guild: discord.Guild) -> None:
        try:
            invites = await guild.invites()
        except discord.Forbidden:
            self._cache[guild.id] = {}
            self._inviters[guild.id] = {}
            return
        self._cache[guild.id] = {invite.code: invite.uses or 0 for invite in invites}
        self._inviters[guild.id] = {
            invite.code: invite.inviter.id if invite.inviter else None for invite in invites
        }

    async def cache_all(self, guilds: list[discord.Guild]) -> None:
        for guild in guilds:
            await self.cache_guild(guild)

    async def find_used_invite(self, guild: discord.Guild) -> tuple[str | None, int | None, bool]:
        """
        Membandingkan snapshot lama dengan kondisi invite saat ini.
        Return: (code, inviter_id, is_vanity_or_unknown)
        """
        before = self._cache.get(guild.id, {})
        before_inviters = self._inviters.get(guild.id, {})

        try:
            after_invites = await guild.invites()
        except discord.Forbidden:
            return None, None, True

        used_code = None
        for invite in after_invites:
            prev_uses = before.get(invite.code, 0)
            if (invite.uses or 0) > prev_uses:
                used_code = invite.code
                break

        # Update cache ke kondisi terbaru
        self._cache[guild.id] = {invite.code: invite.uses or 0 for invite in after_invites}
        self._inviters[guild.id] = {
            invite.code: invite.inviter.id if invite.inviter else None for invite in after_invites
        }

        if used_code is None:
            # Kemungkinan vanity URL, invite yang baru dibuat, atau widget invite
            return None, None, True

        return used_code, before_inviters.get(used_code), False


invite_cache = InviteCache()
