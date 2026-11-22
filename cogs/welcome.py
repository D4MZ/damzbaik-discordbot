"""Cog: Welcome & Leave Message System.

Welcome dan leave memakai command dan logika yang sama; perbedaannya hanya
prefix kolom di GuildConfig (welcome_* / leave_*) dan event pemicunya.
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from database import repositories as repo
from ui.modals import MemberEmbedModal, MemberTextModal
from utils.components import build_plain_container
from utils.logger import get_logger
from utils.permissions import require_permissions
from utils.placeholders import resolve_member_placeholders

logger = get_logger(__name__)

KINDS = {
    "welcome": {"label": "Welcome", "default": "Welcome {user} to {server}!"},
    "leave": {"label": "Leave", "default": "{username} telah meninggalkan {server}."},
}


def build_member_payload(config, member: discord.Member, kind: str = "welcome", *, preview: bool = False) -> dict:
    """Mengembalikan kwargs siap kirim menggunakan container polos."""
    meta = KINDS[kind]
    get = lambda field: getattr(config, f"{kind}_{field}")  # noqa: E731
    preview_title = f"Preview {meta['label']}"

    if get("type") == "embed":
        description = resolve_member_placeholders(get("embed_description") or meta["default"], member)
        title = resolve_member_placeholders(get("embed_title") or "", member) or None
        if preview:
            title = f"{preview_title} — {title}" if title else preview_title
        text_parts = []
        if get("mention"):
            text_parts.append(member.mention)
        if get("embed_author"):
            text_parts.append(f"-# {get('embed_author')}")
        text_parts.append(description)
        if get("embed_footer"):
            text_parts.append(f"-# {get('embed_footer')}")
        if get("timestamp"):
            text_parts.append(f"-# {discord.utils.format_dt(discord.utils.utcnow(), style='f')}")
        media = get("embed_image") or get("embed_thumbnail") or member.display_avatar.url
        view = build_plain_container(
            title=title,
            description="\n\n".join(text_parts),
            media=media,
            media_description=f"Avatar {member.display_name}",
        )
        return {"view": view}

    text = resolve_member_placeholders(get("message"), member)
    if get("mention") and member.mention not in text:
        text = f"{member.mention}\n\n{text}"
    return {"view": build_plain_container(title=preview_title if preview else None, description=text)}


def build_welcome_payload(config, member: discord.Member, *, preview: bool = False) -> dict:
    return build_member_payload(config, member, "welcome", preview=preview)


def _reply(title: str, description: str) -> dict:
    return {"view": build_plain_container(title=title, description=description), "ephemeral": True}


def build_member_group(kind: str) -> app_commands.Group:
    meta = KINDS[kind]
    label = meta["label"]
    group = app_commands.Group(name=kind, description=f"Kelola pesan {label.lower()} member.")

    async def save(interaction: discord.Interaction, title: str, description: str, **fields) -> None:
        await repo.update_guild_config(interaction.guild_id, **{f"{kind}_{k}": v for k, v in fields.items()})
        await interaction.response.send_message(**_reply(f"✅ {title}", description))

    @group.command(name="enable", description=f"Aktifkan pesan {label.lower()}.")
    @app_commands.describe(channel=f"Channel tujuan pesan {label.lower()}")
    @require_permissions(manage_guild=True)
    async def enable(interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await save(
            interaction, f"{label} Diaktifkan", f"Pesan {label.lower()} akan dikirim ke {channel.mention}.",
            enabled=True, channel_id=channel.id,
        )

    @group.command(name="disable", description=f"Nonaktifkan pesan {label.lower()}.")
    @require_permissions(manage_guild=True)
    async def disable(interaction: discord.Interaction) -> None:
        await save(interaction, f"{label} Dinonaktifkan", f"Pesan {label.lower()} tidak akan dikirim lagi.", enabled=False)

    @group.command(name="set-type", description=f"Pilih tipe pesan {label.lower()}: text atau embed.")
    @app_commands.choices(
        type=[app_commands.Choice(name="Text biasa", value="text"), app_commands.Choice(name="Embed", value="embed")]
    )
    @require_permissions(manage_guild=True)
    async def set_type(interaction: discord.Interaction, type: app_commands.Choice[str]) -> None:
        await save(interaction, f"Tipe {label} Diubah", f"Tipe diatur ke `{type.value}`.", type=type.value)

    @group.command(name="set-text", description=f"Atur teks {label.lower()} (mode text biasa).")
    @require_permissions(manage_guild=True)
    async def set_text(interaction: discord.Interaction) -> None:
        async def on_submit(modal_interaction: discord.Interaction, message: str) -> None:
            await save(modal_interaction, f"Teks {label} Disimpan", f"```{message}```", message=message)

        await interaction.response.send_modal(MemberTextModal(label, meta["default"], on_submit))

    @group.command(name="set-embed", description=f"Atur embed {label.lower()}.")
    @require_permissions(manage_guild=True)
    async def set_embed(interaction: discord.Interaction) -> None:
        async def on_submit(modal_interaction: discord.Interaction, data: dict) -> None:
            await save(modal_interaction, f"{label} Disimpan", f"Konfigurasi {label.lower()} container berhasil disimpan.", **data)

        await interaction.response.send_modal(MemberEmbedModal(label, meta["default"], on_submit))

    @group.command(name="set-mention", description=f"Aktif/nonaktifkan mention member di {label.lower()}.")
    @require_permissions(manage_guild=True)
    async def set_mention(interaction: discord.Interaction, enabled: bool) -> None:
        await save(interaction, f"{label} Diperbarui", f"Mention member: `{enabled}`", mention=enabled)

    @group.command(name="set-timestamp", description=f"Aktif/nonaktifkan timestamp di embed {label.lower()}.")
    @require_permissions(manage_guild=True)
    async def set_timestamp(interaction: discord.Interaction, enabled: bool) -> None:
        await save(interaction, f"{label} Diperbarui", f"Timestamp: `{enabled}`", timestamp=enabled)

    @group.command(name="preview", description=f"Preview pesan {label.lower()}.")
    @require_permissions(manage_guild=True)
    async def preview(interaction: discord.Interaction) -> None:
        config = await repo.get_or_create_guild_config(interaction.guild_id)
        payload = build_member_payload(config, interaction.user, kind, preview=True)
        await interaction.response.send_message(ephemeral=True, **payload)

    return group


class WelcomeCog(commands.Cog, name="Welcome"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _send(self, member: discord.Member, kind: str) -> None:
        config = await repo.get_or_create_guild_config(member.guild.id)
        if not getattr(config, f"{kind}_enabled") or not getattr(config, f"{kind}_channel_id"):
            return
        channel = member.guild.get_channel(getattr(config, f"{kind}_channel_id"))
        if channel is None:
            return
        try:
            await channel.send(**build_member_payload(config, member, kind))
        except discord.Forbidden:
            logger.warning("Tidak punya izin mengirim pesan %s di guild %s", kind, member.guild.id)
        except Exception:
            logger.exception("Gagal mengirim pesan %s di guild %s", kind, member.guild.id)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self._send(member, "welcome")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await self._send(member, "leave")


async def setup(bot: commands.Bot) -> None:
    for kind in KINDS:
        bot.tree.add_command(build_member_group(kind))
    await bot.add_cog(WelcomeCog(bot))
