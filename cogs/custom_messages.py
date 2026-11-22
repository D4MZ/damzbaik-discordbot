"""Custom message builder: legacy embed, Components V2, atau keduanya."""

from __future__ import annotations

import io
import json
import secrets

import discord
from discord import app_commands
from discord.ext import commands

from config import settings
from database import repositories as repo
from services.custom_messages import (
    DEFAULT_PAYLOAD,
    CustomMessageValidationError,
    build_legacy_embeds,
    build_v2_view,
    dump_payload,
    parse_payload,
    prepare_v2_message,
    send_custom_message,
)
from services.custom_web import get_or_create_builder_webhook
from utils.components import build_plain_container
from utils.permissions import require_permissions

custom_group = app_commands.Group(name="custom", description="Buat pesan custom seperti Discohook.")

MODE_CHOICES = [
    app_commands.Choice(name="Legacy Embed", value="legacy"),
    app_commands.Choice(name="Components V2", value="v2"),
    app_commands.Choice(name="Both / Keduanya", value="both"),
]


def editor_url(token: str) -> str | None:
    if not (settings.custom_web_enabled or settings.dashboard_enabled):
        return None
    if not settings.custom_web_public_url:
        return None
    return f"{settings.custom_web_public_url}/custom/{token}"


async def get_draft_or_error(interaction: discord.Interaction, draft_id: int):
    draft = await repo.get_custom_message_draft(draft_id, interaction.guild_id)
    if draft is None:
        await interaction.response.send_message(
            view=build_plain_container(
                title="❌ Draft Tidak Ditemukan",
                description=f"Draft `{draft_id}` tidak ditemukan di server ini.",
            ),
            ephemeral=True,
        )
    return draft


class CustomQuickEditModal(discord.ui.Modal, title="Quick Edit Custom Message"):
    content = discord.ui.TextInput(
        label="Message Content",
        required=False,
        max_length=2000,
        style=discord.TextStyle.paragraph,
    )
    legacy_title = discord.ui.TextInput(label="Legacy Embed Title", required=False, max_length=256)
    legacy_description = discord.ui.TextInput(
        label="Legacy Embed Description",
        required=False,
        max_length=4000,
        style=discord.TextStyle.paragraph,
    )
    v2_text = discord.ui.TextInput(
        label="Components V2 Text",
        required=False,
        max_length=4000,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, draft):
        super().__init__()
        self.draft = draft
        payload = parse_payload(draft.payload_json)
        self.content.default = str(payload.get("content") or "")
        self.legacy_title.default = str(payload["legacy"].get("title") or "")
        self.legacy_description.default = str(payload["legacy"].get("description") or "")
        text_component = next(
            (
                component
                for component in payload["v2"].get("components", [])
                if isinstance(component, dict) and component.get("type") == "text"
            ),
            {"content": ""},
        )
        self.v2_text.default = str(text_component.get("content") or "")

    async def on_submit(self, interaction: discord.Interaction) -> None:
        payload = parse_payload(self.draft.payload_json)
        payload["content"] = str(self.content.value)
        payload["legacy"]["title"] = str(self.legacy_title.value)
        payload["legacy"]["description"] = str(self.legacy_description.value)
        components = payload["v2"].get("components", [])
        text_component = next(
            (
                component
                for component in components
                if isinstance(component, dict) and component.get("type") == "text"
            ),
            None,
        )
        if text_component is None:
            components.insert(0, {"type": "text", "content": str(self.v2_text.value)})
        else:
            text_component["content"] = str(self.v2_text.value)
        await repo.update_custom_message_draft(
            self.draft.id,
            interaction.guild_id,
            payload_json=dump_payload(payload),
        )
        await interaction.response.send_message(
            view=build_plain_container(
                title="✅ Quick Edit Disimpan",
                description=f"Draft `{self.draft.id}` berhasil diperbarui.",
            ),
            ephemeral=True,
        )


