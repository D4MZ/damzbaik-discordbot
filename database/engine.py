"""
Inisialisasi async engine & session factory SQLAlchemy.

Modul ini dipisah dari models.py agar tidak terjadi circular import,
dan dipisah dari config.py agar mudah di-mock saat testing.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, func, insert, inspect, literal, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from database.models import Base, InviteStat, PaymentMethod, UserPaymentMethod

# Pastikan folder data/ ada sebelum SQLite mencoba membuat file database
if settings.database_url.startswith("sqlite"):
    Path("data").mkdir(parents=True, exist_ok=True)

engine = create_async_engine(settings.database_url, echo=False, future=True)

async_session_factory = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def init_db() -> None:
    """Membuat seluruh tabel jika belum ada. Dipanggil sekali saat startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all does not add columns to an existing SQLite table.
        if settings.database_url.startswith("sqlite"):
            existing = await conn.run_sync(
                lambda sync_conn: {column["name"] for column in inspect(sync_conn).get_columns("guild_config")}
            )
            additions = {
                "boost_enabled": "BOOLEAN NOT NULL DEFAULT 0",
                "boost_channel_id": "BIGINT",
                "boost_message": "TEXT NOT NULL DEFAULT 'Terima kasih {user} sudah boost {server}! 💜'",
                "boost_title": "TEXT",
                "boost_image": "TEXT",
                "boost_footer": "TEXT",
                "leave_enabled": "BOOLEAN NOT NULL DEFAULT 0",
                "leave_channel_id": "BIGINT",
                "leave_type": "VARCHAR(16) NOT NULL DEFAULT 'text'",
                "leave_message": "TEXT NOT NULL DEFAULT '{username} telah meninggalkan {server}.'",
                "leave_embed_title": "TEXT",
                "leave_embed_description": "TEXT",
                "leave_embed_color": "VARCHAR(7) NOT NULL DEFAULT '#5865F2'",
                "leave_embed_footer": "TEXT",
                "leave_embed_thumbnail": "TEXT",
                "leave_embed_image": "TEXT",
                "leave_embed_author": "TEXT",
                "leave_timestamp": "BOOLEAN NOT NULL DEFAULT 1",
                "leave_mention": "BOOLEAN NOT NULL DEFAULT 0",
            }
            for name, definition in additions.items():
                if name not in existing:
                    await conn.execute(text(f"ALTER TABLE guild_config ADD COLUMN {name} {definition}"))
        await conn.execute(
            update(InviteStat)
            .where(
                (InviteStat.joins.is_(None))
                | (InviteStat.leaves.is_(None))
                | (InviteStat.fake.is_(None))
            )
            .values(
                joins=func.coalesce(InviteStat.joins, 0),
                leaves=func.coalesce(InviteStat.leaves, 0),
                fake=func.coalesce(InviteStat.fake, 0),
            )
        )
        user_payment_count = await conn.scalar(
            select(func.count()).select_from(UserPaymentMethod)
        )
        if user_payment_count == 0:
            await conn.execute(
                insert(UserPaymentMethod).from_select(
                    [
                        "guild_id",
                        "owner_id",
                        "name",
                        "payment_text",
                        "qr_image_location",
                        "qr_image_filename",
                        "created_at",
                        "updated_at",
                    ],
                    select(
                        PaymentMethod.guild_id,
                        literal(0),
                        PaymentMethod.name,
                        PaymentMethod.payment_text,
                        PaymentMethod.qr_image_location,
                        PaymentMethod.qr_image_filename,
                        PaymentMethod.created_at,
                        PaymentMethod.updated_at,
                    ),
                )
            )
            await conn.execute(delete(PaymentMethod))


def get_session() -> AsyncSession:
    return async_session_factory()
