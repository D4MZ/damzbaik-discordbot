"""Cog: Activity Log System (Message Log, Voice Log, Member Log)."""

from __future__ import annotations

import asyncio
import datetime as dt

import discord
from discord import app_commands
from discord.ext import commands

from database import repositories as repo
from utils.components import build_plain_container
from utils.embeds import success_embed
from utils.permissions import require_permissions

log_group = app_commands.Group(name="log", description="Kelola channel logging.")

LOG_TYPE_FIELD = {
    "message": "message_log_channel_id",
    "voice": "voice_log_channel_id",
    "member": "member_log_channel_id",
}

DELETE_BATCH_DELAY_SECONDS = 1.5
DELETE_LOG_MAX_AGE = dt.timedelta(hours=12)
DELETE_LOG_MAX_LENGTH = 3800


def _user_label(user: discord.abc.User) -> str:
    username = discord.utils.escape_markdown(user.name)
    return f"@{username} ({user.id})"


def _deleted_message_text(message: discord.Message) -> str:
    content = message.content.strip()
    if not content and message.attachments:
        filenames = ", ".join(attachment.filename for attachment in message.attachments)
        content = f"[Lampiran: {filenames}]"
    if not content:
        content = "[Pesan tanpa teks]"
    content = discord.utils.escape_markdown(content.replace("\n", " "))
    return content[:500]


def build_deleted_messages_description(
    messages: list[discord.Message],
    channel: discord.abc.GuildChannel | discord.Thread,
    *,
    now: dt.datetime | None = None,
) -> str:
    current_time = now or discord.utils.utcnow()
    unique_messages = {message.id: message for message in messages}
    ordered_messages = sorted(unique_messages.values(), key=lambda message: message.created_at)
    recent_messages = [
        message
        for message in ordered_messages
        if current_time - message.created_at <= DELETE_LOG_MAX_AGE
    ]

    lines = [
        f"**{len(ordered_messages)} pesan dihapus dari {channel.mention} ({channel.id}).**",
        "-# Hanya menampilkan isi pesan dari 12 jam terakhir yang masih tersimpan di cache bot.",
    ]
    hidden_count = len(ordered_messages) - len(recent_messages)

    for message in recent_messages:
        line = f"{_user_label(message.author)}: {_deleted_message_text(message)}"
        candidate = "\n\n".join([*lines, line])
        if len(candidate) > DELETE_LOG_MAX_LENGTH:
            hidden_count += len(recent_messages) - recent_messages.index(message)
            break
        lines.append(line)

    if hidden_count:
        lines.append(f"-# {hidden_count} pesan lainnya tidak ditampilkan.")
    return "\n\n".join(lines)


@log_group.command(name="set-channel", description="Atur channel untuk sebuah tipe log.")
@app_commands.choices(
    log_type=[
        app_commands.Choice(name="Message Log", value="message"),
        app_commands.Choice(name="Voice Log", value="voice"),
        app_commands.Choice(name="Member Log", value="member"),
    ]
)
@app_commands.describe(channel="Channel tujuan log")
@require_permissions(manage_guild=True)
async def log_set_channel(
    interaction: discord.Interaction, log_type: app_commands.Choice[str], channel: discord.TextChannel
) -> None:
    field = LOG_TYPE_FIELD[log_type.value]
    await repo.update_guild_config(interaction.guild_id, **{field: channel.id})
    await interaction.response.send_message(
        embed=success_embed("Log Diatur", f"{log_type.name} akan dikirim ke {channel.mention}."), ephemeral=True
    )


