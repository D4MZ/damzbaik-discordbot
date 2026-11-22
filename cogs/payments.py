"""Command konfigurasi payment dan tampilan payment server."""

from __future__ import annotations

from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from database import repositories as repo
from services.storage import get_storage_backend
from utils.components import build_plain_container
from utils.permissions import require_permissions

show_group = app_commands.Group(name="show", description="Tampilkan informasi server.")
payment_group = app_commands.Group(name="payment", description="Atur payment server.")


def _payment_error(title: str, description: str) -> discord.ui.LayoutView:
    return build_plain_container(title=f"❌ {title}", description=description)


def _clean_payment_value(value: str) -> str:
    return value.strip().strip("`").strip()


def _format_payment_text(payment_text: str | None) -> str:
    if not payment_text or not payment_text.strip():
        return "Silakan scan QR di bawah untuk melakukan pembayaran."

    entries = []
    for raw_line in payment_text.replace("```", "").splitlines():
        line = _clean_payment_value(raw_line)
        if not line:
            continue

        parts = [_clean_payment_value(part) for part in line.split("|")]
        parts = [part for part in parts if part]
        if len(parts) < 2:
            entries.append(line)
            continue

        label = parts[0]
        value = parts[1]
        if ":" in label:
            label, inline_value = (_clean_payment_value(part) for part in label.split(":", 1))
            if inline_value:
                value = inline_value
                parts = [label, value, *parts[1:]]

        entry = f"**{label}**\n`{value}`"
        if len(parts) > 2:
            recipient = " • ".join(parts[2:])
            entry += f"\n-# Atas nama: {recipient}"
        entries.append(entry)

    return "\n\n".join(entries) or "Silakan scan QR di bawah untuk melakukan pembayaran."


def _payment_description(payment_text: str | None, owner_text: str | None = None) -> str:
    sections = [f"**Informasi Pembayaran**\n{_format_payment_text(payment_text)}"]
    if owner_text:
        sections.append(f"**Pemilik Payment**\n{owner_text}")
    sections.append("-# ⚠️ Pastikan nomor dan nama penerima sudah sesuai sebelum membayar.")
    return "\n\n---\n\n".join(sections)


def _method_display(name: str, payment_text: str | None) -> tuple[str, str | None]:
    normalized_name = name.strip()
    has_inline_details = "|" in normalized_name or (
        ":" in normalized_name and bool(normalized_name.split(":", 1)[1].strip())
    )
    if not has_inline_details:
        return f"💳 Payment — {normalized_name}", payment_text

    combined_text = normalized_name
    if payment_text and payment_text.strip():
        combined_text += f"\n{payment_text.strip()}"
    return "💳 Detail Payment", combined_text


def _method_option_label(name: str) -> str:
    label = name.split("|", 1)[0].split(":", 1)[0].strip()
    return (label or name.strip() or "Payment")[:100]


async def _validate_method_input(
    interaction: discord.Interaction,
    name: str,
    text: str | None,
    qr_image: discord.Attachment | None,
) -> bool:
    if not name.strip():
        await interaction.response.send_message(
            view=_payment_error("Nama Tidak Valid", "Nama payment tidak boleh kosong."),
            ephemeral=True,
        )
        return False
    if len(name) > 100:
        await interaction.response.send_message(
            view=_payment_error("Nama Terlalu Panjang", "Nama payment maksimal 100 karakter."),
            ephemeral=True,
        )
        return False
    if text is None and qr_image is None:
        await interaction.response.send_message(
            view=_payment_error("Data Payment Kosong", "Isi `text`, upload `qr_image`, atau keduanya."),
            ephemeral=True,
        )
        return False
    if text is not None and len(text) > 4000:
        await interaction.response.send_message(
            view=_payment_error("Teks Terlalu Panjang", "Teks payment maksimal 4000 karakter."),
            ephemeral=True,
        )
        return False
    if qr_image is not None and (
        not qr_image.content_type or not qr_image.content_type.startswith("image/")
    ):
        await interaction.response.send_message(
            view=_payment_error("File Tidak Valid", "`qr_image` harus berupa file gambar."),
            ephemeral=True,
        )
        return False
    return True


async def _save_qr_image(qr_image: discord.Attachment) -> tuple[str, str]:
    data = await qr_image.read()
    location = await get_storage_backend("local").save(
        filename=qr_image.filename,
        data=data,
    )
    return location, Path(qr_image.filename).name or "payment-qr.png"


