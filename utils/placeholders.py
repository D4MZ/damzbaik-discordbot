"""
Resolver placeholder teks, dipakai oleh welcome system dan announcement.

Placeholder yang didukung: {user} {username} {displayname} {userid}
{server} {membercount}
"""

from __future__ import annotations

import discord


def resolve_member_placeholders(text: str, member: discord.Member) -> str:
    guild = member.guild
    replacements = {
        "{user}": member.mention,
        "{username}": member.name,
        "{displayname}": member.display_name,
        "{userid}": str(member.id),
        "{server}": guild.name if guild else "",
        "{membercount}": str(guild.member_count) if guild else "0",
    }
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    return text

