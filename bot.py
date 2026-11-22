"""
Entry point utama Discord Bot Management & Community System.

Menjalankan:
- Inisialisasi database (auto create table jika belum ada)
- Load seluruh cogs (arsitektur modular)
- Registrasi ulang persistent views (role dropdown)
- Sync slash command (guild command saat development, global saat production)
- Global error handler untuk application commands
"""

from __future__ import annotations

import asyncio
import signal

import discord
from aiohttp.client_exceptions import ClientConnectionError
from discord.ext import commands

from config import settings
from database import repositories as repo
from database.engine import init_db
from ui.role_views import register_all_role_dropdowns
from utils.error_handler import handle_app_command_error
from utils.logger import get_logger, setup_logging

setup_logging(settings.log_level)
logger = get_logger(__name__)

INTENTS = discord.Intents.default()
INTENTS.members = True  # dibutuhkan: welcome, autorole, member log, invite tracker
INTENTS.message_content = True  # dibutuhkan: message log (isi pesan yang diedit/dihapus)
INTENTS.guilds = True
INTENTS.voice_states = True  # dibutuhkan: voice log
INTENTS.reactions = True  # dibutuhkan: reaction role

EXTENSIONS = [
    "cogs.general",
    "cogs.settings",
    "cogs.welcome",
    "cogs.boost",
    "cogs.invites",
    "cogs.roles",
    "cogs.announcements",
    "cogs.logging_cog",
    "cogs.images",
    "cogs.payments",
    "cogs.custom_messages",
    "cogs.anti_nuke",
    "cogs.workers",
    "cogs.reviews",
    "cogs.prefix_commands",
]


class ManagementBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=INTENTS, help_command=None)
        self._activity_task: asyncio.Task[None] | None = None
        self._command_sync_lock = asyncio.Lock()
        self._commands_synced = False
        self._all_guilds_synced = False
        self.custom_web_server = None

    async def setup_hook(self) -> None:
        settings.validate()

        logger.info("Menginisialisasi database...")
        await init_db()

        for extension in EXTENSIONS:
            try:
                await self.load_extension(extension)
                logger.info("Cog dimuat: %s", extension)
            except Exception:
                logger.exception("Gagal memuat cog: %s", extension)

        logger.info(
            "Command tree sebelum sync: %s",
            ", ".join(command.name for command in self.tree.get_commands()) or "(kosong)",
        )

        self.tree.on_error = handle_app_command_error

        # Registrasi ulang persistent views agar tombol/dropdown lama tetap
        # berfungsi setelah bot restart.
        await register_all_role_dropdowns(self)

        if settings.custom_web_enabled or settings.dashboard_enabled:
            try:
                from services.custom_web import CustomMessageWebServer

                self.custom_web_server = CustomMessageWebServer(
                    self,
                    host=settings.custom_web_host,
                    port=settings.custom_web_port,
                )
                await self.custom_web_server.start()
            except Exception:
                self.custom_web_server = None
                logger.exception("Web dashboard/editor gagal dijalankan; slash fallback tetap aktif.")

        await self._sync_commands()

    async def _sync_commands(self, *, force: bool = False) -> None:
        if self._commands_synced and not force:
            return
        async with self._command_sync_lock:
            if self._commands_synced and not force:
                return
            # Sync the current command tree globally, so newly loaded cogs and
            # removed commands are reflected after every restart.
            global_synced = await self.tree.sync()
            logger.info(
                "Slash command di-sync secara GLOBAL (%d command).",
                len(global_synced),
            )
            guilds = list(self.guilds)
            if settings.dev_guild_id and all(
                guild.id != settings.dev_guild_id for guild in guilds
            ):
                guilds.append(discord.Object(id=settings.dev_guild_id))
            for guild in guilds:
                try:
                    await self._clear_guild_commands(guild.id)
                except discord.HTTPException:
                    logger.exception("Gagal membersihkan slash command guild %s.", guild.id)
            self._commands_synced = True
            logger.info(
                "Sinkronisasi selesai. Command global aktif: %s",
                ", ".join(command.name for command in global_synced) or "(kosong)",
            )

    async def _clear_guild_commands(self, guild_id: int) -> None:
        # Commands live globally only; a guild copy would show every command twice.
        guild_obj = discord.Object(id=guild_id)
        self.tree.clear_commands(guild=guild_obj)
        await self.tree.sync(guild=guild_obj)
        logger.info("Salinan slash command guild %s dibersihkan.", guild_id)

    async def resync_commands(self, guild_id: int | None = None) -> None:
        """Paksa refresh command saat Discord masih mengirim signature lama."""
        if guild_id is not None:
            async with self._command_sync_lock:
                await self._clear_guild_commands(guild_id)
            return

        self._commands_synced = False
        await self._sync_commands(force=True)

    async def on_ready(self) -> None:
        logger.info("Bot login sebagai %s (ID: %s)", self.user, self.user.id)
        logger.info("Terhubung ke %d server.", len(self.guilds))

        # setup_hook berjalan sebelum cache guild siap. Setelah READY, lakukan
        # satu kali sync ulang agar command langsung tersedia di semua guild.
        if not self._all_guilds_synced:
            await self._sync_commands(force=True)
            self._all_guilds_synced = True

        if self._activity_task is None or self._activity_task.done():
            self._activity_task = asyncio.create_task(self._rotate_activities())

    async def _get_default_activity(self) -> discord.Activity:
        configs = await repo.get_all_guild_configs()
        status_text = next(
            (config.status_text for config in configs if config.status_text),
            "over {servers} servers",
        )
        status_text = status_text.replace("{servers}", str(len(self.guilds)))
        return discord.Activity(type=discord.ActivityType.watching, name=status_text)

    async def _rotate_activities(self) -> None:
        activity_index = 0
        gateway_unavailable = False
        try:
            while not self.is_closed():
                await self.wait_until_ready()
                if self.is_closed():
                    break
                try:
                    if settings.custom_activities:
                        activity_text = settings.custom_activities[activity_index]
                        activity_text = activity_text.replace("{servers}", str(len(self.guilds)))
                        activity = discord.Activity(
                            type=discord.ActivityType.watching,
                            name=activity_text,
                        )
                    else:
                        activity = await self._get_default_activity()

                    await self.change_presence(activity=activity)
                    if settings.custom_activities:
                        activity_index = (activity_index + 1) % len(settings.custom_activities)
                    gateway_unavailable = False
                except asyncio.CancelledError:
                    raise
                except (ClientConnectionError, discord.ConnectionClosed, OSError):
                    if not gateway_unavailable:
                        logger.info(
                            "Gateway Discord sedang reconnect; pembaruan activity ditunda."
                        )
                        gateway_unavailable = True
                    await asyncio.sleep(min(settings.activity_rotation_interval, 10))
                    continue
                except Exception:
                    logger.exception("Gagal memperbarui activity, akan mencoba lagi nanti.")
                await asyncio.sleep(settings.activity_rotation_interval)
        except asyncio.CancelledError:
            raise

    async def close(self) -> None:
        if self._activity_task and not self._activity_task.done():
            self._activity_task.cancel()
            await asyncio.gather(self._activity_task, return_exceptions=True)
        self._activity_task = None
        if self.custom_web_server is not None:
            await self.custom_web_server.close()
            self.custom_web_server = None
        await super().close()

    async def on_guild_join(self, guild: discord.Guild) -> None:
        await repo.get_or_create_guild_config(guild.id)
        try:
            await self.resync_commands(guild.id)
        except discord.HTTPException:
            logger.exception("Gagal sync slash command ke guild baru %s.", guild.id)
        logger.info("Bergabung ke guild baru: %s (%s)", guild.name, guild.id)


bot = ManagementBot()


async def main() -> None:
    async with bot:
        # Graceful shutdown: pastikan koneksi database/gateway ditutup rapi
        # saat menerima SIGTERM (dikirim systemd saat `systemctl stop`).
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _handle_signal() -> None:
            logger.info("Sinyal shutdown diterima, menutup bot dengan rapi...")
            stop_event.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _handle_signal)
            except NotImplementedError:
                # add_signal_handler tidak didukung di Windows
                pass

        bot_task = asyncio.create_task(bot.start(settings.discord_token, reconnect=True))
        stop_task = asyncio.create_task(stop_event.wait())

        done, pending = await asyncio.wait({bot_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)

        if stop_task in done:
            await bot.close()
        for task in pending:
            task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot dihentikan lewat KeyboardInterrupt.")