@payment_group.command(name="set", description="Simpan payment milikmu; bisa lebih dari satu.")
@app_commands.guild_only()
@app_commands.describe(
    name="Nama opsi (default: Payment), misalnya DANA, GoPay, QRIS, atau BCA",
    text="Detail rekening/e-wallet/payment (opsional)",
    qr_image="Gambar QR payment (opsional)",
)
async def payment_set(
    interaction: discord.Interaction,
    name: str = "Payment",
    text: str | None = None,
    qr_image: discord.Attachment | None = None,
) -> None:
    if not await _validate_method_input(interaction, name, text, qr_image):
        return
    normalized_name = name.strip()
    existing = await repo.get_payment_method(
        interaction.guild_id,
        interaction.user.id,
        normalized_name,
    )
    await interaction.response.defer(ephemeral=True, thinking=True)
    fields: dict[str, str | None] = {}
    if text is not None:
        fields["payment_text"] = text
    if qr_image is not None:
        try:
            fields["qr_image_location"], fields["qr_image_filename"] = await _save_qr_image(qr_image)
        except Exception as exc:
            await interaction.followup.send(view=_payment_error("Upload QR Gagal", str(exc)), ephemeral=True)
            return
    if existing is None:
        await repo.add_payment_method(
            interaction.guild_id,
            interaction.user.id,
            name=normalized_name,
            **fields,
        )
        action = "ditambahkan"
        title = "Opsi Payment Ditambahkan"
    else:
        await repo.update_payment_method(
            interaction.guild_id,
            interaction.user.id,
            normalized_name,
            **fields,
        )
        if fields.get("qr_image_location") and existing.qr_image_location:
            Path(existing.qr_image_location).unlink(missing_ok=True)
        action = "diperbarui"
        title = "Opsi Payment Diperbarui"
    await interaction.followup.send(
        view=build_plain_container(
            title=f"✅ {title}",
            description=(
                f"Payment `{normalized_name}` milik {interaction.user.mention} "
                f"berhasil {action}."
            ),
        ),
        ephemeral=True,
    )


@payment_group.command(name="list", description="Lihat semua payment milikmu.")
@app_commands.guild_only()
async def payment_list(interaction: discord.Interaction) -> None:
    methods = await repo.list_payment_methods(interaction.guild_id, interaction.user.id)
    if not methods:
        await interaction.response.send_message(
            view=_payment_error("Belum Ada Opsi", "Tambahkan opsi dengan `/payment set`."), ephemeral=True
        )
        return
    lines = []
    for method in methods:
        contents = []
        if method.payment_text:
            contents.append("Teks ✅")
        if method.qr_image_location:
            contents.append("QR ✅")
        lines.append(f"**{method.name}** — {' | '.join(contents)}")
    await interaction.response.send_message(
        view=build_plain_container(
            title="💳 Payment Milikmu",
            description="\n".join(lines),
        ),
        ephemeral=True,
    )


