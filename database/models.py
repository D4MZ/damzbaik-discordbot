"""
Definisi model database menggunakan SQLAlchemy 2.0 (async, declarative style).

Desain ini sengaja dibuat portable: tidak menggunakan fitur spesifik SQLite,
sehingga project dapat dipindahkan ke PostgreSQL atau MySQL hanya dengan
mengganti DATABASE_URL di .env (lihat README bagian "Migrasi Database").
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ---------------------------------------------------------------------------
# Konfigurasi per-guild
# ---------------------------------------------------------------------------
class GuildConfig(Base):
    __tablename__ = "guild_config"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # Welcome system
    welcome_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    welcome_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    welcome_type: Mapped[str] = mapped_column(String(16), default="text")  # "text" | "embed"
    welcome_message: Mapped[str] = mapped_column(
        Text, default="Welcome {user} to {server}!"
    )
    welcome_embed_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcome_embed_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcome_embed_color: Mapped[str] = mapped_column(String(7), default="#5865F2")
    welcome_embed_footer: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcome_embed_thumbnail: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcome_embed_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcome_embed_author: Mapped[str | None] = mapped_column(Text, nullable=True)
    welcome_timestamp: Mapped[bool] = mapped_column(Boolean, default=True)
    welcome_mention: Mapped[bool] = mapped_column(Boolean, default=True)

    # Leave system (struktur sama dengan welcome)
    leave_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    leave_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    leave_type: Mapped[str] = mapped_column(String(16), default="text")  # "text" | "embed"
    leave_message: Mapped[str] = mapped_column(Text, default="{username} telah meninggalkan {server}.")
    leave_embed_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    leave_embed_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    leave_embed_color: Mapped[str] = mapped_column(String(7), default="#5865F2")
    leave_embed_footer: Mapped[str | None] = mapped_column(Text, nullable=True)
    leave_embed_thumbnail: Mapped[str | None] = mapped_column(Text, nullable=True)
    leave_embed_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    leave_embed_author: Mapped[str | None] = mapped_column(Text, nullable=True)
    leave_timestamp: Mapped[bool] = mapped_column(Boolean, default=True)
    # Member yang keluar sering tampil sebagai @unknown-user, jadi default tanpa mention.
    leave_mention: Mapped[bool] = mapped_column(Boolean, default=False)

    # Server boost message
    boost_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    boost_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    boost_message: Mapped[str] = mapped_column(
        Text,
        default="Terima kasih {user} sudah boost {server}! 💜",
    )
    boost_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    boost_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    boost_footer: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Logging channels (per kategori log)
    message_log_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    voice_log_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    member_log_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Autorole
    autorole_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    autorole_role_ids: Mapped[str] = mapped_column(Text, default="")  # comma-separated

    # Bot status (opsional, override default)
    status_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PaymentConfig(Base):
    __tablename__ = "payment_config"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    payment_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_image_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_image_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PaymentMethod(Base):
    __tablename__ = "payment_method"
    __table_args__ = (UniqueConstraint("guild_id", "name", name="uq_payment_method_guild_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(100))
    payment_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_image_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_image_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class UserPaymentMethod(Base):
    __tablename__ = "user_payment_method"
    __table_args__ = (
        UniqueConstraint(
            "guild_id",
            "owner_id",
            "name",
            name="uq_user_payment_method_owner_name",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(100))
    payment_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_image_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_image_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AntiNukeConfig(Base):
    __tablename__ = "anti_nuke_config"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    log_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    punishment: Mapped[str] = mapped_column(String(20), default="strip_roles")
    violation_limit: Mapped[int] = mapped_column(Integer, default=1)
    window_seconds: Mapped[int] = mapped_column(Integer, default=10)
    mention_limit: Mapped[int] = mapped_column(Integer, default=5)
    features_json: Mapped[str] = mapped_column(Text, default="{}")
    whitelist_json: Mapped[str] = mapped_column(Text, default="[]")
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# ---------------------------------------------------------------------------
# Invite system
# ---------------------------------------------------------------------------
class ManagedInvite(Base):
    """Invite yang dibuat lewat /invite create, untuk keperluan manajemen."""

    __tablename__ = "managed_invite"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    creator_id: Mapped[int] = mapped_column(BigInteger)
    max_age: Mapped[int] = mapped_column(Integer, default=0)
    max_uses: Mapped[int] = mapped_column(Integer, default=0)
    temporary: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InviteStat(Base):
    """Statistik agregat per-inviter, dipakai untuk leaderboard."""

    __tablename__ = "invite_stat"
    __table_args__ = (UniqueConstraint("guild_id", "inviter_id", name="uq_guild_inviter"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    inviter_id: Mapped[int] = mapped_column(BigInteger)
    joins: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    leaves: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    fake: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)


class InviteJoinLog(Base):
    """Catatan siapa masuk lewat kode invite siapa (untuk /invite user)."""

    __tablename__ = "invite_join_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    member_id: Mapped[int] = mapped_column(BigInteger)
    inviter_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    joined_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    left_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_fake: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------------------
# Role system (dropdown & reaction role)
# ---------------------------------------------------------------------------
class RoleDropdown(Base):
    __tablename__ = "role_dropdown"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    title: Mapped[str] = mapped_column(Text, default="Choose your roles")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # options_json: list[{"emoji": str|None, "label": str, "role_id": int, "description": str|None}]
    options_json: Mapped[str] = mapped_column(Text, default="[]")
    multi_select: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReactionRole(Base):
    __tablename__ = "reaction_role"
    __table_args__ = (
        UniqueConstraint("message_id", "emoji", name="uq_message_emoji"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger, index=True)
    emoji: Mapped[str] = mapped_column(String(64))
    role_id: Mapped[int] = mapped_column(BigInteger)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Image management
# ---------------------------------------------------------------------------
class ImageAsset(Base):
    __tablename__ = "image_asset"
    __table_args__ = (UniqueConstraint("guild_id", "name", name="uq_guild_image_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(100), default="general")
    storage_type: Mapped[str] = mapped_column(String(16), default="local")  # local|url|s3
    location: Mapped[str] = mapped_column(Text)  # path, url, atau object key
    uploaded_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------------------------------------------------------------------------
# Custom message / webhook builder
# ---------------------------------------------------------------------------
class CustomMessageDraft(Base):
    __tablename__ = "custom_message_draft"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(100))
    mode: Mapped[str] = mapped_column(String(16), default="legacy")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    editor_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class WorkerStatusPanel(Base):
    __tablename__ = "worker_status_panel"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    title: Mapped[str] = mapped_column(String(100), default="Worker Status")
    description: Mapped[str] = mapped_column(Text, default="Daftar status worker saat ini.")
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class WorkerStatus(Base):
    __tablename__ = "worker_status"
    __table_args__ = (
        UniqueConstraint("guild_id", "member_id", name="uq_worker_status_guild_member"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    member_id: Mapped[int] = mapped_column(BigInteger, index=True)
    label: Mapped[str] = mapped_column(String(100))
    available: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Review(Base):
    __tablename__ = "review"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    reviewer_id: Mapped[int] = mapped_column(BigInteger, index=True)
    service_type: Mapped[str] = mapped_column(String(40))
    rating: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PrefixCommand(Base):
    __tablename__ = "prefix_command"
    __table_args__ = (UniqueConstraint("guild_id", "name", name="uq_prefix_command_guild_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(32))
    response: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(String(100), nullable=True)
    creator_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
