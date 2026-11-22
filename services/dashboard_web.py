"""OAuth Discord dan API untuk dashboard web bot."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import discord
from aiohttp import ClientSession, web

from config import settings
from database import repositories as repo
from services.custom_messages import DEFAULT_PAYLOAD, dump_payload

DASHBOARD_FILE = Path(__file__).resolve().parent.parent / "web" / "dashboard.html"
DISCORD_API = "https://discord.com/api/v10"
ADMINISTRATOR = 1 << 3
MANAGE_GUILD = 1 << 5
MAX_SESSIONS = 5_000
MAX_OAUTH_STATES = 5_000


@dataclass
class DashboardSession:
    user_id: int
    username: str
    avatar_url: str | None
    guild_ids: frozenset[int]
    csrf_token: str
    expires_at: dt.datetime


def command_rows(bot: discord.Client) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def visit(command, prefix: str = "") -> None:
        name = f"{prefix} {command.name}".strip()
        children = getattr(command, "commands", None)
        if children:
            for child in children:
                visit(child, name)
            return
        rows.append({
            "name": f"/{name}",
            "category": name.split(" ", 1)[0].title(),
            "description": command.description or "Tanpa deskripsi.",
        })

    for command in bot.tree.get_commands():
        visit(command)
    return sorted(rows, key=lambda row: row["name"])


class DashboardWeb:
    def __init__(self, bot: discord.Client):
        self.bot = bot
        self.http: ClientSession | None = None
        self.sessions: dict[str, DashboardSession] = {}
        self.oauth_states: dict[str, dt.datetime] = {}

    @property
    def configured(self) -> bool:
        return bool(
            settings.dashboard_enabled
            and settings.discord_client_id
            and settings.discord_client_secret
            and settings.dashboard_redirect_uri
        )

    def register(self, app: web.Application) -> None:
        app.router.add_get("/", self.page)
        app.router.add_get("/dashboard", self.page)
        app.router.add_get("/auth/discord", self.login)
        app.router.add_get("/auth/discord/callback", self.callback)
        app.router.add_post("/auth/logout", self.logout)
        app.router.add_get("/api/dashboard/me", self.me)
        app.router.add_get("/api/dashboard/guilds", self.guilds)
        app.router.add_get("/api/dashboard/guilds/{guild_id}", self.guild_info)
        app.router.add_get("/api/dashboard/guilds/{guild_id}/features", self.features)
        app.router.add_put("/api/dashboard/guilds/{guild_id}/features/{feature}", self.update_feature)
        app.router.add_get("/api/dashboard/commands", self.commands)
        app.router.add_get("/api/dashboard/guilds/{guild_id}/drafts", self.drafts)
        app.router.add_post("/api/dashboard/guilds/{guild_id}/drafts", self.create_draft)
        app.router.add_delete("/api/dashboard/guilds/{guild_id}/drafts/{draft_id}", self.delete_draft)

    async def start(self) -> None:
        self.http = ClientSession()

    async def close(self) -> None:
        if self.http:
            await self.http.close()
            self.http = None

    def clean_expired(self) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        self.sessions = {key: value for key, value in self.sessions.items() if value.expires_at > now}
        self.oauth_states = {key: value for key, value in self.oauth_states.items() if value > now}

    @staticmethod
    async def json_body(request: web.Request) -> dict:
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise web.HTTPBadRequest(text="Body JSON tidak valid.") from exc
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text="Body JSON harus berupa object.")
        return body

    def session(self, request: web.Request) -> DashboardSession:
        self.clean_expired()
        session = self.sessions.get(request.cookies.get("dashboard_session", ""))
        if session is None:
            raise web.HTTPUnauthorized(text="Login Discord diperlukan.")
        return session

    @staticmethod
    def check_csrf(request: web.Request, session: DashboardSession) -> None:
        if request.headers.get("X-CSRF-Token") != session.csrf_token:
            raise web.HTTPForbidden(text="Token keamanan tidak valid.")

    async def guild_access(self, request: web.Request) -> tuple[DashboardSession, discord.Guild]:
        session = self.session(request)
        try:
            guild_id = int(request.match_info["guild_id"])
        except ValueError as exc:
            raise web.HTTPBadRequest(text="Guild ID tidak valid.") from exc
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            raise web.HTTPNotFound(text="Bot tidak terhubung ke server ini.")
        if session.user_id != settings.bot_owner_id and guild.id not in session.guild_ids:
            raise web.HTTPForbidden(text="Anda tidak memiliki Manage Server.")
        member = guild.get_member(session.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(session.user_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None
        allowed = session.user_id == settings.bot_owner_id or guild.owner_id == session.user_id
        allowed = allowed or bool(member and (member.guild_permissions.administrator or member.guild_permissions.manage_guild))
        if not allowed:
            raise web.HTTPForbidden(text="Akses administrator sudah tidak berlaku.")
        return session, guild

    async def page(self, request: web.Request) -> web.Response:
        if not settings.dashboard_enabled:
            raise web.HTTPNotFound(text="Dashboard belum diaktifkan.")
        if not DASHBOARD_FILE.exists():
            raise web.HTTPInternalServerError(text="File dashboard tidak ditemukan.")
        return web.FileResponse(DASHBOARD_FILE)

    async def login(self, request: web.Request) -> web.Response:
        if not self.configured:
            raise web.HTTPServiceUnavailable(text="OAuth Discord dashboard belum dikonfigurasi.")
        self.clean_expired()
        if len(self.oauth_states) >= MAX_OAUTH_STATES:
            oldest_state = min(self.oauth_states, key=self.oauth_states.get)
            self.oauth_states.pop(oldest_state, None)
        state = secrets.token_urlsafe(32)
        self.oauth_states[state] = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)
        query = urlencode({
            "client_id": settings.discord_client_id,
            "response_type": "code",
            "redirect_uri": settings.dashboard_redirect_uri,
            "scope": "identify guilds",
            "state": state,
            "prompt": "none",
        })
        response = web.HTTPFound(f"https://discord.com/oauth2/authorize?{query}")
        secure = bool(settings.custom_web_public_url and urlsplit(settings.custom_web_public_url).scheme == "https")
        response.set_cookie("dashboard_oauth_state", state, httponly=True, secure=secure, samesite="Lax", max_age=600, path="/")
        raise response

    async def callback(self, request: web.Request) -> web.Response:
        self.clean_expired()
        state = request.query.get("state", "")
        code = request.query.get("code", "")
        if not code or request.cookies.get("dashboard_oauth_state") != state or self.oauth_states.pop(state, None) is None:
            raise web.HTTPBadRequest(text="State OAuth tidak valid atau kedaluwarsa.")
        if self.http is None or not self.configured:
            raise web.HTTPServiceUnavailable(text="Layanan OAuth belum siap.")
        async with self.http.post(f"{DISCORD_API}/oauth2/token", data={
            "client_id": settings.discord_client_id,
            "client_secret": settings.discord_client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.dashboard_redirect_uri,
        }) as response:
            if response.status != 200:
                raise web.HTTPBadGateway(text="Login Discord gagal.")
            access_token = (await response.json())["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        async with self.http.get(f"{DISCORD_API}/users/@me", headers=headers) as response:
            if response.status != 200:
                raise web.HTTPBadGateway(text="Profil Discord tidak dapat dibaca.")
            user = await response.json()
        async with self.http.get(f"{DISCORD_API}/users/@me/guilds", headers=headers) as response:
            if response.status != 200:
                raise web.HTTPBadGateway(text="Daftar server Discord tidak dapat dibaca.")
            oauth_guilds = await response.json()
        user_id = int(user["id"])
        guild_ids = frozenset(
            int(item["id"])
            for item in oauth_guilds
            if item.get("owner") or int(item.get("permissions", "0")) & (ADMINISTRATOR | MANAGE_GUILD)
        )
        avatar_hash = user.get("avatar")
        avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=128" if avatar_hash else None
        token = secrets.token_urlsafe(48)
        self.clean_expired()
        if len(self.sessions) >= MAX_SESSIONS:
            oldest_session = min(self.sessions, key=lambda key: self.sessions[key].expires_at)
            self.sessions.pop(oldest_session, None)
        self.sessions[token] = DashboardSession(
            user_id=user_id,
            username=user.get("global_name") or user.get("username") or str(user_id),
            avatar_url=avatar_url,
            guild_ids=guild_ids,
            csrf_token=secrets.token_urlsafe(32),
            expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=settings.dashboard_session_hours),
        )
        response = web.HTTPFound("/dashboard")
        secure = bool(settings.custom_web_public_url and urlsplit(settings.custom_web_public_url).scheme == "https")
        response.set_cookie("dashboard_session", token, httponly=True, secure=secure, samesite="Lax", max_age=settings.dashboard_session_hours * 3600, path="/")
        response.del_cookie("dashboard_oauth_state", path="/")
        raise response

    async def logout(self, request: web.Request) -> web.Response:
        session = self.session(request)
        self.check_csrf(request, session)
        self.sessions.pop(request.cookies.get("dashboard_session", ""), None)
        response = web.json_response({"ok": True})
        response.del_cookie("dashboard_session", path="/")
        return response

    async def me(self, request: web.Request) -> web.Response:
        if not self.configured:
            return web.json_response({"authenticated": False, "configured": False})
        try:
            session = self.session(request)
        except web.HTTPUnauthorized:
            return web.json_response({"authenticated": False, "configured": True})
        return web.json_response({
            "authenticated": True,
            "configured": True,
            "user": {"id": str(session.user_id), "username": session.username, "avatar_url": session.avatar_url},
            "csrf_token": session.csrf_token,
            "bot": {
                "name": str(self.bot.user) if self.bot.user else "Discord Bot",
                "ready": self.bot.is_ready(),
                "latency_ms": round(self.bot.latency * 1000),
                "guild_count": len(self.bot.guilds),
                "command_count": len(command_rows(self.bot)),
            },
        })

    async def guilds(self, request: web.Request) -> web.Response:
        session = self.session(request)
        rows = []
        for guild in self.bot.guilds:
            if session.user_id != settings.bot_owner_id and guild.id not in session.guild_ids:
                continue
            rows.append({
                "id": str(guild.id),
                "name": guild.name,
                "icon_url": str(guild.icon.url) if guild.icon else None,
                "member_count": guild.member_count or len(guild.members),
                "owner": guild.owner_id == session.user_id,
            })
        return web.json_response({"guilds": sorted(rows, key=lambda item: item["name"].lower())})

    async def guild_info(self, request: web.Request) -> web.Response:
        _, guild = await self.guild_access(request)
        owner = guild.owner
        if owner is None:
            try:
                owner = await guild.fetch_member(guild.owner_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                owner = None
        text_channels = sum(isinstance(channel, discord.TextChannel) for channel in guild.channels)
        voice_channels = sum(isinstance(channel, (discord.VoiceChannel, discord.StageChannel)) for channel in guild.channels)
        categories = sum(isinstance(channel, discord.CategoryChannel) for channel in guild.channels)
        tier_value = getattr(guild.premium_tier, "value", guild.premium_tier)
        tier = {0: "Not boosted", 1: "Tier 1", 2: "Tier 2", 3: "Tier 3"}.get(
            int(tier_value),
            f"Tier {tier_value}",
        )
        return web.json_response({
            "id": str(guild.id),
            "name": guild.name,
            "icon_url": str(guild.icon.url) if guild.icon else None,
            "owner": f"@{owner.name}" if owner else str(guild.owner_id),
            "owner_id": str(guild.owner_id),
            "boosts": guild.premium_subscription_count or 0,
            "boost_tier": tier,
            "roles": max(0, len(guild.roles) - 1),
            "channels": len(guild.channels),
            "text_channels": text_channels,
            "voice_channels": voice_channels,
            "categories": categories,
            "members": guild.member_count or len(guild.members),
            "created_at": guild.created_at.isoformat(),
        })

    async def feature_rows(self, guild: discord.Guild, user_id: int) -> list[dict]:
        values = await asyncio.gather(
            repo.get_or_create_guild_config(guild.id),
            repo.get_or_create_anti_nuke_config(guild.id),
            repo.list_payment_methods(guild.id),
            repo.list_managed_invites(guild.id),
            repo.list_role_dropdowns(guild.id),
            repo.list_image_assets(guild.id),
            repo.list_custom_message_drafts(guild.id),
        )
        guild_config, anti_nuke, payments, invites, dropdowns, images, drafts = values
        log_count = sum(channel_id is not None for channel_id in (
            guild_config.message_log_channel_id,
            guild_config.voice_log_channel_id,
            guild_config.member_log_channel_id,
        ))
        return [
            {"key": "welcome", "name": "Welcome", "enabled": guild_config.welcome_enabled, "editable": True, "detail": f"Mode {guild_config.welcome_type}"},
            {"key": "payment", "name": "Payment", "enabled": bool(payments), "editable": False, "detail": f"{len(payments)} metode tersimpan"},
            {"key": "invite", "name": "Invite", "enabled": bool(invites), "editable": False, "detail": f"{len(invites)} invite dikelola"},
            {"key": "role", "name": "Role System", "enabled": guild_config.autorole_enabled or bool(dropdowns), "editable": False, "detail": f"{len(dropdowns)} dropdown; autorole {'aktif' if guild_config.autorole_enabled else 'nonaktif'}"},
            {"key": "logging", "name": "Logging", "enabled": log_count > 0, "editable": False, "detail": f"{log_count}/3 channel log diatur"},
            {"key": "image", "name": "Image Manager", "enabled": bool(images), "editable": False, "detail": f"{len(images)} image"},
            {"key": "custom", "name": "Custom Message", "enabled": bool(drafts), "editable": False, "detail": f"{len(drafts)} draft"},
            {"key": "anti_nuke", "name": "Anti-Nuke", "enabled": anti_nuke.enabled, "editable": user_id in {guild.owner_id, settings.bot_owner_id}, "detail": "18 proteksi keamanan; hanya owner yang dapat mengubah"},
            {"key": "announcement", "name": "Announcement", "enabled": True, "editable": False, "detail": "Siap digunakan"},
        ]

    async def features(self, request: web.Request) -> web.Response:
        session, guild = await self.guild_access(request)
        return web.json_response({"features": await self.feature_rows(guild, session.user_id)})

    async def update_feature(self, request: web.Request) -> web.Response:
        session, guild = await self.guild_access(request)
        self.check_csrf(request, session)
        enabled = (await self.json_body(request)).get("enabled")
        if not isinstance(enabled, bool):
            raise web.HTTPBadRequest(text="Nilai enabled harus berupa boolean.")
        feature = request.match_info["feature"]
        if feature == "welcome":
            await repo.update_guild_config(guild.id, welcome_enabled=enabled)
        elif feature == "anti_nuke":
            if session.user_id not in {guild.owner_id, settings.bot_owner_id}:
                raise web.HTTPForbidden(text="Anti-nuke hanya dapat diubah oleh owner server atau owner bot.")
            await repo.update_anti_nuke_config(guild.id, enabled=enabled)
            cog = self.bot.get_cog("Anti Nuke")
            if cog is not None and hasattr(cog, "_config"):
                await cog._config(guild.id, refresh=True)
        else:
            raise web.HTTPBadRequest(text="Fitur ini dikelola melalui command Discord.")
        return web.json_response({"ok": True, "enabled": enabled})

    async def commands(self, request: web.Request) -> web.Response:
        self.session(request)
        return web.json_response({"commands": command_rows(self.bot)})

    async def drafts(self, request: web.Request) -> web.Response:
        _, guild = await self.guild_access(request)
        drafts = await repo.list_custom_message_drafts(guild.id)
        base_url = settings.custom_web_public_url or ""
        return web.json_response({"drafts": [{
            "id": draft.id,
            "name": draft.name,
            "mode": draft.mode,
            "owner_id": str(draft.owner_id),
            "updated_at": draft.updated_at.isoformat(),
            "editor_url": f"{base_url}/custom/{draft.editor_token}" if base_url else f"/custom/{draft.editor_token}",
        } for draft in drafts]})

    async def create_draft(self, request: web.Request) -> web.Response:
        session, guild = await self.guild_access(request)
        self.check_csrf(request, session)
        body = await self.json_body(request)
        name = str(body.get("name") or "Untitled").strip()[:100] or "Untitled"
        mode = str(body.get("mode") or "both").lower()
        if mode not in {"legacy", "v2", "both"}:
            raise web.HTTPBadRequest(text="Mode draft tidak valid.")
        draft = await repo.create_custom_message_draft(
            guild_id=guild.id,
            owner_id=session.user_id,
            name=name,
            mode=mode,
            payload_json=dump_payload(DEFAULT_PAYLOAD),
            editor_token=secrets.token_urlsafe(32),
        )
        base_url = settings.custom_web_public_url or ""
        editor_url = f"{base_url}/custom/{draft.editor_token}" if base_url else f"/custom/{draft.editor_token}"
        return web.json_response({"ok": True, "draft": {"id": draft.id, "name": draft.name, "mode": draft.mode, "editor_url": editor_url}}, status=201)

    async def delete_draft(self, request: web.Request) -> web.Response:
        session, guild = await self.guild_access(request)
        self.check_csrf(request, session)
        try:
            draft_id = int(request.match_info["draft_id"])
        except ValueError as exc:
            raise web.HTTPBadRequest(text="Draft ID tidak valid.") from exc
        if not await repo.delete_custom_message_draft(draft_id, guild.id):
            raise web.HTTPNotFound(text="Draft tidak ditemukan.")
        return web.json_response({"ok": True})
