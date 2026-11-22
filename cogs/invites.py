"""Cog: Permanent Invite System + Invite Tracker (join/leave logging, leaderboard)."""

from __future__ import annotations

import datetime as dt

import discord
from discord import app_commands
from discord.ext import commands

from database import repositories as repo
from services.invite_cache import invite_cache
from utils.embeds import error_embed, info_embed, success_embed
from utils.logger import get_logger
from utils.permissions import require_permissions

logger = get_logger(__name__)

invite_group = app_commands.Group(name="invite", description="Kelola Discord invite.")


@invite_group.command(name="create", description="Buat invite baru (default: permanen, unlimited).")
@app_commands.describe(
    channel="Channel tujuan invite",
    max_age="Masa berlaku dalam detik (0 = permanen)",
    max_uses="Batas penggunaan (0 = unlimited)",
    temporary="Apakah member yang join lewat invite ini bersifat sementara",
    reason="Alasan pembuatan invite (dicatat di audit log)",
)
@require_permissions(manage_guild=True)
async def invite_create(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    max_age: int = 0,
    max_uses: int = 0,
    temporary: bool = False,
    reason: str | None = None,
) -> None:
    bot_perms = channel.permissions_for(interaction.guild.me)
    if not bot_perms.create_instant_invite:
        await interaction.response.send_message(
            embed=error_embed("Gagal", f"Bot tidak memiliki izin `Create Invite` di {channel.mention}."),
            ephemeral=True,
        )
        return

    invite = await channel.create_invite(
        max_age=max_age,
        max_uses=max_uses,
        temporary=temporary,
        reason=reason or f"Dibuat oleh {interaction.user}",
    )
    await repo.create_managed_invite(
        guild_id=interaction.guild_id,
        code=invite.code,
        channel_id=channel.id,
        creator_id=interaction.user.id,
        max_age=max_age,
        max_uses=max_uses,
        temporary=temporary,
        reason=reason,
    )
    await invite_cache.cache_guild(interaction.guild)

    is_permanent = max_age == 0 and max_uses == 0 and not temporary
    if is_permanent:
        await interaction.response.send_message(
            content=f"**PERMANENT LINK** @everyone\n{invite.url}",
            allowed_mentions=discord.AllowedMentions(everyone=True),
        )
        return
    else:
        embed = success_embed("Invite Dibuat", invite.url)
    embed.add_field(name="Channel", value=channel.mention)
    embed.add_field(name="Max Age", value="Permanen" if max_age == 0 else f"{max_age} detik")
    embed.add_field(name="Max Uses", value="Unlimited" if max_uses == 0 else str(max_uses))
    await interaction.response.send_message(embed=embed)


@invite_group.command(name="list", description="Lihat semua invite yang dibuat lewat bot ini.")
@require_permissions(manage_guild=True)
async def invite_list(interaction: discord.Interaction) -> None:
    invites = await repo.list_managed_invites(interaction.guild_id)
    if not invites:
        await interaction.response.send_message(
            embed=info_embed("Tidak Ada Invite", "Belum ada invite yang dibuat lewat bot."), ephemeral=True
        )
        return

    embed = discord.Embed(title="📋 Daftar Invite", color=discord.Color.blurple())
    for inv in invites:
        channel = interaction.guild.get_channel(inv.channel_id)
        creator = interaction.guild.get_member(inv.creator_id)
        embed.add_field(
            name=f"discord.gg/{inv.code}",
            value=(
                f"Channel: {channel.mention if channel else inv.channel_id}\n"
                f"Dibuat oleh: {creator.mention if creator else inv.creator_id}\n"
                f"Dibuat: {discord.utils.format_dt(inv.created_at, style='R')}"
            ),
            inline=False,
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@invite_group.command(name="delete", description="Hapus sebuah invite.")
@app_commands.describe(code="Kode invite (contoh: abc123)")
@require_permissions(manage_guild=True)
async def invite_delete(interaction: discord.Interaction, code: str) -> None:
    managed = await repo.get_managed_invite(code)
    if managed is None or managed.guild_id != interaction.guild_id:
        await interaction.response.send_message(
            embed=error_embed("Tidak Ditemukan", "Invite dengan kode tersebut tidak terdaftar di bot ini."),
            ephemeral=True,
        )
        return

    try:
        discord_invite = await interaction.client.fetch_invite(code)
        await discord_invite.delete(reason=f"Dihapus oleh {interaction.user}")
    except discord.NotFound:
        pass
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=error_embed("Gagal", "Bot tidak memiliki izin untuk menghapus invite ini di Discord."),
            ephemeral=True,
        )
        return

    await repo.delete_managed_invite(code)
    await invite_cache.cache_guild(interaction.guild)
    await interaction.response.send_message(embed=success_embed("Invite Dihapus", f"`{code}` telah dihapus."))