@custom_group.command(name="create", description="Buat draft custom message baru.")
@app_commands.choices(mode=MODE_CHOICES)
@app_commands.describe(name="Nama draft", mode="Legacy, Components V2, atau keduanya")
@require_permissions(administrator=True)
async def custom_create(
    interaction: discord.Interaction,
    name: str,
    mode: app_commands.Choice[str],
) -> None:
    draft = await repo.create_custom_message_draft(
        guild_id=interaction.guild_id,
        owner_id=interaction.user.id,
        name=name.strip()[:100] or "Untitled",
        mode=mode.value,
        payload_json=dump_payload(DEFAULT_PAYLOAD),
        editor_token=secrets.token_urlsafe(32),
    )
    url = editor_url(draft.editor_token)
    description = (
        f"Draft ID: `{draft.id}`\nMode: `{draft.mode}`\n\n"
        + (f"[Buka Web Editor]({url})" if url else "Web editor belum aktif. Gunakan `/custom set-json` sebagai fallback.")
    )
    await interaction.response.send_message(
        view=build_plain_container(title="✅ Draft Dibuat", description=description),
        ephemeral=True,
    )


@custom_group.command(name="list", description="Lihat semua draft custom message.")
@require_permissions(administrator=True)
async def custom_list(interaction: discord.Interaction) -> None:
    drafts = await repo.list_custom_message_drafts(interaction.guild_id)
    if not drafts:
        description = "Belum ada draft. Buat dengan `/custom create`."
    else:
        description = "\n".join(
            f"`#{draft.id}` **{draft.name}** — `{draft.mode}`"
            for draft in drafts[:50]
        )
    await interaction.response.send_message(
        view=build_plain_container(title="✨ Custom Message Drafts", description=description),
        ephemeral=True,
    )


@custom_group.command(name="editor", description="Dapatkan link web editor atau template JSON draft.")
@require_permissions(administrator=True)
async def custom_editor(interaction: discord.Interaction, draft_id: int) -> None:
    draft = await get_draft_or_error(interaction, draft_id)
    if draft is None:
        return
    url = editor_url(draft.editor_token)
    payload = {
        "name": draft.name,
        "mode": draft.mode,
        "payload": parse_payload(draft.payload_json),
    }
    file = discord.File(
        io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")),
        filename=f"custom-draft-{draft.id}.json",
    )
    description = (
        f"[Buka Web Editor]({url})\n\nLink ini bersifat rahasia. Jangan dibagikan."
        if url
        else "Web editor belum tersedia pada hosting ini. Edit file JSON lalu upload lewat `/custom set-json`."
    )
    await interaction.response.send_message(
        content=description,
        file=file,
        ephemeral=True,
    )


@custom_group.command(name="quick-edit", description="Edit teks utama draft langsung dari Discord.")
@require_permissions(administrator=True)
async def custom_quick_edit(interaction: discord.Interaction, draft_id: int) -> None:
    draft = await get_draft_or_error(interaction, draft_id)
    if draft is None:
        return
    await interaction.response.send_modal(CustomQuickEditModal(draft))


@custom_group.command(name="set-mode", description="Ganti mode legacy, Components V2, atau keduanya.")
@app_commands.choices(mode=MODE_CHOICES)
@require_permissions(administrator=True)
async def custom_set_mode(
    interaction: discord.Interaction,
    draft_id: int,
    mode: app_commands.Choice[str],
) -> None:
    draft = await get_draft_or_error(interaction, draft_id)
    if draft is None:
        return
    await repo.update_custom_message_draft(draft.id, interaction.guild_id, mode=mode.value)
    await interaction.response.send_message(
        view=build_plain_container(
            title="✅ Mode Diperbarui",
            description=f"Draft `{draft.id}` sekarang memakai mode `{mode.value}`.",
        ),
        ephemeral=True,
    )


