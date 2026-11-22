"""Helper untuk membuat embed Discord secara konsisten di seluruh bot."""

from __future__ import annotations

import datetime as dt

import discord

DEFAULT_COLOR = discord.Color.blurple()


def parse_color(value: str | None, default: discord.Color = DEFAULT_COLOR) -> discord.Color:
    if not value:
        return default
    try:
        return discord.Color(int(value.lstrip("#"), 16))
    except (ValueError, TypeError):
        return default


def success_embed(title: str, description: str = "") -> discord.Embed:
    return discord.Embed(title=f"✅ {title}", description=description, color=discord.Color.green())


def error_embed(title: str, description: str = "") -> discord.Embed:
    return discord.Embed(title=f"❌ {title}", description=description, color=discord.Color.red())


def info_embed(title: str, description: str = "") -> discord.Embed:
    return discord.Embed(title=f"ℹ️ {title}", description=description, color=discord.Color.blue())


def build_custom_embed(
    *,
    title: str | None = None,
    description: str | None = None,
    color: str | None = None,
    footer: str | None = None,
    thumbnail: str | None = None,
    image: str | None = None,
    author: str | None = None,
    author_icon_url: str | None = None,
    timestamp: bool = False,
) -> discord.Embed:
    embed = discord.Embed(
        title=title or None,
        description=description or None,
        color=parse_color(color),
    )
    if footer:
        embed.set_footer(text=footer)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if image:
        embed.set_image(url=image)
    if author:
        embed.set_author(name=author, icon_url=author_icon_url)
    if timestamp:
        embed.timestamp = dt.datetime.now(dt.timezone.utc)
    return embed
