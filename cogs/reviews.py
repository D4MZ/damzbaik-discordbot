"""Panel review untuk jasa FiveM."""

from __future__ import annotations

from typing import Optional
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from database import repositories as repo
from utils.embeds import error_embed, success_embed
from utils.permissions import require_permissions

SERVICE_CHOICES = {
    "video": "Video Editing FiveM",
    "model": "3D Model FiveM",
    "handling": "Handling Editor FiveM",
}


class ReviewModal(discord.ui.Modal, title="Submit a Review"):
    service = discord.ui.TextInput(
        label="Service",
        placeholder="video / 3d model / handling",
        max_length=20,
    )
    rating = discord.ui.TextInput(
        label="Rating (1-5)",
        placeholder="5",
        max_length=1,
    )
    content = discord.ui.TextInput(
        label="Review",
        style=discord.TextStyle.paragraph,
        placeholder="Tell us about your experience...",
        max_length=1000,
    )

    def __init__(self, target_channel: discord.TextChannel):
        super().__init__()
        self.target_channel = target_channel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        service_key = str(self.service.value).strip().lower()
        service_name = SERVICE_CHOICES.get(service_key)
        try:
            rating = int(str(self.rating.value).strip())
        except ValueError:
            rating = 0

        if service_name is None or not 1 <= rating <= 5:
            await interaction.response.send_message(
                embed=error_embed(
                    "Data Review Tidak Valid",
                    "Jasa harus `video`, `model`, atau `handling`, dan rating harus 1 sampai 5.",
                ),
                ephemeral=True,
            )
            return

        review = await repo.add_review(
            guild_id=interaction.guild_id,
            reviewer_id=interaction.user.id,
            service_type=service_key,
            rating=rating,
            content=str(self.content.value).strip(),
        )
        try:
            await self.target_channel.send(
                view=build_review_view(
                    interaction.user,
                    service_name,
                    review.content,
                    rating,
                    review.created_at,
                )
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=error_embed("Gagal Mengirim Review", "Bot tidak memiliki izin mengirim pesan ke channel review."),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=success_embed("Review Terkirim", "Terima kasih sudah memberikan review!"),
            ephemeral=True,
        )


class SubmitReviewButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="Submit a Review",
            style=discord.ButtonStyle.primary,
            custom_id="reviews:submit",
            emoji="📝",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        channel = interaction.guild.get_channel(interaction.channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Channel review tidak ditemukan.", ephemeral=True)
            return
        await interaction.response.send_modal(ReviewModal(channel))


class ReviewView(discord.ui.LayoutView):
    def __init__(self, *, panel: bool = False):
        super().__init__(timeout=None)
        if panel:
            self.add_item(
                discord.ui.Container(
                    discord.ui.TextDisplay(
                        "**⭐ Customer Review**\n\n"
                        "Have you used our services?\n"
                        "Share your experience with **Video Editing FiveM**, "
                        "**3D Model FiveM**, or **Handling Editor FiveM**."
                    ),
                    discord.ui.ActionRow(SubmitReviewButton()),
                )
            )
        else:
            self.add_item(discord.ui.ActionRow(SubmitReviewButton()))


def build_review_view(
    user: discord.abc.User,
    service_name: str,
    content: str,
    rating: int,
    reviewed_at,
) -> ReviewView:
    reviewed_at = reviewed_at.replace(tzinfo=ZoneInfo("UTC")) if reviewed_at.tzinfo is None else reviewed_at
    jakarta_time = reviewed_at.astimezone(ZoneInfo("Asia/Jakarta"))
    reviewed_label = jakarta_time.strftime("%d/%m/%Y %H:%M WIB").lstrip("0")
    stars = "⭐" * rating
    view = ReviewView()
    view.clear_items()
    view.add_item(
        discord.ui.Container(
            discord.ui.TextDisplay(f"**New Review From <@{user.id}>**"),
        )
    )
    view.add_item(
        discord.ui.Container(
            discord.ui.Section(
                discord.ui.TextDisplay(
                    f"**Jasa:** {service_name}\n\n"
                    f"> {content}\n\n"
                    f"**Rating:** {stars} ({rating}/5)\n"
                    f"**Reviewed:** {reviewed_label}"
                ),
                accessory=discord.ui.Thumbnail(
                    user.display_avatar.url,
                    description=f"Profile {user.display_name}",
                ),
            )
        )
    )
    view.add_item(
        discord.ui.Container(
            discord.ui.TextDisplay(
                "Thank you for trusting us to assist you, and for your review."
            ),
            discord.ui.ActionRow(SubmitReviewButton()),
        )
    )
    return view


review_group = app_commands.Group(name="review", description="Kelola panel review jasa FiveM.")


async def send_review_panel(target: discord.TextChannel) -> None:
    await target.send(view=ReviewView(panel=True))


@review_group.command(name="setup", description="Buat panel review jasa FiveM di channel ini atau channel pilihan.")
@app_commands.guild_only()
@app_commands.describe(channel="Channel untuk panel dan review (opsional)")
@require_permissions(manage_guild=True)
async def review_setup(
    interaction: discord.Interaction,
    channel: Optional[discord.TextChannel] = None,
) -> None:
    target = channel or interaction.channel
    if not isinstance(target, discord.TextChannel):
        await interaction.response.send_message("Gunakan command ini di text channel.", ephemeral=True)
        return
    await send_review_panel(target)
    await interaction.response.send_message(
        embed=success_embed("Panel Review Dibuat", f"Panel berhasil dikirim ke {target.mention}."),
        ephemeral=True,
    )


class Reviews(commands.Cog, name="Reviews"):
    @commands.command(name="review", aliases=("reviews",), help="!review setup [#channel]")
    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    async def legacy_review(self, ctx: commands.Context, action: str = "setup") -> None:
        if action.lower() != "setup":
            await ctx.send("Gunakan: `!review setup [#channel]`", delete_after=10)
            return
        target = ctx.channel
        if ctx.message.channel_mentions:
            target = ctx.message.channel_mentions[0]
        if not isinstance(target, discord.TextChannel):
            await ctx.send("Command ini hanya bisa digunakan di text channel.", delete_after=10)
            return
        await send_review_panel(target)
        await ctx.send(f"✅ Panel review dibuat di {target.mention}.", delete_after=10)


async def setup(bot: commands.Bot) -> None:
    bot.tree.add_command(review_group)
    bot.add_view(ReviewView())
    await bot.add_cog(Reviews(bot))
