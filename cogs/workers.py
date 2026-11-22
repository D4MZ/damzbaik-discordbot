"""Panel status worker berbasis Discord Components V2."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from re import findall

from database import repositories as repo
from utils.embeds import error_embed, success_embed
from utils.permissions import require_permissions

MAX_WORKERS = 10
WORKER_BUTTON_PREFIX = "worker-status:toggle:"


def _parse_member_ids(value: str) -> list[int]:
    """Membaca mention/member ID dari input list worker."""
    member_ids: list[int] = []
    for token in findall(r"<@!?([0-9]+)>|(?<![0-9])([0-9]{15,22})(?![0-9])", value):
        raw_id = token[0] or token[1]
        member_id = int(raw_id)
        if member_id not in member_ids:
            member_ids.append(member_id)
    return member_ids


def build_worker_status_view(cog: "WorkersCog", panel, workers: list) -> discord.ui.LayoutView:
    children: list[discord.ui.Item] = [
        discord.ui.TextDisplay(
            f"## {panel.title}\n{panel.description}\n\n"
            "🟢 **Available** — worker siap menerima pekerjaan.\n"
            "🔴 **Not available** — worker sedang tidak tersedia.\n"
            "Setiap worker hanya dapat mengubah statusnya sendiri."
        ),
        discord.ui.Separator(),
    ]
    if not workers:
        children.append(discord.ui.TextDisplay("Belum ada worker yang terdaftar."))
    else:
        for start in range(0, len(workers), 5):
            buttons = [
                WorkerStatusButton(cog, worker)
                for worker in workers[start : start + 5]
            ]
            children.append(discord.ui.ActionRow(*buttons))

    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(*children))
    return view


class WorkerStatusButton(discord.ui.Button):
    def __init__(self, cog: "WorkersCog", worker) -> None:
        self.cog = cog
        self.member_id = worker.member_id
        available = bool(worker.available)
        super().__init__(
            label=worker.label[:75],
            emoji="🟢" if available else "🔴",
            style=discord.ButtonStyle.success if available else discord.ButtonStyle.secondary,
            custom_id=f"{WORKER_BUTTON_PREFIX}{worker.member_id}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.user.id != self.member_id:
            await interaction.response.send_message(
                "Hanya worker terkait yang dapat mengubah status ini.", ephemeral=True
            )
            return
        worker = await repo.get_worker_status(interaction.guild_id, self.member_id)
        if worker is None:
            await interaction.response.send_message(
                "Worker ini sudah tidak terdaftar.", ephemeral=True
            )
            return
        updated = await repo.update_worker_status(
            interaction.guild_id,
            self.member_id,
            available=not worker.available,
        )
        await interaction.response.defer(ephemeral=True)
        await self.cog.refresh_panel(interaction.guild_id)
        await interaction.followup.send(
            f"Status kamu sekarang: {'🟢 Available' if updated and updated.available else '🔴 Not available'}.",
            ephemeral=True,
        )


class WorkersCog(commands.Cog, name="Workers"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        panels = await self._list_panels()
        for panel in panels:
            if panel.message_id is None:
                continue
            workers = await repo.list_worker_statuses(panel.guild_id)
            self.bot.add_view(
                build_worker_status_view(self, panel, workers),
                message_id=panel.message_id,
            )

    async def _list_panels(self) -> list:
        from sqlalchemy import select

        from database.engine import get_session
        from database.models import WorkerStatusPanel

        async with get_session() as session:
            result = await session.execute(select(WorkerStatusPanel))
            return list(result.scalars().all())

    async def refresh_panel(self, guild_id: int) -> bool:
        panel = await repo.get_worker_status_panel(guild_id)
        if panel is None or panel.message_id is None:
            return False
        guild = self.bot.get_guild(guild_id)
        channel = guild.get_channel(panel.channel_id) if guild else None
        if not isinstance(channel, discord.TextChannel):
            return False
        try:
            message = await channel.fetch_message(panel.message_id)
            workers = await repo.list_worker_statuses(guild_id)
            await message.edit(
                content=None,
                embed=None,
                attachments=[],
                view=build_worker_status_view(self, panel, workers),
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return False
        return True

    @app_commands.command(
        name="worker-status",
        description="Buat dan kelola panel status worker.",
    )
    @app_commands.describe(
        channel="Channel untuk panel status worker",
        member="Member worker yang ditambahkan atau dihapus",
        label="Nama worker yang tampil pada tombol",
        members="Daftar mention worker, pisahkan dengan spasi atau koma (maksimal 10)",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="Input list worker", value="input-list"),
        app_commands.Choice(name="Publish ke channel", value="publish"),
        app_commands.Choice(name="Tambah worker", value="add"),
        app_commands.Choice(name="Hapus worker", value="remove"),
        app_commands.Choice(name="Lihat daftar worker", value="list"),
    ])
    @require_permissions(administrator=True)
    async def worker_status(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        channel: discord.TextChannel | None = None,
        member: discord.Member | None = None,
        label: str | None = None,
        members: str | None = None,
    ) -> None:
        guild_id = interaction.guild_id
        if action.value == "input-list":
            if not members:
                await interaction.response.send_message(
                    embed=error_embed(
                        "List Worker Dibutuhkan",
                        "Masukkan mention worker, contoh: `@Worker1 @Worker2 @Worker3`.",
                    ),
                    ephemeral=True,
                )
                return
            member_ids = _parse_member_ids(members)
            if not member_ids or len(member_ids) > MAX_WORKERS:
                await interaction.response.send_message(
                    embed=error_embed(
                        "Format List Worker Salah",
                        "Masukkan 1 sampai 10 mention worker yang valid.",
                    ),
                    ephemeral=True,
                )
                return
            selected_members = [interaction.guild.get_member(member_id) for member_id in member_ids]
            missing = [str(member_id) for member_id, selected in zip(member_ids, selected_members) if selected is None]
            if missing:
                await interaction.response.send_message(
                    embed=error_embed(
                        "Worker Tidak Ditemukan",
                        f"Member berikut bukan anggota server ini: {', '.join(missing)}",
                    ),
                    ephemeral=True,
                )
                return
            current_workers = await repo.list_worker_statuses(guild_id)
            for worker in current_workers:
                if worker.member_id not in member_ids:
                    await repo.delete_worker_status(guild_id, worker.member_id)
            for selected in selected_members:
                if await repo.get_worker_status(guild_id, selected.id) is None:
                    await repo.add_worker_status(guild_id, selected.id, selected.display_name[:100])
            await interaction.response.send_message(
                embed=success_embed(
                    "List Worker Tersimpan",
                    f"{len(member_ids)} worker tersimpan. Setelah selesai, gunakan `Publish ke channel` untuk mengirim panel.",
                ),
                ephemeral=True,
            )
            return

        if action.value == "publish":
            target = channel or interaction.channel
            workers = await repo.list_worker_statuses(guild_id)
            if not workers:
                await interaction.response.send_message(
                    embed=error_embed(
                        "List Worker Kosong",
                        "Input list worker terlebih dahulu, lalu pilih aksi `Publish ke channel`.",
                    ),
                    ephemeral=True,
                )
                return
            if not isinstance(target, discord.TextChannel):
                await interaction.response.send_message(
                    embed=error_embed("Channel Tidak Valid", "Pilih text channel untuk publish panel."),
                    ephemeral=True,
                )
                return
            existing = await repo.get_worker_status_panel(guild_id)
            if (
                existing
                and existing.message_id is not None
                and existing.channel_id == target.id
                and await self.refresh_panel(guild_id)
            ):
                await interaction.response.send_message(
                    embed=success_embed("Panel Diperbarui", f"List worker diperbarui di {target.mention}."),
                    ephemeral=True,
                )
                return
            await interaction.response.defer(ephemeral=True)
            panel = existing or await repo.upsert_worker_status_panel(
                guild_id,
                channel_id=target.id,
                message_id=None,
            )
            message = await target.send(view=build_worker_status_view(self, panel, workers))
            await repo.upsert_worker_status_panel(
                guild_id,
                channel_id=target.id,
                message_id=message.id,
            )
            await interaction.followup.send(
                embed=success_embed("Panel Dipublish", f"List worker dikirim ke {target.mention}."),
                ephemeral=True,
            )
            return

        if action.value == "add":
            if member is None:
                await interaction.response.send_message(
                    embed=error_embed("Member Dibutuhkan", "Pilih member worker."),
                    ephemeral=True,
                )
                return
            workers = await repo.list_worker_statuses(guild_id)
            if len(workers) >= MAX_WORKERS:
                await interaction.response.send_message(
                    embed=error_embed("Batas Worker", "Satu panel dapat memiliki maksimal 10 worker."),
                    ephemeral=True,
                )
                return
            if await repo.get_worker_status(guild_id, member.id):
                await interaction.response.send_message(
                    embed=error_embed("Sudah Terdaftar", "Member tersebut sudah menjadi worker."),
                    ephemeral=True,
                )
                return
            await repo.add_worker_status(
                guild_id,
                member.id,
                (label or member.display_name).strip()[:100],
            )
            await self.refresh_panel(guild_id)
            await interaction.response.send_message(
                embed=success_embed("Worker Ditambahkan", f"{member.mention} berhasil ditambahkan."),
                ephemeral=True,
            )
            return

        if action.value == "remove":
            if member is None or not await repo.delete_worker_status(guild_id, member.id):
                await interaction.response.send_message(
                    embed=error_embed("Tidak Ditemukan", "Worker tidak ditemukan."),
                    ephemeral=True,
                )
                return
            await self.refresh_panel(guild_id)
            await interaction.response.send_message(
                embed=success_embed("Worker Dihapus", f"{member.mention} dihapus dari panel."),
                ephemeral=True,
            )
            return

        if action.value == "list":
            workers = await repo.list_worker_statuses(guild_id)
            lines = [
                f"{'🟢' if worker.available else '🔴'} <@{worker.member_id}> — {worker.label}"
                for worker in workers
            ] or ["Belum ada worker."]
            await interaction.response.send_message("\n".join(lines), ephemeral=True)
            return

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WorkersCog(bot))
