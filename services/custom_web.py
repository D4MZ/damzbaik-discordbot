"""Web editor self-hosted untuk custom message builder."""

from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import urlsplit

import discord
from aiohttp import web

from config import settings
from database import repositories as repo
from services.custom_messages import (
    CustomMessageValidationError,
    build_legacy_embeds,
    build_v2_view,
    dump_payload,
    parse_payload,
    send_custom_message,
)
from services.dashboard_web import DashboardWeb
from utils.logger import get_logger

logger = get_logger(__name__)
EDITOR_FILE = Path(__file__).resolve().parent.parent / "web" / "custom_editor.html"
WEBHOOK_PATH = re.compile(r"^/api(?:/v\d+)?/webhooks/\d+/[A-Za-z0-9._-]+/?$")
DISCORD_WEBHOOK_HOSTS = frozenset({
    "discord.com",
    "www.discord.com",
    "discordapp.com",
    "canary.discord.com",
    "ptb.discord.com",
})


def validate_webhook_url(value: object) -> str:
    webhook_url = str(value or "").strip()
    parsed = urlsplit(webhook_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in DISCORD_WEBHOOK_HOSTS
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or not WEBHOOK_PATH.fullmatch(parsed.path)
    ):
        raise CustomMessageValidationError(
            "Webhook URL tidak valid. Gunakan URL webhook resmi https://discord.com/api/webhooks/..."
        )
    return webhook_url


async def get_or_create_builder_webhook(channel: discord.TextChannel) -> discord.Webhook:
    for webhook in await channel.webhooks():
        if webhook.user and channel.guild.me and webhook.user.id == channel.guild.me.id:
            if webhook.name == "Custom Message Builder":
                return webhook
    return await channel.create_webhook(name="Custom Message Builder", reason="Custom message builder")


class CustomMessageWebServer:
    def __init__(self, bot: discord.Client, *, host: str, port: int):
        self.bot = bot
        self.host = host
        self.port = port
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self.dashboard_web = DashboardWeb(bot)

    async def start(self) -> None:
        @web.middleware
        async def security_headers(request: web.Request, handler):
            response = await handler(request)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' https: data:; "
                "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
                "connect-src 'self'; frame-ancestors 'self'"
            )
            return response

        app = web.Application(
            client_max_size=2 * 1024 * 1024,
            middlewares=[security_headers],
        )
        editor_enabled = settings.custom_web_enabled or settings.dashboard_enabled
        if editor_enabled:
            app.router.add_get("/custom/{token}", self.editor)
            app.router.add_get("/api/custom/{token}", self.get_draft)
            app.router.add_put("/api/custom/{token}", self.save_draft)
            app.router.add_post("/api/custom/{token}/send", self.send_draft)
        app.router.add_get("/health", self.health)
        if settings.dashboard_enabled:
            self.dashboard_web.register(app)
            await self.dashboard_web.start()
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()
        logger.info("Web dashboard/editor aktif di http://%s:%s", self.host, self.port)

    async def close(self) -> None:
        await self.dashboard_web.close()
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
            self.site = None

    async def _draft(self, request: web.Request):
        draft = await repo.get_custom_message_draft_by_token(request.match_info["token"])
        if draft is None:
            raise web.HTTPNotFound(text="Editor link tidak ditemukan atau sudah dihapus.")
        return draft

    async def editor(self, request: web.Request) -> web.Response:
        await self._draft(request)
        if not EDITOR_FILE.exists():
            raise web.HTTPInternalServerError(text="File web editor tidak ditemukan.")
        return web.FileResponse(EDITOR_FILE)

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "ok": True,
                "bot_ready": self.bot.is_ready(),
                "dashboard": settings.dashboard_enabled,
                "dashboard_oauth": self.dashboard_web.configured,
                "custom_editor": settings.custom_web_enabled or settings.dashboard_enabled,
            }
        )

    async def get_draft(self, request: web.Request) -> web.Response:
        draft = await self._draft(request)
        guild = self.bot.get_guild(draft.guild_id)
        bot_member = guild.me if guild else None
        channels = []
        if guild and bot_member:
            channels = [
                {"id": str(channel.id), "name": channel.name, "category": channel.category.name if channel.category else ""}
                for channel in guild.text_channels
                if channel.permissions_for(bot_member).manage_webhooks
                and channel.permissions_for(bot_member).send_messages
            ]
        return web.json_response(
            {
                "id": draft.id,
                "name": draft.name,
                "mode": draft.mode,
                "guild": guild.name if guild else str(draft.guild_id),
                "payload": parse_payload(draft.payload_json),
                "channels": channels,
            }
        )

    async def save_draft(self, request: web.Request) -> web.Response:
        draft = await self._draft(request)
        try:
            body = await request.json()
            mode = str(body.get("mode") or draft.mode).lower()
            if mode not in {"legacy", "v2", "both"}:
                raise CustomMessageValidationError("Mode tidak valid.")
            payload = parse_payload(body.get("payload"))
            if mode in {"legacy", "both"}:
                build_legacy_embeds(payload)
            if mode in {"v2", "both"}:
                build_v2_view(payload)
            name = str(body.get("name") or draft.name).strip()[:100]
            await repo.update_custom_message_draft_by_token(
                draft.editor_token,
                name=name,
                mode=mode,
                payload_json=dump_payload(payload),
            )
        except (CustomMessageValidationError, ValueError, TypeError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True})

    async def send_draft(self, request: web.Request) -> web.Response:
        draft = await self._draft(request)
        try:
            body = await request.json()
        except (ValueError, TypeError):
            return web.json_response({"ok": False, "error": "Body request tidak valid."}, status=400)
        webhook_url = str(body.get("webhook_url") or "").strip()
        if webhook_url:
            try:
                webhook = discord.Webhook.from_url(validate_webhook_url(webhook_url), client=self.bot)
                await send_custom_message(
                    webhook,
                    mode=draft.mode,
                    payload=parse_payload(draft.payload_json),
                )
            except (CustomMessageValidationError, ValueError, discord.HTTPException) as exc:
                return web.json_response({"ok": False, "error": str(exc)}, status=400)
            return web.json_response({"ok": True, "channel": "webhook eksternal"})
        try:
            channel_id = int(body.get("channel_id"))
        except (TypeError, ValueError):
            return web.json_response({"ok": False, "error": "Channel tujuan tidak valid."}, status=400)
        guild = self.bot.get_guild(draft.guild_id)
        channel = guild.get_channel(channel_id) if guild else None
        if not isinstance(channel, discord.TextChannel):
            return web.json_response({"ok": False, "error": "Channel tidak ditemukan."}, status=404)
        bot_member = guild.me
        if bot_member is None:
            return web.json_response({"ok": False, "error": "Bot belum siap di server ini."}, status=503)
        permissions = channel.permissions_for(bot_member)
        if not permissions.manage_webhooks or not permissions.send_messages:
            return web.json_response(
                {"ok": False, "error": "Bot membutuhkan Manage Webhooks dan Send Messages."},
                status=403,
            )
        try:
            webhook = await get_or_create_builder_webhook(channel)
            await send_custom_message(
                webhook,
                mode=draft.mode,
                payload=parse_payload(draft.payload_json),
            )
        except (CustomMessageValidationError, discord.HTTPException) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        return web.json_response({"ok": True, "channel": channel.name})
