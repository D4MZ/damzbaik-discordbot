"""Renderer dan pengirim custom message bergaya Discohook."""

from __future__ import annotations

import io
import json
import re
from typing import Any
from urllib.parse import unquote, urlsplit

import aiohttp
import discord


DEFAULT_PAYLOAD: dict[str, Any] = {
    "content": "",
    "username": "",
    "avatar_url": "",
    "legacy": {
        "title": "Judul Embed",
        "description": "Deskripsi embed lama.",
        "color": "#5865F2",
        "url": "",
        "author_name": "",
        "author_url": "",
        "author_icon_url": "",
        "thumbnail_url": "",
        "image_url": "",
        "footer_text": "",
        "footer_icon_url": "",
        "timestamp": False,
        "fields": [],
        "embeds": [],
    },
    "v2": {
        "accent_color": "",
        "spoiler": False,
        "components": [
            {"type": "text", "content": "## Judul Container\nDeskripsi Components V2."}
        ],
    },
}


class CustomMessageValidationError(ValueError):
    pass


FILE_HOSTS = frozenset({"cdn.discordapp.com", "media.discordapp.net"})
MAX_COMPONENT_FILE_BYTES = 10 * 1024 * 1024
SAFE_FILENAME = re.compile(r"[^A-Za-z0-9_.-]+")


def normalize_mode(mode: str) -> str:
    value = (mode or "legacy").strip().lower()
    if value not in {"legacy", "v2", "both"}:
        raise CustomMessageValidationError("Mode harus `legacy`, `v2`, atau `both`.")
    return value