@custom_group.command(name="set-json", description="Perbarui draft dengan file JSON export editor.")
@app_commands.describe(draft_id="ID draft", file="File JSON hasil export", mode="Opsional: ganti mode draft")
@app_commands.choices(mode=MODE_CHOICES)
@require_permissions(administrator=True)
async def custom_set_json(
    interaction: discord.Interaction,
    draft_id: int,
    file: discord.Attachment,
    mode: app_commands.Choice[str] | None = None,
) -> None:
    draft = await get_draft_or_error(interaction, draft_id)
    if draft is None:
        return
    if file.size > 2 * 1024 * 1024:
        await interaction.response.send_message("File JSON maksimal 2 MB.", ephemeral=True)
        return
    try:
        imported = json.loads((await file.read()).decode("utf-8-sig"))
        if not isinstance(imported, dict):
            raise CustomMessageValidationError("Root JSON harus berupa object.")
        payload = parse_payload(imported.get("payload", imported))
        selected_mode = mode.value if mode else str(imported.get("mode") or draft.mode)
        if selected_mode in {"legacy", "both"}:
            build_legacy_embeds(payload)
        if selected_mode in {"v2", "both"}:
            build_v2_view(payload)
        if selected_mode not in {"legacy", "v2", "both"}:
            raise CustomMessageValidationError("Mode JSON tidak valid.")
    except (UnicodeDecodeError, json.JSONDecodeError, CustomMessageValidationError, ValueError) as exc:
        await interaction.response.send_message(f"JSON tidak valid: {exc}", ephemeral=True)
        return
    await repo.update_custom_message_draft(
        draft.id,
        interaction.guild_id,
        name=str(imported.get("name") or draft.name)[:100],
        mode=selected_mode,
        payload_json=dump_payload(payload),
    )
    await interaction.response.send_message(
        view=build_plain_container(
            title="✅ Draft Diperbarui",
            description=f"Draft `{draft.id}` berhasil di-import dari JSON.",
        ),
        ephemeral=True,
    )


@custom_group.command(name="preview", description="Preview draft custom message secara privat.")
@require_permissions(administrator=True)
async def custom_preview(interaction: discord.Interaction, draft_id: int) -> None:
    draft = await get_draft_or_error(interaction, draft_id)
    if draft is None:
        return
    payload = parse_payload(draft.payload_json)
    await interaction.response.defer(ephemeral=True)
    if draft.mode in {"legacy", "both"}:
        await interaction.followup.send(
            content=str(payload.get("content") or "")[:2000] or None,
            embeds=build_legacy_embeds(payload),
            ephemeral=True,
        )
    if draft.mode in {"v2", "both"}:
        view, files = await prepare_v2_message(payload)
        await interaction.followup.send(view=view, files=files, ephemeral=True)


@custom_group.command(name="send", description="Kirim draft melalui webhook bot.")
@app_commands.describe(draft_id="ID draft", channel="Channel tujuan")
@require_permissions(administrator=True)
async def custom_send(
    interaction: discord.Interaction,
    draft_id: int,
    channel: discord.TextChannel,
) -> None:
    draft = await get_draft_or_error(interaction, draft_id)
    if draft is None:
        return
    permissions = channel.permissions_for(interaction.guild.me)
    if not permissions.manage_webhooks or not permissions.send_messages:
        await interaction.response.send_message(
            "Bot membutuhkan izin Manage Webhooks dan Send Messages di channel tujuan.",
            ephemeral=True,
        )
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        webhook = await get_or_create_builder_webhook(channel)
        await send_custom_message(webhook, mode=draft.mode, payload=parse_payload(draft.payload_json))
    except (CustomMessageValidationError, discord.HTTPException) as exc:
        await interaction.followup.send(f"Gagal mengirim: {exc}", ephemeral=True)
        return
    await interaction.followup.send(f"Draft `{draft.id}` terkirim ke {channel.mention}.", ephemeral=True)


@custom_group.command(name="delete", description="Hapus draft custom message.")
@require_permissions(administrator=True)
async def custom_delete(interaction: discord.Interaction, draft_id: int) -> None:
    deleted = await repo.delete_custom_message_draft(draft_id, interaction.guild_id)
    await interaction.response.send_message(
        "Draft berhasil dihapus." if deleted else "Draft tidak ditemukan.",
        ephemeral=True,
    )


async def setup(bot: commands.Bot) -> None:
    bot.tree.add_command(custom_group)