class LoggingCog(commands.Cog, name="Logging"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._pending_deleted_messages: dict[tuple[int, int], dict[int, discord.Message]] = {}
        self._delete_log_tasks: dict[tuple[int, int], asyncio.Task[None]] = {}

    def cog_unload(self) -> None:
        for task in self._delete_log_tasks.values():
            task.cancel()
        self._delete_log_tasks.clear()
        self._pending_deleted_messages.clear()

    async def _get_channel(self, guild_id: int, field: str) -> discord.TextChannel | None:
        config = await repo.get_or_create_guild_config(guild_id)
        channel_id = getattr(config, field)
        if not channel_id:
            return None
        guild = self.bot.get_guild(guild_id)
        return guild.get_channel(channel_id) if guild else None

    # ---------------- Message Log ----------------
    def _queue_deleted_messages(self, messages: list[discord.Message]) -> None:
        if not messages or messages[0].guild is None:
            return
        guild_id = messages[0].guild.id
        channel_id = messages[0].channel.id
        key = (guild_id, channel_id)
        pending = self._pending_deleted_messages.setdefault(key, {})
        pending.update({message.id: message for message in messages if not message.author.bot})
        if not pending:
            self._pending_deleted_messages.pop(key, None)
            return
        current_task = self._delete_log_tasks.get(key)
        if current_task is None or current_task.done():
            self._delete_log_tasks[key] = asyncio.create_task(self._flush_deleted_messages(key))

    async def _flush_deleted_messages(self, key: tuple[int, int]) -> None:
        try:
            await asyncio.sleep(DELETE_BATCH_DELAY_SECONDS)
            pending = self._pending_deleted_messages.pop(key, {})
            if not pending:
                return
            guild_id, channel_id = key
            log_channel = await self._get_channel(guild_id, "message_log_channel_id")
            guild = self.bot.get_guild(guild_id)
            source_channel = guild.get_channel_or_thread(channel_id) if guild else None
            if log_channel is None or source_channel is None:
                return
            description = build_deleted_messages_description(list(pending.values()), source_channel)
            await log_channel.send(
                view=build_plain_container(description=description),
                allowed_mentions=discord.AllowedMentions.none(),
                silent=True,
            )
        finally:
            self._delete_log_tasks.pop(key, None)
            if self._pending_deleted_messages.get(key):
                self._delete_log_tasks[key] = asyncio.create_task(self._flush_deleted_messages(key))

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        self._queue_deleted_messages([message])

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]) -> None:
        self._queue_deleted_messages(messages)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if before.author.bot or before.guild is None or before.content == after.content:
            return
        channel = await self._get_channel(before.guild.id, "message_log_channel_id")
        if channel is None:
            return
        embed = discord.Embed(title="✏️ Pesan Diedit", color=discord.Color.orange())
        embed.add_field(name="User", value=_user_label(before.author), inline=True)
        embed.add_field(name="Channel", value=f"{before.channel.mention} ({before.channel.id})", inline=True)
        embed.add_field(name="Before", value=(before.content[:1000] or "*(kosong)*"), inline=False)
        embed.add_field(name="After", value=(after.content[:1000] or "*(kosong)*"), inline=False)
        embed.timestamp = discord.utils.utcnow()
        await channel.send(embed=embed, silent=True)

    # ---------------- Voice Log ----------------
    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        channel = await self._get_channel(member.guild.id, "voice_log_channel_id")
        if channel is None:
            return

        description = None
        if before.channel is None and after.channel is not None:
            description = f"{_user_label(member)} bergabung ke voice {after.channel.mention}"
        elif before.channel is not None and after.channel is None:
            description = f"{_user_label(member)} keluar dari voice {before.channel.mention}"
        elif before.channel != after.channel:
            description = f"{_user_label(member)} pindah dari {before.channel.mention} ke {after.channel.mention}"
        elif before.self_mute != after.self_mute:
            description = f"{_user_label(member)} {'mute' if after.self_mute else 'unmute'}"
        elif before.self_deaf != after.self_deaf:
            description = f"{_user_label(member)} {'deafen' if after.self_deaf else 'undeafen'}"
        elif before.self_stream != after.self_stream:
            description = f"{_user_label(member)} {'mulai' if after.self_stream else 'berhenti'} streaming"
        elif before.self_video != after.self_video:
            description = f"{_user_label(member)} {'menyalakan' if after.self_video else 'mematikan'} kamera"

        if description:
            embed = discord.Embed(description=description, color=discord.Color.blue())
            embed.timestamp = discord.utils.utcnow()
            await channel.send(embed=embed, silent=True)

    # ---------------- Member Log ----------------
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        channel = await self._get_channel(member.guild.id, "member_log_channel_id")
        if channel:
            embed = discord.Embed(description=f"📥 {_user_label(member)} bergabung ke server.", color=discord.Color.green())
            embed.timestamp = discord.utils.utcnow()
            await channel.send(embed=embed, silent=True)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        channel = await self._get_channel(member.guild.id, "member_log_channel_id")
        if channel:
            embed = discord.Embed(description=f"📤 {_user_label(member)} meninggalkan server.", color=discord.Color.orange())
            embed.timestamp = discord.utils.utcnow()
            await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        channel = await self._get_channel(guild.id, "member_log_channel_id")
        if channel:
            embed = discord.Embed(description=f"🔨 {_user_label(user)} di-ban dari server.", color=discord.Color.red())
            embed.timestamp = discord.utils.utcnow()
            await channel.send(embed=embed, silent=True)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        channel = await self._get_channel(guild.id, "member_log_channel_id")
        if channel:
            embed = discord.Embed(description=f"♻️ {_user_label(user)} di-unban dari server.", color=discord.Color.green())
            embed.timestamp = discord.utils.utcnow()
            await channel.send(embed=embed, silent=True)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        channel = await self._get_channel(before.guild.id, "member_log_channel_id")
        if channel is None:
            return

        if before.nick != after.nick:
            embed = discord.Embed(
                description=f"📝 {_user_label(after)} mengubah nickname: `{before.nick}` → `{after.nick}`",
                color=discord.Color.blue(),
            )
            embed.timestamp = discord.utils.utcnow()
            await channel.send(embed=embed, silent=True)

        before_roles, after_roles = set(before.roles), set(after.roles)
        added = after_roles - before_roles
        removed = before_roles - after_roles
        if added:
            embed = discord.Embed(
                description=f"➕ {_user_label(after)} mendapat role: {', '.join(r.mention for r in added)}",
                color=discord.Color.green(),
            )
            embed.timestamp = discord.utils.utcnow()
            await channel.send(embed=embed, silent=True)
        if removed:
            embed = discord.Embed(
                description=f"➖ {_user_label(after)} kehilangan role: {', '.join(r.mention for r in removed)}",
                color=discord.Color.red(),
            )
            embed.timestamp = discord.utils.utcnow()
            await channel.send(embed=embed, silent=True)


async def setup(bot: commands.Bot) -> None:
    bot.tree.add_command(log_group)
    await bot.add_cog(LoggingCog(bot))