def parse_payload(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return json.loads(json.dumps(DEFAULT_PAYLOAD))
    if isinstance(raw, dict):
        payload = raw
    else:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CustomMessageValidationError(f"JSON tidak valid: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise CustomMessageValidationError("Payload harus berupa object JSON.")
    merged = json.loads(json.dumps(DEFAULT_PAYLOAD))
    for key in ("content", "username", "avatar_url"):
        if key in payload:
            merged[key] = payload[key]
    for section in ("legacy", "v2"):
        incoming = payload.get(section)
        if isinstance(incoming, dict):
            merged[section].update(incoming)
    return merged


def dump_payload(payload: dict[str, Any]) -> str:
    return json.dumps(parse_payload(payload), ensure_ascii=False, separators=(",", ":"))


def parse_color(value: Any, *, allow_none: bool = True) -> discord.Color | None:
    text = str(value or "").strip()
    if not text and allow_none:
        return None
    try:
        return discord.Color.from_str(text or "#5865F2")
    except ValueError as exc:
        raise CustomMessageValidationError(f"Warna `{text}` tidak valid. Gunakan format #RRGGBB.") from exc


def _build_legacy_embed(data: dict[str, Any]) -> discord.Embed:
    title = str(data.get("title") or "")[:256] or None
    description = str(data.get("description") or "")[:4096] or None
    if not title and not description:
        description = "‎"
    embed = discord.Embed(
        title=title,
        description=description,
        color=parse_color(data.get("color"), allow_none=False),
        url=str(data.get("url") or "") or None,
        timestamp=discord.utils.utcnow() if data.get("timestamp") else None,
    )
    author_name = str(data.get("author_name") or "")[:256]
    if author_name:
        embed.set_author(
            name=author_name,
            url=str(data.get("author_url") or "") or None,
            icon_url=str(data.get("author_icon_url") or "") or None,
        )
    thumbnail = str(data.get("thumbnail_url") or "")
    image = str(data.get("image_url") or "")
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if image:
        embed.set_image(url=image)
    footer = str(data.get("footer_text") or "")[:2048]
    footer_icon = str(data.get("footer_icon_url") or "")
    if footer or footer_icon:
        embed.set_footer(text=footer or "‎", icon_url=footer_icon or None)
    fields = data.get("fields") if isinstance(data.get("fields"), list) else []
    for field in fields[:25]:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "‎")[:256]
        value = str(field.get("value") or "‎")[:1024]
        embed.add_field(name=name, value=value, inline=bool(field.get("inline")))
    if len(embed) > 6000:
        raise CustomMessageValidationError("Total isi embed melebihi batas Discord 6000 karakter.")
    return embed


def build_legacy_embeds(payload: dict[str, Any]) -> list[discord.Embed]:
    data = parse_payload(payload)["legacy"]
    additional = data.get("embeds") if isinstance(data.get("embeds"), list) else []
    embed_data = [data, *(item for item in additional if isinstance(item, dict))]
    embeds = [_build_legacy_embed(item) for item in embed_data[:10]]
    if sum(len(embed) for embed in embeds) > 6000:
        raise CustomMessageValidationError(
            "Total isi seluruh embed melebihi batas Discord 6000 karakter."
        )
    return embeds


def build_legacy_embed(payload: dict[str, Any]) -> discord.Embed:
    return build_legacy_embeds(payload)[0]


def _build_link_buttons(buttons: Any) -> discord.ui.ActionRow | None:
    if not isinstance(buttons, list):
        return None
    items = []
    for data in buttons[:5]:
        if not isinstance(data, dict) or not str(data.get("url") or "").startswith(("http://", "https://")):
            continue
        items.append(
            discord.ui.Button(
                label=str(data.get("label") or "Open")[:80],
                url=str(data["url"]),
                emoji=str(data.get("emoji") or "") or None,
            )
        )
    return discord.ui.ActionRow(*items) if items else None


def _component_file_specs(payload: dict[str, Any]) -> list[tuple[int, str, str, bool]]:
    components = parse_payload(payload)["v2"].get("components")
    if not isinstance(components, list):
        return []
    specs = []
    for index, component in enumerate(components[:10]):
        if not isinstance(component, dict) or str(component.get("type") or "").lower() != "file":
            continue
        url = str(component.get("url") or "").strip()
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in FILE_HOSTS
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 443}
            or parsed.fragment
        ):
            raise CustomMessageValidationError(
                "File V2 harus memakai URL attachment Discord dari cdn.discordapp.com "
                "atau media.discordapp.net."
            )
        source_name = unquote(parsed.path.rsplit("/", 1)[-1]) or f"file-{index + 1}"
        filename = SAFE_FILENAME.sub("_", source_name).strip("._")[:100] or f"file-{index + 1}"
        if "." not in filename:
            filename += ".bin"
        specs.append((index, url, f"{index + 1}-{filename}", bool(component.get("spoiler"))))
    return specs


