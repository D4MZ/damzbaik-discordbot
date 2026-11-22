"""Cog: Image Management System."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from database import repositories as repo
from services.storage import get_storage_backend
from utils.components import build_plain_container
from utils.embeds import error_embed, success_embed
from utils.permissions import require_permissions

image_group = app_commands.Group(name="image", description="Kelola image asset server.")


@image_group.command(name="upload", description="Upload image dan simpan dengan nama & kategori.")
@app_commands.describe(
    file="File gambar yang diupload",
    name="Nama unik untuk gambar ini",
    category="Kategori gambar (default: general)",
    storage_type="Tipe penyimpanan",
)
@app_commands.choices(
    storage_type=[
        app_commands.Choice(name="Local (disk VPS)", value="local"),
        app_commands.Choice(name="S3-compatible", value="s3"),
    ]
)
@require_permissions(manage_guild=True)
async def image_upload(
    interaction: discord.Interaction,
    file: discord.Attachment,
    name: str,
    category: str = "general",
    storage_type: app_commands.Choice[str] | None = None,
) -> None:
    if not file.content_type or not file.content_type.startswith("image/"):
        await interaction.response.send_message(embed=error_embed("Gagal", "File yang diupload harus berupa gambar."), ephemeral=True)
        return

    existing = await repo.get_image_asset(interaction.guild_id, name)
    if existing is not None:
        await interaction.response.send_message(
            embed=error_embed("Nama Sudah Dipakai", f"Image dengan nama `{name}` sudah ada. Hapus dulu atau gunakan nama lain."),
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    chosen_type = storage_type.value if storage_type else "local"
    try:
        backend = get_storage_backend(chosen_type)
        data = await file.read()
        location = await backend.save(filename=file.filename, data=data)
    except Exception as exc:
        await interaction.followup.send(embed=error_embed("Gagal Upload", str(exc)), ephemeral=True)
        return

    await repo.add_image_asset(
        guild_id=interaction.guild_id,
        name=name,
        category=category,
        storage_type=chosen_type,
        location=location,
        uploaded_by=interaction.user.id,
    )
    await interaction.followup.send(
        embed=success_embed("Image Diupload", f"Nama: `{name}` | Kategori: `{category}` | Storage: `{chosen_type}`"),
        ephemeral=True,
    )


@image_group.command(name="show", description="Tampilkan sebuah image berdasarkan nama.")
@app_commands.describe(name="Nama image")
async def image_show(interaction: discord.Interaction, name: str) -> None:
    asset = await repo.get_image_asset(interaction.guild_id, name)
    if asset is None:
        await interaction.response.send_message(
            view=build_plain_container(
                title="❌ Image Tidak Ditemukan",
                description=f"Image `{name}` tidak ditemukan.",
            ),
            ephemeral=True,
        )
        return

    if asset.storage_type == "local":
        try:
            filename = name if "." in name else f"{name}.png"
            file = discord.File(asset.location, filename=filename)
            await interaction.response.send_message(
                view=build_plain_container(
                    title=f"🖼️ {name}",
                    media=file,
                    media_description=name,
                ),
                file=file,
            )
        except FileNotFoundError:
            await interaction.response.send_message(
                view=build_plain_container(
                    title="❌ Gagal Menampilkan Image",
                    description="File gambar tidak ditemukan di disk.",
                ),
                ephemeral=True,
            )
        return

    backend = get_storage_backend(asset.storage_type)
    url = backend.resolve_url(asset.location)
    await interaction.response.send_message(
        view=build_plain_container(
            title=f"🖼️ {name}",
            media=url,
            media_description=name,
        )
    )


@image_group.command(name="list", description="Lihat daftar image, opsional filter kategori.")
@app_commands.describe(category="Filter berdasarkan kategori (opsional)")
async def image_list(interaction: discord.Interaction, category: str | None = None) -> None:
    assets = await repo.list_image_assets(interaction.guild_id, category)
    if not assets:
        await interaction.response.send_message("Tidak ada image ditemukan.", ephemeral=True)
        return
    embed = discord.Embed(title="🖼️ Daftar Image", color=discord.Color.blurple())
    for asset in assets:
        uploader = interaction.guild.get_member(asset.uploaded_by)
        embed.add_field(
            name=asset.name,
            value=f"Kategori: `{asset.category}` | Storage: `{asset.storage_type}` | Oleh: {uploader.mention if uploader else asset.uploaded_by}",
            inline=False,
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@image_group.command(name="delete", description="Hapus image yang pernah di-upload.")
@app_commands.describe(name="Nama image yang akan dihapus")
@require_permissions(manage_guild=True)
async def image_delete(interaction: discord.Interaction, name: str) -> None:
    asset = await repo.get_image_asset(interaction.guild_id, name)
    if asset is None:
        await interaction.response.send_message(embed=error_embed("Tidak Ditemukan", f"Image `{name}` tidak ditemukan."), ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        backend = get_storage_backend(asset.storage_type)
        await backend.delete(asset.location)
    except Exception as exc:
        await interaction.followup.send(
            embed=error_embed(
                "Gagal Menghapus Image",
                f"File `{name}` gagal dihapus dari storage: {exc}",
            ),
            ephemeral=True,
        )
        return

    deleted = await repo.delete_image_asset(interaction.guild_id, name)
    if deleted is None:
        await interaction.followup.send(
            embed=error_embed("Gagal", "Data image sudah berubah. Silakan periksa `/image list`."),
            ephemeral=True,
        )
        return

    await interaction.followup.send(
        embed=success_embed(
            "Image Dihapus",
            f"Image `{name}` beserta file storage-nya telah dihapus.",
        ),
        ephemeral=True,
    )


async def setup(bot: commands.Bot) -> None:
    bot.tree.add_command(image_group)
