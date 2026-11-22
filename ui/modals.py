"""Modal (pop-up form) yang dipakai berbagai cog untuk input teks panjang."""

from __future__ import annotations

import discord

from utils.embeds import build_custom_embed


class AnnouncementModal(discord.ui.Modal, title="Buat Announcement"):
    ann_title = discord.ui.TextInput(label="Judul", required=False, max_length=256)
    ann_description = discord.ui.TextInput(
        label="Isi Pesan", style=discord.TextStyle.paragraph, required=True, max_length=4000
    )
    ann_color = discord.ui.TextInput(
        label="Warna (hex, contoh #5865F2)", required=False, max_length=7, default="#5865F2"
    )
    ann_image = discord.ui.TextInput(label="URL Gambar (opsional)", required=False)
    ann_footer = discord.ui.TextInput(label="Footer (opsional)", required=False, max_length=256)

    def __init__(self, on_submit_callback):
        super().__init__()
        self._callback = on_submit_callback

    async def on_submit(self, interaction: discord.Interaction) -> None:
        embed = build_custom_embed(
            title=str(self.ann_title.value) or None,
            description=str(self.ann_description.value),
            color=str(self.ann_color.value) or None,
            image=str(self.ann_image.value) or None,
            footer=str(self.ann_footer.value) or None,
            timestamp=True,
        )
        await self._callback(interaction, embed)


class SayEditModal(discord.ui.Modal, title="Edit Pesan Bot"):
    def __init__(self, current: str, max_length: int, on_submit_callback):
        super().__init__()
        self.message = discord.ui.TextInput(
            label="Isi Pesan",
            style=discord.TextStyle.paragraph,
            default=current[:max_length],
            max_length=max_length,
        )
        self.add_item(self.message)
        self._callback = on_submit_callback

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._callback(interaction, str(self.message.value))


class MemberTextModal(discord.ui.Modal):
    """Form teks untuk pesan welcome/leave."""

    message = discord.ui.TextInput(label="Pesan", style=discord.TextStyle.paragraph, max_length=2000)

    def __init__(self, label: str, placeholder: str, on_submit_callback):
        super().__init__(title=f"Set {label} Text")
        self.message.label = f"Pesan {label}"
        self.message.placeholder = placeholder
        self._callback = on_submit_callback

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._callback(interaction, str(self.message.value))


class MemberEmbedModal(discord.ui.Modal):
    """Form embed untuk pesan welcome/leave. Mengembalikan field tanpa prefix."""

    embed_title = discord.ui.TextInput(label="Judul Embed", required=False, max_length=256)
    embed_description = discord.ui.TextInput(
        label="Deskripsi", style=discord.TextStyle.paragraph, required=False, max_length=4000,
    )
    embed_color = discord.ui.TextInput(label="Warna (hex)", required=False, default="#5865F2")
    embed_footer = discord.ui.TextInput(label="Footer", required=False, max_length=256)
    embed_thumbnail = discord.ui.TextInput(label="URL Thumbnail", required=False)

    def __init__(self, label: str, placeholder: str, on_submit_callback):
        super().__init__(title=f"Set {label} Embed")
        self.embed_description.placeholder = placeholder
        self._callback = on_submit_callback

    async def on_submit(self, interaction: discord.Interaction) -> None:
        data = {
            "embed_title": str(self.embed_title.value) or None,
            "embed_description": str(self.embed_description.value) or None,
            "embed_color": str(self.embed_color.value) or "#5865F2",
            "embed_footer": str(self.embed_footer.value) or None,
            "embed_thumbnail": str(self.embed_thumbnail.value) or None,
        }
        await self._callback(interaction, data)


class BoostMessageModal(discord.ui.Modal, title="Set Boost Message"):
    title_input = discord.ui.TextInput(label="Judul", required=False, max_length=256)
    message = discord.ui.TextInput(
        label="Isi pesan", style=discord.TextStyle.paragraph, required=True, max_length=4000,
        placeholder="Terima kasih {user} sudah boost {server}!",
    )
    image = discord.ui.TextInput(label="URL gambar/avatar (opsional)", required=False, max_length=1000)
    footer = discord.ui.TextInput(label="Footer (opsional)", required=False, max_length=256)

    def __init__(self, config, on_submit_callback):
        super().__init__()
        self._callback = on_submit_callback
        self.title_input.default = config.boost_title or "Server Boost"
        self.message.default = config.boost_message
        self.image.default = config.boost_image or ""
        self.footer.default = getattr(config, "boost_footer", None) or ""

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self._callback(interaction, {
            "boost_title": str(self.title_input.value) or None,
            "boost_message": str(self.message.value),
            "boost_image": str(self.image.value) or None,
            "boost_footer": str(self.footer.value) or None,
        })