def build_v2_view(
    payload: dict[str, Any],
    *,
    component_files: dict[int, discord.File] | None = None,
) -> discord.ui.LayoutView:
    data = parse_payload(payload)["v2"]
    file_specs = {index: (url, filename, spoiler) for index, url, filename, spoiler in _component_file_specs(payload)}
    children: list[discord.ui.Item] = []
    components = data.get("components") if isinstance(data.get("components"), list) else []
    for index, component in enumerate(components):
        if len(children) >= 10:
            break
        if not isinstance(component, dict):
            continue
        component_type = str(component.get("type") or "text").lower()
        if component_type == "text":
            content = str(component.get("content") or "")[:4000]
            if content:
                children.append(discord.ui.TextDisplay(content))
        elif component_type == "separator":
            spacing = discord.SeparatorSpacing.large if component.get("spacing") == "large" else discord.SeparatorSpacing.small
            children.append(discord.ui.Separator(visible=bool(component.get("visible", True)), spacing=spacing))
        elif component_type == "media":
            urls = component.get("urls") if isinstance(component.get("urls"), list) else [component.get("url")]
            gallery = discord.ui.MediaGallery()
            for url in urls[:10]:
                if str(url or "").startswith(("http://", "https://")):
                    gallery.add_item(media=str(url), description=str(component.get("description") or "") or None)
            if gallery.items:
                children.append(gallery)
        elif component_type == "section":
            content = str(component.get("content") or "")[:4000]
            thumbnail = str(component.get("thumbnail_url") or "")
            button_url = str(component.get("button_url") or "")
            if thumbnail.startswith(("http://", "https://")):
                accessory = discord.ui.Thumbnail(thumbnail, description=str(component.get("description") or "") or None)
            elif button_url.startswith(("http://", "https://")):
                accessory = discord.ui.Button(label=str(component.get("button_label") or "Open")[:80], url=button_url)
            else:
                continue
            children.append(discord.ui.Section(discord.ui.TextDisplay(content or "‎"), accessory=accessory))
        elif component_type == "buttons":
            row = _build_link_buttons(component.get("items"))
            if row:
                children.append(row)
        elif component_type == "file" and index in file_specs:
            _, filename, spoiler = file_specs[index]
            media = component_files.get(index) if component_files else None
            children.append(discord.ui.File(media or f"attachment://{filename}", spoiler=spoiler))
    if not children:
        children.append(discord.ui.TextDisplay("‎"))
    accent = parse_color(data.get("accent_color"))
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(*children, accent_color=accent, spoiler=bool(data.get("spoiler"))))
    return view


async def prepare_v2_message(payload: dict[str, Any]) -> tuple[discord.ui.LayoutView, list[discord.File]]:
    specs = _component_file_specs(payload)
    if not specs:
        return build_v2_view(payload), []
    component_files: dict[int, discord.File] = {}
    timeout = aiohttp.ClientTimeout(total=30, connect=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for index, url, filename, spoiler in specs:
            try:
                async with session.get(url, allow_redirects=False) as response:
                    if response.status != 200:
                        raise CustomMessageValidationError(
                            f"File `{filename}` gagal diunduh dari Discord (HTTP {response.status})."
                        )
                    declared_size = response.content_length
                    if declared_size and declared_size > MAX_COMPONENT_FILE_BYTES:
                        raise CustomMessageValidationError(f"File `{filename}` melebihi batas 10 MB.")
                    content = bytearray()
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        content.extend(chunk)
                        if len(content) > MAX_COMPONENT_FILE_BYTES:
                            raise CustomMessageValidationError(f"File `{filename}` melebihi batas 10 MB.")
            except (aiohttp.ClientError, TimeoutError) as exc:
                raise CustomMessageValidationError(f"File `{filename}` tidak dapat diunduh.") from exc
            component_files[index] = discord.File(io.BytesIO(content), filename=filename, spoiler=spoiler)
    files = list(component_files.values())
    return build_v2_view(payload, component_files=component_files), files


def message_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = parse_payload(payload)
    kwargs: dict[str, Any] = {}
    username = str(normalized.get("username") or "")[:80]
    avatar_url = str(normalized.get("avatar_url") or "")
    if username:
        kwargs["username"] = username
    if avatar_url.startswith(("http://", "https://")):
        kwargs["avatar_url"] = avatar_url
    return kwargs


async def send_custom_message(
    webhook: discord.Webhook,
    *,
    mode: str,
    payload: dict[str, Any],
    wait: bool = True,
) -> list[discord.WebhookMessage | None]:
    selected_mode = normalize_mode(mode)
    normalized = parse_payload(payload)
    identity = message_kwargs(normalized)
    results = []
    if selected_mode in {"legacy", "both"}:
        content = str(normalized.get("content") or "")[:2000] or None
        results.append(
            await webhook.send(
                content=content,
                embeds=build_legacy_embeds(normalized),
                wait=wait,
                **identity,
            )
        )
    if selected_mode in {"v2", "both"}:
        view, files = await prepare_v2_message(normalized)
        results.append(await webhook.send(view=view, files=files, wait=wait, **identity))
    return results
