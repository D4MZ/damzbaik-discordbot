"""UI Components V2 untuk menu /help."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Mapping

import discord

from utils.logger import get_logger

logger = get_logger(__name__)
HELP_ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "help_icons"
HELP_BANNER_DIR = Path(__file__).resolve().parent.parent / "assets" / "help_banners"
HelpEmoji = discord.Emoji | discord.PartialEmoji | str
_help_emojis: dict[str, HelpEmoji] | None = None
_help_emoji_lock: asyncio.Lock | None = None

HELP_CATEGORIES: dict[str, dict] = {
    "general": {
        "label": "General",
        "emoji": "📖",
        "icon_file": "general.png",
        "emoji_name": "help_general",
        "banner_file": "general.png",
        "commands": [
            "/ping", "/help", "/say", "/say-edit", "/show payment", "/payment set",
            "/payment list", "/payment edit", "/payment delete",
        ],
    },
    "welcome": {
        "label": "Welcome",
        "emoji": "👋",
        "icon_file": "welcome.png",
        "emoji_name": "help_welcome",
        "banner_file": "welcome.png",
        "commands": [
            "/welcome enable", "/welcome disable", "/welcome set-type", "/welcome set-text",
            "/welcome set-embed", "/welcome set-mention", "/welcome set-timestamp", "/welcome preview",
            "/leave enable", "/leave disable", "/leave set-type", "/leave set-text",
            "/leave set-embed", "/leave set-mention", "/leave set-timestamp", "/leave preview",
        ],
    },
    "role": {
        "label": "Role",
        "emoji": "🎭",
        "icon_file": "role.png",
        "emoji_name": "help_role",
        "banner_file": "role.png",
        "commands": [
            "/role dropdown", "/role reaction", "/role autorole",
        ],
    },
    "logging": {
        "label": "Logging",
        "emoji": "📝",
        "icon_file": "logging.png",
        "emoji_name": "help_logging",
        "banner_file": "logging.png",
        "commands": ["/log set-channel"],
    },
    "admin": {
        "label": "Admin",
        "emoji": "🛡️",
        "icon_file": "admin.png",
        "emoji_name": "help_admin",
        "banner_file": "admin.png",
        "commands": [
            "/settings", "/config", "/payment clear", "/invite create", "/invite list",
            "/invite delete", "/invite info", "/invite leaderboard", "/invite user", "/invite stats",
            "/announcement create", "/set-status",
            "/antinuke setup", "/antinuke toggle", "/antinuke feature",
            "/antinuke whitelist-add", "/antinuke whitelist-remove", "/antinuke status",
        ],
    },
    "image": {
        "label": "Image",
        "emoji": "🖼️",
        "icon_file": "image.png",
        "emoji_name": "help_image",
        "banner_file": "help.png",
        "commands": ["/image upload", "/image show", "/image list", "/image delete"],
    },
    "custom": {
        "label": "Custom Message",
        "emoji": "✨",
        "icon_file": "custom_message.png",
        "emoji_name": "help_custom_message",
        "banner_file": "custom_message.png",
        "commands": [
            "/custom create", "/custom list", "/custom editor", "/custom quick-edit", "/custom set-mode",
            "/custom set-json", "/custom preview", "/custom send", "/custom delete",
        ],
    },
    "boost": {
        "label": "Boost",
        "emoji": "🚀",
        "icon_file": "admin.png",
        "emoji_name": "help_boost",
        "banner_file": "admin.png",
        "commands": ["/boost enable", "/boost disable", "/boost set-message", "/boost preview"],
    },
    "review": {
        "label": "Review",
        "emoji": "⭐",
        "icon_file": "admin.png",
        "emoji_name": "help_review",
        "banner_file": "admin.png",
        "commands": ["/review setup"],
    },
    "prefix": {
        "label": "Prefix Command",
        "emoji": "📜",
        "icon_file": "admin.png",
        "emoji_name": "help_prefix",
        "banner_file": "admin.png",
        "commands": ["/prefix add", "/prefix delete", "/prefix edit", "/prefix list", "/prefix view"],
    },
    "worker": {
        "label": "Worker Status",
        "emoji": "👷",
        "icon_file": "admin.png",
        "emoji_name": "help_worker_status",
        "banner_file": "admin.png",
        "commands": [
            "/worker-status action:Input list worker members:@Worker1 @Worker2",
            "/worker-status action:Publish ke channel channel:#channel",
            "/worker-status action:Tambah worker member:@Worker",
            "/worker-status action:Hapus worker member:@Worker",
            "/worker-status action:Lihat daftar worker",
        ],
    },
}


COMMAND_GUIDES: dict[str, str] = {
    "/ping": "Check bot gateway and roundtrip latency.",
    "/help": "Open this help menu and browse commands by category.",
    "/say": "Send as plain text or choose True for a container box. Requires Manage Messages.",
    "/say-edit": "Paste a bot message ID (right-click → Copy Message ID) to edit its text in a form.",
    "/show payment": "Display the server's available payment methods.",
    "/payment set": "Add or update one of your payment methods.",
    "/payment list": "View your saved payment methods.",
    "/payment edit": "Edit one of your saved payment methods.",
    "/payment delete": "Delete one of your saved payment methods.",
    "/welcome enable": "Enable welcome messages for new members.",
    "/welcome disable": "Disable welcome messages.",
    "/welcome set-type": "Choose text or embed welcome messages.",
    "/welcome set-text": "Set the text used in welcome messages.",
    "/welcome set-embed": "Configure the welcome embed title, text, and style.",
    "/welcome set-mention": "Turn new-member mentions on or off.",
    "/welcome set-timestamp": "Turn welcome embed timestamps on or off.",
    "/welcome preview": "Preview the current welcome message before using it.",
    "/leave enable": "Enable leave messages when a member leaves the server.",
    "/leave disable": "Disable leave messages.",
    "/leave set-type": "Choose text or embed leave messages.",
    "/leave set-text": "Set the text used in leave messages, e.g. {username} left {server}.",
    "/leave set-embed": "Configure the leave embed title, text, and style.",
    "/leave set-mention": "Turn member mentions in leave messages on or off.",
    "/leave set-timestamp": "Turn leave embed timestamps on or off.",
    "/leave preview": "Preview the current leave message before using it.",
    "/role dropdown": "Set a channel and title, then pick roles from the menu. The panel is posted for you.",
    "/role reaction": "Set a channel and title, then type emoji + role pairs, e.g. 🎮 @Gamer 🎨 @Artist.",
    "/role autorole": "Mention roles for new members, e.g. @Member. Leave empty to turn it off.",
    "/log set-channel": "Set the channel for a selected log type.",
    "/settings": "Open the server configuration dashboard.",
    "/config": "Alias of /settings; open server configuration.",
    "/payment clear": "Clear the server's configured payment methods.",
    "/invite create": "Create a Discord invite managed by the bot.",
    "/invite list": "List invites created through the bot.",
    "/invite delete": "Delete a managed invite.",
    "/invite info": "Track an invite link: view usage count, creator, channel, expiry, and status.",
    "/invite leaderboard": "View the server invite leaderboard.",
    "/invite user": "View invite statistics for a selected member.",
    "/invite stats": "View your own invite statistics.",
    "/announcement create": "Create and send an announcement after previewing it.",
    "/set-status": "Change the bot's Watching status text.",
    "/antinuke setup": "Enable and configure anti-nuke protection.",
    "/antinuke toggle": "Enable or disable anti-nuke protection.",
    "/antinuke feature": "Enable or disable one anti-nuke feature.",
    "/antinuke whitelist-add": "Add a trusted member to the anti-nuke whitelist.",
    "/antinuke whitelist-remove": "Remove a member from the anti-nuke whitelist.",
    "/antinuke status": "View anti-nuke protection and whitelist status.",
    "/image upload": "Upload and save an image asset with a name and category.",
    "/image show": "Display a saved image by name.",
    "/image list": "List saved images, optionally filtered by category.",
    "/image delete": "Delete a saved image asset.",
    "/custom create": "Create a new custom message draft.",
    "/custom list": "List all custom message drafts.",
    "/custom editor": "Get an editor link or JSON template for a draft.",
    "/custom quick-edit": "Edit the main text of a draft directly in Discord.",
    "/custom set-mode": "Choose legacy, Components V2, or both message modes.",
    "/custom set-json": "Update a draft from an editor JSON export.",
    "/custom preview": "Preview a custom message privately.",
    "/custom send": "Send a custom message draft through the bot webhook.",
    "/custom delete": "Delete a custom message draft.",
    "/boost enable": "Enable automatic messages when the server is boosted.",
    "/boost disable": "Disable automatic boost messages.",
    "/boost set-message": "Configure the server boost message.",
    "/boost preview": "Preview the current boost message.",
    "/prefix add": "Create a custom command like !rules with its reply. Use \\n for new lines.",
    "/prefix delete": "Delete a custom prefix command.",
    "/prefix edit": "Change the reply or description of a custom prefix command.",
    "/prefix list": "List all custom prefix commands in this server.",
    "/prefix view": "View the full reply and details of a custom prefix command.",
    "/review setup":"Publish a review panel in this or another channel.",
    "/worker-status action:Input list worker members:@Worker1 @Worker2": "Input worker members for the status panel.",
    "/worker-status action:Publish ke channel channel:#channel": "Publish the worker status panel to a channel.",
    "/worker-status action:Tambah worker member:@Worker": "Add a worker to the status panel.",
    "/worker-status action:Hapus worker member:@Worker": "Remove a worker from the status panel.",
    "/worker-status action:Lihat daftar worker": "View the current worker list.",
}


def _fallback_emojis() -> dict[str, HelpEmoji]:
    return {key: data["emoji"] for key, data in HELP_CATEGORIES.items()}


async def ensure_help_emojis(bot: discord.Client) -> dict[str, HelpEmoji]:
    global _help_emojis, _help_emoji_lock
    if _help_emojis is not None:
        return _help_emojis
    if _help_emoji_lock is None:
        _help_emoji_lock = asyncio.Lock()
    async with _help_emoji_lock:
        if _help_emojis is not None:
            return _help_emojis
        resolved = _fallback_emojis()
        try:
            existing = {
                emoji.name: emoji
                for emoji in await bot.fetch_application_emojis()
            }
            for key, data in HELP_CATEGORIES.items():
                emoji = existing.get(data["emoji_name"])
                if emoji is None:
                    icon_path = HELP_ICON_DIR / data["icon_file"]
                    if not icon_path.is_file():
                        logger.warning("Icon /help tidak ditemukan: %s", icon_path)
                        continue
                    try:
                        emoji = await bot.create_application_emoji(
                            name=data["emoji_name"],
                            image=icon_path.read_bytes(),
                        )
                        logger.info("Application emoji /help dibuat: %s", data["emoji_name"])
                    except (discord.HTTPException, OSError):
                        logger.exception(
                            "Gagal membuat application emoji /help: %s",
                            data["emoji_name"],
                        )
                        continue
                resolved[key] = emoji
        except (discord.HTTPException, OSError):
            logger.exception("Gagal menyiapkan custom icon /help; memakai emoji bawaan.")
        _help_emojis = resolved
        return resolved


def _category_emoji(key: str, emojis: Mapping[str, HelpEmoji] | None) -> HelpEmoji:
    return emojis.get(key, HELP_CATEGORIES[key]["emoji"]) if emojis else HELP_CATEGORIES[key]["emoji"]


def build_category_content(key: str, emojis: Mapping[str, HelpEmoji] | None = None) -> str:
    category = HELP_CATEGORIES[key]
    commands = "\n".join(
        f"`{command}` — {COMMAND_GUIDES.get(command, 'Follow the options shown by Discord.') }"
        for command in category["commands"]
    )
    return (
        f"**{_category_emoji(key, emojis)} {category['label']} Commands**\n\n"
        f"{commands}"
    )


def help_banner_file(key: str | None = None) -> discord.File:
    filename = HELP_CATEGORIES.get(key or "", {}).get("banner_file", "help.png")
    path = HELP_BANNER_DIR / filename
    if not path.is_file():
        path = HELP_BANNER_DIR / "help.png"
    return discord.File(path, filename="help_banner.png")


class HelpSelect(discord.ui.Select):
    def __init__(self, emojis: Mapping[str, HelpEmoji] | None = None):
        self.help_emojis = emojis
        options = [
            discord.SelectOption(
                label=data["label"],
                value=key,
                emoji=_category_emoji(key, emojis),
            )
            for key, data in HELP_CATEGORIES.items()
        ]
        super().__init__(placeholder="Pilih kategori bantuan...", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        key = self.values[0]
        banner = help_banner_file(key)
        view = HelpView(
            content=build_category_content(key, self.help_emojis),
            emojis=self.help_emojis,
            banner=banner,
        )
        await interaction.response.edit_message(
            content=None,
            embed=None,
            attachments=[banner],
            view=view,
        )


class HelpView(discord.ui.LayoutView):
    def __init__(
        self,
        *,
        content: str,
        emojis: Mapping[str, HelpEmoji] | None = None,
        banner: discord.File | None = None,
    ):
        super().__init__(timeout=120)
        gallery = discord.ui.MediaGallery()
        gallery.add_item(
            media=banner or "attachment://help_banner.png",
            description="Banner menu bantuan",
        )
        self.add_item(
            discord.ui.Container(
                gallery,
                discord.ui.TextDisplay(content),
                discord.ui.ActionRow(HelpSelect(emojis)),
            )
        )


def build_help_home_content(
    bot_name: str,
    emojis: Mapping[str, HelpEmoji] | None = None,
) -> str:
    lines = [f"**❓ Bantuan {bot_name}**", "", "Pilih kategori di bawah untuk melihat daftar command administrator.", ""]
    for key, data in HELP_CATEGORIES.items():
        lines.append(f"{_category_emoji(key, emojis)} **{data['label']}** — {len(data['commands'])} command")
    return "\n".join(lines)