@payment_group.command(name="edit", description="Edit payment milikmu berdasarkan nama.")
@app_commands.guild_only()
@app_commands.describe(
    name="Nama opsi payment yang akan diedit",
    text="Teks payment baru (kosongkan untuk mempertahankan teks lama)",
    qr_image="Gambar QR baru (kosongkan untuk mempertahankan QR lama)",
)
async def payment_edit(
    interaction: discord.Interaction,
    name: str,
    text: str | None = None,
    qr_image: discord.Attachment | None = None,
) -> None:
    if text is None and qr_image is None:
        await interaction.response.send_message(
            view=_payment_error("Tidak Ada Perubahan", "Isi `text` atau upload `qr_image` yang baru."),
            ephemeral=True,
        )
        return
    if text is not None and len(text) > 4000:
        await interaction.response.send_message(
            view=_payment_error("Teks Terlalu Panjang", "Teks payment maksimal 4000 karakter."),
            ephemeral=True,
        )
        return
    if qr_image is not None and (
        not qr_image.content_type or not qr_image.content_type.startswith("image/")
    ):
        await interaction.response.send_message(
            view=_payment_error("File Tidak Valid", "`qr_image` harus berupa file gambar."),
            ephemeral=True,
        )
        return

    existing = await repo.get_payment_method(
        interaction.guild_id,
        interaction.user.id,
        name.strip(),
    )
    if existing is None:
        await interaction.response.send_message(
            view=_payment_error("Opsi Tidak Ditemukan", f"Payment `{name.strip()}` belum terdaftar."),
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    fields: dict[str, str | None] = {}
    if text is not None:
        fields["payment_text"] = text
    new_qr_location = None
    if qr_image is not None:
        try:
            new_qr_location, fields["qr_image_filename"] = await _save_qr_image(qr_image)
        except Exception as exc:
            await interaction.followup.send(view=_payment_error("Upload QR Gagal", str(exc)), ephemeral=True)
            return
        fields["qr_image_location"] = new_qr_location
    await repo.update_payment_method(
        interaction.guild_id,
        interaction.user.id,
        name.strip(),
        **fields,
    )
    if new_qr_location and existing.qr_image_location:
        Path(existing.qr_image_location).unlink(missing_ok=True)
    updated_items = []
    if text is not None:
        updated_items.append("teks")
    if qr_image is not None:
        updated_items.append("QR image")
    await interaction.followup.send(
        view=build_plain_container(
            title="✅ Opsi Payment Diperbarui",
            description=f"`{name.strip()}`: " + ", ".join(updated_items),
        ),
        ephemeral=True,
    )


@payment_group.command(name="delete", description="Hapus payment milikmu berdasarkan nama.")
@app_commands.guild_only()
@app_commands.describe(name="Nama opsi payment yang akan dihapus")
async def payment_delete(interaction: discord.Interaction, name: str) -> None:
    method = await repo.delete_payment_method(
        interaction.guild_id,
        interaction.user.id,
        name.strip(),
    )
    if method is None:
        await interaction.response.send_message(
            view=_payment_error("Opsi Tidak Ditemukan", f"Payment `{name.strip()}` belum terdaftar."),
            ephemeral=True,
        )
        return
    if method.qr_image_location:
        Path(method.qr_image_location).unlink(missing_ok=True)
    await interaction.response.send_message(
        view=build_plain_container(
            title="✅ Opsi Payment Dihapus",
            description=f"Payment `{method.name}` telah dihapus.",
        ),
        ephemeral=True,
    )


@payment_group.command(name="clear", description="Hapus seluruh konfigurasi payment server.")
@app_commands.guild_only()
@require_permissions(administrator=True)
async def payment_clear(interaction: discord.Interaction) -> None:
    config = await repo.get_payment_config(interaction.guild_id)
    methods = await repo.list_payment_methods(interaction.guild_id)
    if (config is None or (not config.payment_text and not config.qr_image_location)) and not methods:
        await interaction.response.send_message(
            view=_payment_error("Belum Ada Payment", "Konfigurasi payment server masih kosong."),
            ephemeral=True,
        )
        return

    if config is not None:
        await repo.update_payment_config(
            interaction.guild_id,
            payment_text=None,
            qr_image_location=None,
            qr_image_filename=None,
        )
        if config.qr_image_location:
            Path(config.qr_image_location).unlink(missing_ok=True)
    for method in methods:
        await repo.delete_payment_method(
            interaction.guild_id,
            method.owner_id,
            method.name,
        )
        if method.qr_image_location:
            Path(method.qr_image_location).unlink(missing_ok=True)
    await interaction.response.send_message(
        view=build_plain_container(
            title="✅ Payment Dihapus",
            description="Semua opsi payment server telah dikosongkan.",
        ),
        ephemeral=True,
    )


@show_group.command(name="payment", description="Tampilkan metode pembayaran server.")
@app_commands.guild_only()
async def show_payment(interaction: discord.Interaction) -> None:
    methods = await repo.list_payment_methods(interaction.guild_id)
    if methods:
        if len(methods) == 1:
            await _send_payment_method(interaction, methods[0])
        else:
            await interaction.response.send_message(
                view=PaymentPickerView(methods, interaction.guild),
                ephemeral=True,
            )
        return

    config = await repo.get_payment_config(interaction.guild_id)
    if config is None or (not config.payment_text and not config.qr_image_location):
        await interaction.response.send_message(
            view=_payment_error("Payment Belum Diatur", "Admin server belum mengatur metode pembayaran."),
            ephemeral=True,
        )
        return

    description = _payment_description(config.payment_text)

    if config.qr_image_location:
        filename = config.qr_image_filename or "payment-qr.png"
        try:
            file = discord.File(config.qr_image_location, filename=filename)
            await interaction.response.send_message(
                view=build_plain_container(
                    title=f"💳 Payment — {interaction.guild.name}",
                    description=description,
                    media=file,
                    media_description="QR payment",
                ),
                file=file,
            )
        except FileNotFoundError:
            await interaction.response.send_message(
                view=_payment_error("QR Tidak Ditemukan", "File QR payment tidak tersedia di storage bot."),
                ephemeral=True,
            )
        return

    await interaction.response.send_message(
        view=build_plain_container(
            title=f"💳 Payment — {interaction.guild.name}",
            description=description,
        )
    )


async def _send_payment_method(interaction: discord.Interaction, method) -> None:
    owner = interaction.guild.get_member(method.owner_id) if method.owner_id else None
    owner_text = owner.mention if owner else ("Payment server" if method.owner_id == 0 else f"<@{method.owner_id}>")
    title, payment_text = _method_display(method.name, method.payment_text)
    description = _payment_description(payment_text, owner_text)
    if method.qr_image_location:
        filename = method.qr_image_filename or "payment-qr.png"
        try:
            file = discord.File(method.qr_image_location, filename=filename)
            await interaction.response.send_message(
                view=build_plain_container(
                    title=title,
                    description=description,
                    media=file,
                    media_description=f"QR {method.name}",
                ),
                file=file,
            )
        except FileNotFoundError:
            await interaction.response.send_message(
                view=_payment_error("QR Tidak Ditemukan", "File QR payment tidak tersedia di storage bot."),
                ephemeral=True,
            )
        return
    await interaction.response.send_message(
        view=build_plain_container(
            title=title,
            description=description,
        )
    )


class PaymentMethodSelect(discord.ui.Select):
    def __init__(self, methods, guild: discord.Guild) -> None:
        self.methods = {str(method.id): method for method in methods[:25]}
        options = [
            discord.SelectOption(
                label=_method_option_label(method.name),
                value=str(method.id),
                description=(
                    f"Milik {guild.get_member(method.owner_id).display_name}"[:100]
                    if method.owner_id and guild.get_member(method.owner_id)
                    else ("Payment server" if method.owner_id == 0 else f"Pemilik ID {method.owner_id}")
                ),
            )
            for method in methods[:25]
        ]
        super().__init__(placeholder="Pilih metode pembayaran...", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        method = self.methods[self.values[0]]
        await _send_payment_method(interaction, method)


class PaymentPageButton(discord.ui.Button):
    def __init__(self, *, page: int, label: str, emoji: str, disabled: bool = False) -> None:
        super().__init__(
            label=label,
            emoji=emoji,
            style=discord.ButtonStyle.secondary,
            disabled=disabled,
        )
        self.page = page

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, PaymentPickerView):
            return
        await interaction.response.edit_message(
            view=PaymentPickerView(view.methods, view.guild, page=self.page)
        )


class PaymentPickerView(discord.ui.LayoutView):
    PAGE_SIZE = 25

    def __init__(self, methods, guild: discord.Guild, *, page: int = 0) -> None:
        super().__init__(timeout=180)
        self.methods = list(methods)
        self.guild = guild
        page_count = max(1, (len(self.methods) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self.page = max(0, min(page, page_count - 1))
        start = self.page * self.PAGE_SIZE
        page_methods = self.methods[start : start + self.PAGE_SIZE]
        children: list[discord.ui.Item] = [
            discord.ui.TextDisplay(
                "**💳 Pilih Payment**\n\n"
                "Pilih metode pembayaran yang ingin ditampilkan. "
                "Nama pemilik tercantum pada setiap pilihan."
            ),
            discord.ui.ActionRow(PaymentMethodSelect(page_methods, guild)),
        ]
        if page_count > 1:
            children.append(
                discord.ui.ActionRow(
                    PaymentPageButton(
                        page=self.page - 1,
                        label="Sebelumnya",
                        emoji="◀️",
                        disabled=self.page == 0,
                    ),
                    discord.ui.Button(
                        label=f"{self.page + 1}/{page_count}",
                        style=discord.ButtonStyle.secondary,
                        disabled=True,
                    ),
                    PaymentPageButton(
                        page=self.page + 1,
                        label="Berikutnya",
                        emoji="▶️",
                        disabled=self.page >= page_count - 1,
                    ),
                )
            )
        self.add_item(discord.ui.Container(*children))


async def setup(bot: commands.Bot) -> None:
    bot.tree.add_command(payment_group)
    bot.tree.add_command(show_group)
