"""Sistem anti-nuke berbasis audit log, rollback, dan proteksi pesan."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands

from config import settings
from database import repositories as repo
from utils.components import build_plain_container
from utils.logger import get_logger

logger = get_logger(__name__)

anti_nuke_group = app_commands.Group(
    name="antinuke",
    description="Kelola perlindungan anti-nuke server.",
)

FEATURE_LABELS = {
    "ban": "Anti Ban",
    "kick": "Anti Kick",
    "role_create": "Anti Role Create",
    "role_delete": "Anti Role Delete",
    "channel_create": "Anti Channel Create",
    "channel_delete": "Anti Channel Delete",
    "mention": "Anti Mention",
    "bot_add": "Anti Bot Add",
    "prune": "Anti Prune",
    "dangerous_role_permission_update": "Anti Dangerous Role Permission Update",
    "dangerous_role_add": "Anti Dangerous Role Add",
    "server_rename": "Anti Server Rename",
    "server_icon_change": "Anti Server Icon Change",
    "role_rename": "Anti Role Rename",
    "channel_rename": "Anti Channel Rename",
    "emoji_delete": "Anti Emoji Delete",
    "invite_link": "Anti Invite Link",
    "ghost_ping": "Anti Ghost Ping",
}

FEATURE_CHOICES = [
    app_commands.Choice(name=label, value=key)
    for key, label in FEATURE_LABELS.items()
]

PUNISHMENT_CHOICES = [
    app_commands.Choice(name="Cabut semua role", value="strip_roles"),
    app_commands.Choice(name="Kick", value="kick"),
    app_commands.Choice(name="Ban", value="ban"),
    app_commands.Choice(name="Hanya log", value="none"),
]

INVITE_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord\.gg|discord(?:app)?\.com/invite)/[A-Za-z0-9-]+",
    re.IGNORECASE,
)

DANGEROUS_PERMISSIONS = {
    "administrator",
    "manage_guild",
    "manage_roles",
    "manage_channels",
    "manage_webhooks",
    "ban_members",
    "kick_members",
    "moderate_members",
    "mention_everyone",
}


@dataclass(frozen=True)
class AntiNukeSettings:
    enabled: bool
    log_channel_id: int | None
    punishment: str
    violation_limit: int
    window_seconds: int
    mention_limit: int
    features: dict[str, bool]
    whitelist: frozenset[int]


def _manager_check():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            raise app_commands.NoPrivateMessage()
        if interaction.user.id in {interaction.guild.owner_id, settings.bot_owner_id}:
            return True
        raise app_commands.CheckFailure(
            "Konfigurasi anti-nuke hanya dapat diubah oleh owner server atau owner bot."
        )

    return app_commands.check(predicate)


def _parse_config(config) -> AntiNukeSettings:
    try:
        stored_features = json.loads(config.features_json or "{}")
    except (TypeError, json.JSONDecodeError):
        stored_features = {}
    try:
        stored_whitelist = json.loads(config.whitelist_json or "[]")
    except (TypeError, json.JSONDecodeError):
        stored_whitelist = []
    return AntiNukeSettings(
        enabled=bool(config.enabled),
        log_channel_id=config.log_channel_id,
        punishment=config.punishment if config.punishment in {"strip_roles", "kick", "ban", "none"} else "strip_roles",
        violation_limit=max(1, int(config.violation_limit or 1)),
        window_seconds=max(3, int(config.window_seconds or 10)),
        mention_limit=max(1, int(config.mention_limit or 5)),
        features={key: bool(stored_features.get(key, True)) for key in FEATURE_LABELS},
        whitelist=frozenset(int(value) for value in stored_whitelist if str(value).isdigit()),
    )


def _has_dangerous_permissions(permissions: discord.Permissions) -> bool:
    return any(getattr(permissions, name, False) for name in DANGEROUS_PERMISSIONS)


def _new_dangerous_permissions(before: discord.Permissions, after: discord.Permissions) -> list[str]:
    return [
        name
        for name in DANGEROUS_PERMISSIONS
        if not getattr(before, name, False) and getattr(after, name, False)
    ]


def _message_mentions(message: discord.Message) -> bool:
    return bool(message.mentions or message.role_mentions or message.mention_everyone)


class AntiNukeCog(commands.Cog, name="Anti Nuke"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._config_cache: dict[int, AntiNukeSettings] = {}
        self._violations: dict[tuple[int, int, str], deque[dt.datetime]] = defaultdict(deque)
        self._handled_audit_entries: set[int] = set()
        self._rollback_targets: dict[tuple[str, int], dt.datetime] = {}
        self._protected_message_deletions: set[int] = set()

    async def _config(self, guild_id: int, *, refresh: bool = False) -> AntiNukeSettings:
        if refresh or guild_id not in self._config_cache:
            config = await repo.get_or_create_anti_nuke_config(guild_id)
            self._config_cache[guild_id] = _parse_config(config)
        return self._config_cache[guild_id]

    async def _update_config(self, guild_id: int, **fields) -> AntiNukeSettings:
        config = await repo.update_anti_nuke_config(guild_id, **fields)
        parsed = _parse_config(config)
        self._config_cache[guild_id] = parsed
        return parsed

    def _is_trusted(self, guild: discord.Guild, user_id: int, config: AntiNukeSettings) -> bool:
        bot_user_id = self.bot.user.id if self.bot.user else 0
        return user_id in {guild.owner_id, settings.bot_owner_id, bot_user_id} or user_id in config.whitelist

    def _feature_enabled(self, config: AntiNukeSettings, feature: str) -> bool:
        return config.enabled and config.features.get(feature, True)

    def _mark_rollback(self, kind: str, target_id: int) -> None:
        self._rollback_targets[(kind, target_id)] = discord.utils.utcnow() + dt.timedelta(seconds=8)

    def _is_rollback(self, kind: str, target_id: int) -> bool:
        key = (kind, target_id)
        expiry = self._rollback_targets.get(key)
        if expiry is None:
            return False
        if expiry < discord.utils.utcnow():
            self._rollback_targets.pop(key, None)
            return False
        self._rollback_targets.pop(key, None)
        return True

    async def _audit_entry(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        *,
        target_id: int | None = None,
        retries: int = 3,
    ) -> discord.AuditLogEntry | None:
        if not guild.me or not guild.me.guild_permissions.view_audit_log:
            return None
        for attempt in range(retries):
            if attempt:
                await asyncio.sleep(0.55)
            after = discord.utils.utcnow() - dt.timedelta(seconds=12)
            try:
                async for entry in guild.audit_logs(limit=8, action=action, after=after):
                    if entry.id in self._handled_audit_entries:
                        continue
                    entry_target_id = getattr(entry.target, "id", None)
                    if target_id is not None and entry_target_id != target_id:
                        continue
                    self._handled_audit_entries.add(entry.id)
                    if len(self._handled_audit_entries) > 5000:
                        self._handled_audit_entries.clear()
                    return entry
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Gagal membaca audit log anti-nuke pada guild %s", guild.id)
                return None
        return None

    async def _log(
        self,
        guild: discord.Guild,
        config: AntiNukeSettings,
        *,
        feature: str,
        actor_id: int | None,
        target: str,
        action: str,
        punishment: str = "Belum melewati batas",
        rollback: str = "Tidak tersedia",
    ) -> None:
        channel = guild.get_channel(config.log_channel_id) if config.log_channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return
        actor = f"<@{actor_id}> (`{actor_id}`)" if actor_id else "Tidak diketahui"
        description = (
            f"**Proteksi:** {FEATURE_LABELS[feature]}\n"
            f"**Pelaku:** {actor}\n"
            f"**Target:** {target}\n"
            f"**Aksi:** {action}\n"
            f"**Rollback:** {rollback}\n"
            f"**Hukuman:** {punishment}\n"
            f"**Waktu:** {discord.utils.format_dt(discord.utils.utcnow(), style='F')}"
        )
        try:
            await channel.send(
                view=build_plain_container(title="🛡️ Anti-Nuke Alert", description=description),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            logger.exception("Gagal mengirim log anti-nuke pada guild %s", guild.id)

    def _record_violation(
        self,
        guild_id: int,
        actor_id: int,
        feature: str,
        config: AntiNukeSettings,
    ) -> int:
        now = discord.utils.utcnow()
        cutoff = now - dt.timedelta(seconds=config.window_seconds)
        violations = self._violations[(guild_id, actor_id, feature)]
        while violations and violations[0] < cutoff:
            violations.popleft()
        violations.append(now)
        return len(violations)

    async def _punish(self, guild: discord.Guild, actor_id: int, config: AntiNukeSettings, reason: str) -> str:
        if config.punishment == "none":
            return "Hanya log"
        member = guild.get_member(actor_id)
        if member is None:
            try:
                member = await guild.fetch_member(actor_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None
        try:
            if config.punishment == "ban":
                await guild.ban(discord.Object(id=actor_id), reason=reason, delete_message_seconds=0)
                return "Ban"
            if config.punishment == "kick":
                if member is None:
                    return "Kick gagal: member tidak ditemukan"
                await member.kick(reason=reason)
                return "Kick"
            if member is None or guild.me is None:
                return "Cabut role gagal: member tidak ditemukan"
            removable = [
                role
                for role in member.roles
                if role != guild.default_role and not role.managed and role < guild.me.top_role
            ]
            if removable:
                await member.remove_roles(*removable, reason=reason)
            return f"Cabut {len(removable)} role"
        except (discord.Forbidden, discord.HTTPException) as exc:
            return f"Gagal: {exc}"

    async def _message_was_deleted_by_moderator(self, message: discord.Message) -> bool:
        guild = message.guild
        if not guild.me or not guild.me.guild_permissions.view_audit_log:
            return False
        for attempt in range(2):
            if attempt:
                await asyncio.sleep(0.55)
            after = discord.utils.utcnow() - dt.timedelta(seconds=12)
            try:
                async for entry in guild.audit_logs(
                    limit=8,
                    action=discord.AuditLogAction.message_delete,
                    after=after,
                ):
                    if getattr(entry.target, "id", None) != message.author.id:
                        continue
                    channel = getattr(entry.extra, "channel", None)
                    if channel is not None and channel.id != message.channel.id:
                        continue
                    return entry.user is not None and entry.user.id != message.author.id
            except (discord.Forbidden, discord.HTTPException):
                logger.exception("Gagal membaca audit log ghost ping pada guild %s", guild.id)
                return False
        return False

    async def _violation(
        self,
        guild: discord.Guild,
        *,
        feature: str,
        actor_id: int | None,
        target: str,
        action: str,
        rollback: str,
        config: AntiNukeSettings | None = None,
    ) -> None:
        config = config or await self._config(guild.id)
        if actor_id is None:
            await self._log(
                guild,
                config,
                feature=feature,
                actor_id=None,
                target=target,
                action=f"{action} (pelaku tidak ditemukan di audit log)",
                rollback=rollback,
            )
            return
        if self._is_trusted(guild, actor_id, config):
            return
        count = self._record_violation(guild.id, actor_id, feature, config)
        punishment = f"Pelanggaran {count}/{config.violation_limit}"
        if count >= config.violation_limit:
            punishment = await self._punish(
                guild,
                actor_id,
                config,
                reason=f"Anti-nuke: {FEATURE_LABELS[feature]}",
            )
            self._violations.pop((guild.id, actor_id, feature), None)
        await self._log(
            guild,
            config,
            feature=feature,
            actor_id=actor_id,
            target=target,
            action=action,
            punishment=punishment,
            rollback=rollback,
        )

    async def _audit_violation(
        self,
        guild: discord.Guild,
        *,
        feature: str,
        audit_action: discord.AuditLogAction,
        target_id: int | None,
        target: str,
        action: str,
        rollback: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        config = await self._config(guild.id)
        if not self._feature_enabled(config, feature):
            return
        entry = await self._audit_entry(guild, audit_action, target_id=target_id)
        actor_id = entry.user.id if entry and entry.user else None
        if entry is None:
            await self._violation(
                guild,
                feature=feature,
                actor_id=None,
                target=target,
                action=action,
                rollback="Dilewati: pelaku tidak ditemukan di audit log",
                config=config,
            )
            return
        if actor_id is not None and self._is_trusted(guild, actor_id, config):
            return
        rollback_text = "Tidak tersedia"
        if rollback is not None:
            try:
                await rollback()
                rollback_text = "Berhasil"
            except (discord.Forbidden, discord.HTTPException, OSError, ValueError) as exc:
                rollback_text = f"Gagal: {exc}"
        await self._violation(
            guild,
            feature=feature,
            actor_id=actor_id,
            target=target,
            action=action,
            rollback=rollback_text,
            config=config,
        )

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        async def rollback() -> None:
            await guild.unban(user, reason="Anti-nuke rollback ban ilegal")

        await self._audit_violation(
            guild,
            feature="ban",
            audit_action=discord.AuditLogAction.ban,
            target_id=user.id,
            target=f"{user} (`{user.id}`)",
            action="Member diban",
            rollback=rollback,
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        config = await self._config(member.guild.id)
        if not config.enabled:
            return
        if self._feature_enabled(config, "kick"):
            entry = await self._audit_entry(
                member.guild,
                discord.AuditLogAction.kick,
                target_id=member.id,
                retries=2,
            )
            if entry is not None:
                await self._violation(
                    member.guild,
                    feature="kick",
                    actor_id=entry.user.id if entry.user else None,
                    target=f"{member} (`{member.id}`)",
                    action="Member dikick",
                    rollback="Kick tidak dapat dipulihkan otomatis",
                    config=config,
                )
                return
        if self._feature_enabled(config, "prune"):
            entry = await self._audit_entry(
                member.guild,
                discord.AuditLogAction.member_prune,
                retries=2,
            )
            if entry is not None:
                removed = getattr(entry.extra, "members_removed", "beberapa")
                await self._violation(
                    member.guild,
                    feature="prune",
                    actor_id=entry.user.id if entry.user else None,
                    target=f"{removed} member",
                    action="Member dipruning",
                    rollback="Prune tidak dapat dipulihkan otomatis",
                    config=config,
                )

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        if self._is_rollback("role_create", role.id):
            return

        async def rollback() -> None:
            await role.delete(reason="Anti-nuke rollback role create ilegal")

        await self._audit_violation(
            role.guild,
            feature="role_create",
            audit_action=discord.AuditLogAction.role_create,
            target_id=role.id,
            target=f"@{role.name} (`{role.id}`)",
            action="Role dibuat",
            rollback=rollback,
        )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        async def rollback() -> None:
            recreated = await role.guild.create_role(
                name=role.name,
                permissions=role.permissions,
                colour=role.colour,
                hoist=role.hoist,
                mentionable=role.mentionable,
                reason="Anti-nuke rollback role delete ilegal",
            )
            self._mark_rollback("role_create", recreated.id)
            try:
                await recreated.edit(position=role.position)
            except discord.HTTPException:
                pass

        await self._audit_violation(
            role.guild,
            feature="role_delete",
            audit_action=discord.AuditLogAction.role_delete,
            target_id=role.id,
            target=f"@{role.name} (`{role.id}`)",
            action="Role dihapus",
            rollback=rollback,
        )

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        if self._is_rollback("role_update", after.id):
            return
        config = await self._config(after.guild.id)
        permission_changes = _new_dangerous_permissions(before.permissions, after.permissions)
        renamed = before.name != after.name
        features = []
        if permission_changes and self._feature_enabled(config, "dangerous_role_permission_update"):
            features.append(("dangerous_role_permission_update", f"Permission berbahaya ditambahkan: {', '.join(permission_changes)}"))
        if renamed and self._feature_enabled(config, "role_rename"):
            features.append(("role_rename", f"Role diubah nama dari `{before.name}` menjadi `{after.name}`"))
        if not features:
            return
        entry = await self._audit_entry(after.guild, discord.AuditLogAction.role_update, target_id=after.id)
        actor_id = entry.user.id if entry and entry.user else None
        if entry is None:
            for feature, action in features:
                await self._violation(
                    after.guild,
                    feature=feature,
                    actor_id=None,
                    target=f"@{before.name} (`{after.id}`)",
                    action=action,
                    rollback="Dilewati: pelaku tidak ditemukan di audit log",
                    config=config,
                )
            return
        if actor_id is not None and self._is_trusted(after.guild, actor_id, config):
            return
        rollback_text = "Berhasil"
        try:
            self._mark_rollback("role_update", after.id)
            await after.edit(
                name=before.name,
                permissions=before.permissions,
                colour=before.colour,
                hoist=before.hoist,
                mentionable=before.mentionable,
                reason="Anti-nuke rollback role update ilegal",
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            rollback_text = f"Gagal: {exc}"
        for feature, action in features:
            await self._violation(
                after.guild,
                feature=feature,
                actor_id=actor_id,
                target=f"@{before.name} (`{after.id}`)",
                action=action,
                rollback=rollback_text,
                config=config,
            )

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel) -> None:
        if self._is_rollback("channel_create", channel.id):
            return

        async def rollback() -> None:
            await channel.delete(reason="Anti-nuke rollback channel create ilegal")

        await self._audit_violation(
            channel.guild,
            feature="channel_create",
            audit_action=discord.AuditLogAction.channel_create,
            target_id=channel.id,
            target=f"{channel.name} (`{channel.id}`)",
            action="Channel dibuat",
            rollback=rollback,
        )

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        async def rollback() -> None:
            recreated = await channel.clone(reason="Anti-nuke rollback channel delete ilegal")
            self._mark_rollback("channel_create", recreated.id)
            try:
                await recreated.edit(position=channel.position)
            except discord.HTTPException:
                pass

        await self._audit_violation(
            channel.guild,
            feature="channel_delete",
            audit_action=discord.AuditLogAction.channel_delete,
            target_id=channel.id,
            target=f"{channel.name} (`{channel.id}`)",
            action="Channel dihapus",
            rollback=rollback,
        )

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
        if before.name == after.name or self._is_rollback("channel_update", after.id):
            return

        async def rollback() -> None:
            self._mark_rollback("channel_update", after.id)
            await after.edit(name=before.name, reason="Anti-nuke rollback channel rename ilegal")

        await self._audit_violation(
            after.guild,
            feature="channel_rename",
            audit_action=discord.AuditLogAction.channel_update,
            target_id=after.id,
            target=f"{before.name} (`{after.id}`)",
            action=f"Channel diubah nama menjadi `{after.name}`",
            rollback=rollback,
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if not member.bot:
            return

        async def rollback() -> None:
            await member.kick(reason="Anti-nuke rollback bot add ilegal")

        await self._audit_violation(
            member.guild,
            feature="bot_add",
            audit_action=discord.AuditLogAction.bot_add,
            target_id=member.id,
            target=f"{member} (`{member.id}`)",
            action="Bot ditambahkan ke server",
            rollback=rollback,
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        added_roles = [role for role in after.roles if role not in before.roles and _has_dangerous_permissions(role.permissions)]
        if not added_roles:
            return
        config = await self._config(after.guild.id)
        if not self._feature_enabled(config, "dangerous_role_add"):
            return
        entry = await self._audit_entry(
            after.guild,
            discord.AuditLogAction.member_role_update,
            target_id=after.id,
        )
        actor_id = entry.user.id if entry and entry.user else None
        if entry is None:
            await self._violation(
                after.guild,
                feature="dangerous_role_add",
                actor_id=None,
                target=f"{after} (`{after.id}`): {', '.join(role.name for role in added_roles)}",
                action="Role berbahaya diberikan",
                rollback="Dilewati: pelaku tidak ditemukan di audit log",
                config=config,
            )
            return
        if actor_id is not None and self._is_trusted(after.guild, actor_id, config):
            return
        rollback_text = "Berhasil"
        try:
            await after.remove_roles(*added_roles, reason="Anti-nuke rollback dangerous role add")
        except (discord.Forbidden, discord.HTTPException) as exc:
            rollback_text = f"Gagal: {exc}"
        await self._violation(
            after.guild,
            feature="dangerous_role_add",
            actor_id=actor_id,
            target=f"{after} (`{after.id}`): {', '.join(role.name for role in added_roles)}",
            action="Role berbahaya diberikan",
            rollback=rollback_text,
            config=config,
        )

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild) -> None:
        renamed = before.name != after.name
        icon_changed = before.icon != after.icon
        config = await self._config(after.id)
        features = []
        if renamed and self._feature_enabled(config, "server_rename"):
            features.append(("server_rename", f"Server diubah nama dari `{before.name}` menjadi `{after.name}`"))
        if icon_changed and self._feature_enabled(config, "server_icon_change"):
            features.append(("server_icon_change", "Icon server diubah"))
        if not features:
            return
        entry = await self._audit_entry(after, discord.AuditLogAction.guild_update, target_id=after.id)
        actor_id = entry.user.id if entry and entry.user else None
        if entry is None:
            for feature, action in features:
                await self._violation(
                    after,
                    feature=feature,
                    actor_id=None,
                    target=f"{before.name} (`{after.id}`)",
                    action=action,
                    rollback="Dilewati: pelaku tidak ditemukan di audit log",
                    config=config,
                )
            return
        if actor_id is not None and self._is_trusted(after, actor_id, config):
            return
        rollback_text = "Berhasil"
        try:
            edit_fields = {
                "name": before.name if renamed else after.name,
                "reason": "Anti-nuke rollback server update ilegal",
            }
            if icon_changed:
                edit_fields["icon"] = await before.icon.read() if before.icon else None
            await after.edit(**edit_fields)
        except (discord.Forbidden, discord.HTTPException) as exc:
            rollback_text = f"Gagal: {exc}"
        for feature, action in features:
            await self._violation(
                after,
                feature=feature,
                actor_id=actor_id,
                target=f"{before.name} (`{after.id}`)",
                action=action,
                rollback=rollback_text,
                config=config,
            )

    @commands.Cog.listener()
    async def on_guild_emojis_update(
        self,
        guild: discord.Guild,
        before: tuple[discord.Emoji, ...],
        after: tuple[discord.Emoji, ...],
    ) -> None:
        after_ids = {emoji.id for emoji in after}
        deleted = [emoji for emoji in before if emoji.id not in after_ids]
        for emoji in deleted:
            async def rollback(deleted_emoji=emoji) -> None:
                image = await deleted_emoji.read()
                await guild.create_custom_emoji(
                    name=deleted_emoji.name,
                    image=image,
                    reason="Anti-nuke rollback emoji delete ilegal",
                )

            await self._audit_violation(
                guild,
                feature="emoji_delete",
                audit_action=discord.AuditLogAction.emoji_delete,
                target_id=emoji.id,
                target=f":{emoji.name}: (`{emoji.id}`)",
                action="Emoji dihapus",
                rollback=rollback,
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None:
            return
        config = await self._config(message.guild.id)
        if not config.enabled or self._is_trusted(message.guild, message.author.id, config):
            return
        feature = None
        action = None
        unique_mentions = {user.id for user in message.mentions}
        unique_mentions.update(role.id for role in message.role_mentions)
        if self._feature_enabled(config, "mention") and (
            message.mention_everyone or len(unique_mentions) >= config.mention_limit
        ):
            feature = "mention"
            action = f"Mass mention ({len(unique_mentions)} target)"
        elif self._feature_enabled(config, "invite_link") and INVITE_PATTERN.search(message.content):
            feature = "invite_link"
            action = "Mengirim invite link Discord"
        if feature is None:
            return
        rollback_text = "Berhasil"
        try:
            self._protected_message_deletions.add(message.id)
            await message.delete(reason=f"Anti-nuke: {FEATURE_LABELS[feature]}")
            asyncio.get_running_loop().call_later(
                15,
                self._protected_message_deletions.discard,
                message.id,
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            self._protected_message_deletions.discard(message.id)
            rollback_text = f"Gagal: {exc}"
        await self._violation(
            message.guild,
            feature=feature,
            actor_id=message.author.id,
            target=f"#{getattr(message.channel, 'name', message.channel.id)} (`{message.channel.id}`)",
            action=action,
            rollback=rollback_text,
            config=config,
        )

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if message.id in self._protected_message_deletions:
            self._protected_message_deletions.discard(message.id)
            return
        if message.guild is None or not _message_mentions(message):
            return
        config = await self._config(message.guild.id)
        if not self._feature_enabled(config, "ghost_ping"):
            return
        if self._is_trusted(message.guild, message.author.id, config):
            return
        if await self._message_was_deleted_by_moderator(message):
            return
        await self._violation(
            message.guild,
            feature="ghost_ping",
            actor_id=message.author.id,
            target=f"#{getattr(message.channel, 'name', message.channel.id)} (`{message.channel.id}`)",
            action="Menghapus pesan yang berisi mention",
            rollback="Pesan sudah terhapus",
            config=config,
        )


@anti_nuke_group.command(name="setup", description="Aktifkan dan konfigurasi anti-nuke.")
@app_commands.guild_only()
@app_commands.describe(
    log_channel="Channel log anti-nuke",
    punishment="Hukuman ketika batas pelanggaran tercapai",
    violation_limit="Jumlah pelanggaran dalam window sebelum dihukum",
    window_seconds="Rentang hitung pelanggaran dalam detik",
    mention_limit="Jumlah mention yang dianggap mass mention",
)
@app_commands.choices(punishment=PUNISHMENT_CHOICES)
@_manager_check()
async def anti_nuke_setup(
    interaction: discord.Interaction,
    log_channel: discord.TextChannel,
    punishment: app_commands.Choice[str],
    violation_limit: app_commands.Range[int, 1, 10] = 1,
    window_seconds: app_commands.Range[int, 3, 60] = 10,
    mention_limit: app_commands.Range[int, 1, 25] = 5,
) -> None:
    await repo.update_anti_nuke_config(
        interaction.guild_id,
        enabled=True,
        log_channel_id=log_channel.id,
        punishment=punishment.value,
        violation_limit=violation_limit,
        window_seconds=window_seconds,
        mention_limit=mention_limit,
    )
    cog = interaction.client.get_cog("Anti Nuke")
    if isinstance(cog, AntiNukeCog):
        await cog._config(interaction.guild_id, refresh=True)
    await interaction.response.send_message(
        view=build_plain_container(
            title="✅ Anti-Nuke Aktif",
            description=(
                f"**Log:** {log_channel.mention}\n"
                f"**Hukuman:** `{punishment.value}`\n"
                f"**Batas:** `{violation_limit}` pelanggaran / `{window_seconds}` detik\n"
                f"**Mass mention:** `{mention_limit}` target\n\n"
                "Semua 18 proteksi aktif. Gunakan `/antinuke feature` untuk mengubah fitur tertentu."
            ),
        ),
        ephemeral=True,
    )


@anti_nuke_group.command(name="toggle", description="Aktifkan atau nonaktifkan anti-nuke.")
@app_commands.guild_only()
@app_commands.describe(enabled="Status anti-nuke")
@_manager_check()
async def anti_nuke_toggle(interaction: discord.Interaction, enabled: bool) -> None:
    cog = interaction.client.get_cog("Anti Nuke")
    if isinstance(cog, AntiNukeCog):
        await cog._update_config(interaction.guild_id, enabled=enabled)
    else:
        await repo.update_anti_nuke_config(interaction.guild_id, enabled=enabled)
    await interaction.response.send_message(
        f"Anti-nuke telah **{'diaktifkan' if enabled else 'dinonaktifkan'}**.",
        ephemeral=True,
    )


@anti_nuke_group.command(name="feature", description="Aktifkan atau nonaktifkan satu proteksi.")
@app_commands.guild_only()
@app_commands.choices(feature=FEATURE_CHOICES)
@_manager_check()
async def anti_nuke_feature(
    interaction: discord.Interaction,
    feature: app_commands.Choice[str],
    enabled: bool,
) -> None:
    config = await repo.get_or_create_anti_nuke_config(interaction.guild_id)
    try:
        features = json.loads(config.features_json or "{}")
    except (TypeError, json.JSONDecodeError):
        features = {}
    features[feature.value] = enabled
    cog = interaction.client.get_cog("Anti Nuke")
    fields = {"features_json": json.dumps(features, separators=(",", ":"))}
    if isinstance(cog, AntiNukeCog):
        await cog._update_config(interaction.guild_id, **fields)
    else:
        await repo.update_anti_nuke_config(interaction.guild_id, **fields)
    await interaction.response.send_message(
        f"**{feature.name}** telah **{'diaktifkan' if enabled else 'dinonaktifkan'}**.",
        ephemeral=True,
    )


@anti_nuke_group.command(name="whitelist-add", description="Tambahkan member tepercaya.")
@app_commands.guild_only()
@_manager_check()
async def anti_nuke_whitelist_add(interaction: discord.Interaction, member: discord.Member) -> None:
    config = await repo.get_or_create_anti_nuke_config(interaction.guild_id)
    try:
        whitelist = {int(value) for value in json.loads(config.whitelist_json or "[]")}
    except (TypeError, ValueError, json.JSONDecodeError):
        whitelist = set()
    whitelist.add(member.id)
    fields = {"whitelist_json": json.dumps(sorted(whitelist))}
    cog = interaction.client.get_cog("Anti Nuke")
    if isinstance(cog, AntiNukeCog):
        await cog._update_config(interaction.guild_id, **fields)
    else:
        await repo.update_anti_nuke_config(interaction.guild_id, **fields)
    await interaction.response.send_message(f"{member.mention} ditambahkan ke whitelist anti-nuke.", ephemeral=True)


@anti_nuke_group.command(name="whitelist-remove", description="Hapus member dari whitelist.")
@app_commands.guild_only()
@_manager_check()
async def anti_nuke_whitelist_remove(interaction: discord.Interaction, member: discord.Member) -> None:
    config = await repo.get_or_create_anti_nuke_config(interaction.guild_id)
    try:
        whitelist = {int(value) for value in json.loads(config.whitelist_json or "[]")}
    except (TypeError, ValueError, json.JSONDecodeError):
        whitelist = set()
    whitelist.discard(member.id)
    fields = {"whitelist_json": json.dumps(sorted(whitelist))}
    cog = interaction.client.get_cog("Anti Nuke")
    if isinstance(cog, AntiNukeCog):
        await cog._update_config(interaction.guild_id, **fields)
    else:
        await repo.update_anti_nuke_config(interaction.guild_id, **fields)
    await interaction.response.send_message(f"{member.mention} dihapus dari whitelist anti-nuke.", ephemeral=True)


@anti_nuke_group.command(name="status", description="Lihat status dan konfigurasi anti-nuke.")
@app_commands.guild_only()
@_manager_check()
async def anti_nuke_status(interaction: discord.Interaction) -> None:
    cog = interaction.client.get_cog("Anti Nuke")
    if isinstance(cog, AntiNukeCog):
        config = await cog._config(interaction.guild_id, refresh=True)
    else:
        config = _parse_config(await repo.get_or_create_anti_nuke_config(interaction.guild_id))
    features = "\n".join(
        f"{'✅' if config.features[key] else '❌'} {label}"
        for key, label in FEATURE_LABELS.items()
    )
    whitelist = ", ".join(f"<@{user_id}>" for user_id in sorted(config.whitelist)) or "Kosong"
    await interaction.response.send_message(
        view=build_plain_container(
            title="🛡️ Status Anti-Nuke",
            description=(
                f"**Status:** {'Aktif' if config.enabled else 'Nonaktif'}\n"
                f"**Log:** {f'<#{config.log_channel_id}>' if config.log_channel_id else 'Belum diatur'}\n"
                f"**Hukuman:** `{config.punishment}`\n"
                f"**Batas:** `{config.violation_limit}` / `{config.window_seconds}` detik\n"
                f"**Mention limit:** `{config.mention_limit}`\n"
                f"**Whitelist:** {whitelist}\n\n{features}"
            ),
        ),
        ephemeral=True,
    )


async def setup(bot: commands.Bot) -> None:
    bot.tree.add_command(anti_nuke_group)
    await bot.add_cog(AntiNukeCog(bot))