@invite_group.command(name="info", description="Track penggunaan dan masa berlaku sebuah invite.")
@app_commands.describe(code="Kode invite atau bagian terakhir link Discord")
@require_permissions(manage_guild=True)
async def invite_info(interaction: discord.Interaction, code: str) -> None:
    code = code.rsplit("/", 1)[-1].strip()
    managed = await repo.get_managed_invite(code)
    if managed is None:
        managed = None
    try:
        discord_invite = await interaction.client.fetch_invite(code, with_counts=True, with_expiration=True)
    except (discord.NotFound, discord.HTTPException):
        if managed is None or managed.guild_id != interaction.guild_id:
            await interaction.response.send_message(
                embed=error_embed("Tidak Ditemukan", "Invite tidak valid atau bukan milik server ini."),
                ephemeral=True,
            )
            return
        discord_invite = None

    if discord_invite is not None and (
        discord_invite.guild is None or discord_invite.guild.id != interaction.guild_id
    ):
        await interaction.response.send_message(
            embed=error_embed("Tidak Ditemukan", "Invite tersebut bukan milik server ini."), ephemeral=True
        )
        return

    channel = (discord_invite.channel if discord_invite else None) or (
        interaction.guild.get_channel(managed.channel_id) if managed else None
    )
    creator = (discord_invite.inviter if discord_invite else None) or (
        interaction.guild.get_member(managed.creator_id) if managed else None
    )
    max_age = (discord_invite.max_age if discord_invite else None) or (managed.max_age if managed else 0)
    max_uses = (discord_invite.max_uses if discord_invite else None) or (managed.max_uses if managed else 0)
    expires_at = discord_invite.expires_at if discord_invite else (
        managed.created_at + dt.timedelta(seconds=max_age) if managed and max_age else None
    )
    uses = discord_invite.uses if discord_invite else "Unknown"

    embed = discord.Embed(title=f"🔗 Invite Tracker: {code}", color=discord.Color.blurple())
    embed.add_field(name="Link", value=f"https://discord.gg/{code}", inline=False)
    embed.add_field(name="Channel", value=channel.mention if channel else "-", inline=True)
    embed.add_field(name="Creator", value=creator.mention if creator else "Unknown", inline=True)
    embed.add_field(name="Used", value=str(uses or 0), inline=True)
    embed.add_field(
        name="Expires",
        value="Never" if expires_at is None else discord.utils.format_dt(expires_at, style="R"),
        inline=True,
    )
    embed.add_field(name="Max Uses", value="Unlimited" if max_uses == 0 else str(max_uses), inline=True)
    embed.add_field(name="Status", value="Active" if not expires_at or expires_at > discord.utils.utcnow() else "Expired", inline=True)
    if managed and managed.reason:
        embed.add_field(name="Reason", value=managed.reason, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@invite_group.command(name="leaderboard", description="Lihat leaderboard invite server.")
async def invite_leaderboard(interaction: discord.Interaction) -> None:
    stats = await repo.get_invite_leaderboard(interaction.guild_id)
    if not stats:
        await interaction.response.send_message(
            embed=info_embed("Kosong", "Belum ada data invite yang tercatat."), ephemeral=True
        )
        return

    lines = []
    for idx, stat in enumerate(stats, start=1):
        member = interaction.guild.get_member(stat.inviter_id)
        name = member.mention if member else f"<@{stat.inviter_id}>"
        joins = stat.joins or 0
        leaves = stat.leaves or 0
        fake = stat.fake or 0
        net = joins - leaves - fake
        lines.append(f"{idx}. {name} — **{net}** invites (joins: {joins}, leaves: {leaves}, fake: {fake})")

    embed = discord.Embed(title="🏆 Invite Leaderboard", description="\n".join(lines), color=discord.Color.gold())
    await interaction.response.send_message(embed=embed)


@invite_group.command(name="user", description="Lihat statistik invite seorang member.")
@app_commands.describe(member="Member yang ingin dilihat statistiknya")
async def invite_user(interaction: discord.Interaction, member: discord.Member | None = None) -> None:
    target = member or interaction.user
    stat = await repo.get_invite_stat(interaction.guild_id, target.id)
    if stat is None:
        await interaction.response.send_message(
            embed=info_embed("Kosong", f"{target.mention} belum memiliki data invite."), ephemeral=True
        )
        return
    joins = stat.joins or 0
    leaves = stat.leaves or 0
    fake = stat.fake or 0
    net = joins - leaves - fake
    embed = discord.Embed(title=f"📊 Invite Stats — {target.display_name}", color=discord.Color.blurple())
    embed.add_field(name="Total Invites", value=str(net))
    embed.add_field(name="Joins", value=str(joins))
    embed.add_field(name="Leaves", value=str(leaves))
    embed.add_field(name="Fake", value=str(fake))
    await interaction.response.send_message(embed=embed)


@invite_group.command(name="stats", description="Alias dari /invite user untuk statistik diri sendiri.")
async def invite_stats(interaction: discord.Interaction) -> None:
    await invite_user.callback(interaction, None)


class InvitesCog(commands.Cog, name="Invites"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await invite_cache.cache_all(self.bot.guilds)
        logger.info("Invite cache dimuat untuk %d guild.", len(self.bot.guilds))

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        await invite_cache.cache_guild(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        await invite_cache.cache_guild(invite.guild)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        await invite_cache.cache_guild(invite.guild)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        code, inviter_id, is_fake_or_unknown = await invite_cache.find_used_invite(member.guild)

        # Deteksi fake join sederhana: akun berumur sangat baru (<3 hari) dianggap indikasi fake.
        import datetime as dt

        account_age = dt.datetime.now(dt.timezone.utc) - member.created_at
        is_fake = account_age.days < 3

        await repo.record_invite_join(
            guild_id=member.guild.id,
            member_id=member.id,
            inviter_id=inviter_id,
            code=code,
            is_fake=is_fake,
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await repo.record_invite_leave(member.guild.id, member.id)


async def setup(bot: commands.Bot) -> None:
    bot.tree.add_command(invite_group)
    await bot.add_cog(InvitesCog(bot))
