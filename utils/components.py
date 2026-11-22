"""Helper Discord Components V2 untuk tampilan container polos."""

from __future__ import annotations

from collections.abc import Sequence

import discord


def build_plain_container(
    *,
    title: str | None = None,
    description: str | None = None,
    media: str | discord.File | None = None,
    media_description: str | None = None,
    items: Sequence[discord.ui.Item] = (),
    timeout: float | None = 180,
) -> discord.ui.LayoutView:
    children: list[discord.ui.Item] = []
    content_parts = []
    if title:
        content_parts.append(f"**{title}**")
    if description:
        content_parts.append(description)
    if content_parts:
        children.append(discord.ui.TextDisplay("\n\n".join(content_parts)))
    if media is not None:
        gallery = discord.ui.MediaGallery()
        gallery.add_item(media=media, description=media_description)
        children.append(gallery)
    children.extend(items)

    view = discord.ui.LayoutView(timeout=timeout)
    view.add_item(discord.ui.Container(*children))
    return view


def build_text_content(title: str, lines: Sequence[str]) -> str:
    body = "\n".join(lines)
    return f"**{title}**\n\n{body}" if body else f"**{title}**"
