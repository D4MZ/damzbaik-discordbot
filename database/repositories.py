"""
Repository layer: kumpulan fungsi query/CRUD yang dipakai oleh cogs.

Memisahkan logika database dari logika Discord (cogs) membuat kode lebih
mudah di-maintain dan di-test, serta memudahkan migrasi database di masa depan.
"""

from __future__ import annotations

from sqlalchemy import delete, func, select, update

from database.engine import get_session
from database.models import (
    AntiNukeConfig,
    GuildConfig,
    CustomMessageDraft,
    ImageAsset,
    InviteJoinLog,
    InviteStat,
    ManagedInvite,
    PaymentConfig,
    PrefixCommand,
    UserPaymentMethod,
    ReactionRole,
    RoleDropdown,
    WorkerStatus,
    WorkerStatusPanel,
    Review,
    utcnow,
)


# ---------------------------------------------------------------------------
# Guild Config
# ---------------------------------------------------------------------------
async def get_or_create_guild_config(guild_id: int) -> GuildConfig:
    async with get_session() as session:
        result = await session.execute(
            select(GuildConfig).where(GuildConfig.guild_id == guild_id)
        )
        config = result.scalar_one_or_none()
        if config is None:
            config = GuildConfig(guild_id=guild_id)
            session.add(config)
            await session.commit()
            await session.refresh(config)
        return config


async def update_guild_config(guild_id: int, **fields) -> GuildConfig:
    async with get_session() as session:
        result = await session.execute(
            select(GuildConfig).where(GuildConfig.guild_id == guild_id)
        )
        config = result.scalar_one_or_none()
        if config is None:
            config = GuildConfig(guild_id=guild_id)
            session.add(config)
        for key, value in fields.items():
            setattr(config, key, value)
        config.updated_at = utcnow()
        await session.commit()
        await session.refresh(config)
        return config


async def get_all_guild_configs() -> list[GuildConfig]:
    async with get_session() as session:
        result = await session.execute(select(GuildConfig))
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Worker status panel
# ---------------------------------------------------------------------------
async def get_worker_status_panel(guild_id: int) -> WorkerStatusPanel | None:
    async with get_session() as session:
        return await session.get(WorkerStatusPanel, guild_id)


async def upsert_worker_status_panel(guild_id: int, **fields) -> WorkerStatusPanel:
    async with get_session() as session:
        panel = await session.get(WorkerStatusPanel, guild_id)
        if panel is None:
            panel = WorkerStatusPanel(guild_id=guild_id, **fields)
            session.add(panel)
        else:
            for key, value in fields.items():
                setattr(panel, key, value)
            panel.updated_at = utcnow()
        await session.commit()
        await session.refresh(panel)
        return panel


async def list_worker_statuses(guild_id: int) -> list[WorkerStatus]:
    async with get_session() as session:
        result = await session.execute(
            select(WorkerStatus)
            .where(WorkerStatus.guild_id == guild_id)
            .order_by(WorkerStatus.id)
        )
        return list(result.scalars().all())


async def get_worker_status(guild_id: int, member_id: int) -> WorkerStatus | None:
    async with get_session() as session:
        result = await session.execute(
            select(WorkerStatus).where(
                WorkerStatus.guild_id == guild_id,
                WorkerStatus.member_id == member_id,
            )
        )
        return result.scalar_one_or_none()


async def add_worker_status(guild_id: int, member_id: int, label: str) -> WorkerStatus:
    async with get_session() as session:
        worker = WorkerStatus(guild_id=guild_id, member_id=member_id, label=label)
        session.add(worker)
        await session.commit()
        await session.refresh(worker)
        return worker


async def delete_worker_status(guild_id: int, member_id: int) -> bool:
    async with get_session() as session:
        result = await session.execute(
            delete(WorkerStatus).where(
                WorkerStatus.guild_id == guild_id,
                WorkerStatus.member_id == member_id,
            )
        )
        await session.commit()
        return result.rowcount > 0


async def update_worker_status(guild_id: int, member_id: int, *, available: bool) -> WorkerStatus | None:
    async with get_session() as session:
        result = await session.execute(
            select(WorkerStatus).where(
                WorkerStatus.guild_id == guild_id,
                WorkerStatus.member_id == member_id,
            )
        )
        worker = result.scalar_one_or_none()
        if worker is None:
            return None
        worker.available = available
        worker.updated_at = utcnow()
        await session.commit()
        await session.refresh(worker)
        return worker


async def get_or_create_anti_nuke_config(guild_id: int) -> AntiNukeConfig:
    async with get_session() as session:
        config = await session.get(AntiNukeConfig, guild_id)
        if config is None:
            config = AntiNukeConfig(guild_id=guild_id)
            session.add(config)
            await session.commit()
            await session.refresh(config)
        return config


async def update_anti_nuke_config(guild_id: int, **fields) -> AntiNukeConfig:
    async with get_session() as session:
        config = await session.get(AntiNukeConfig, guild_id)
        if config is None:
            config = AntiNukeConfig(guild_id=guild_id)
            session.add(config)
        for key, value in fields.items():
            setattr(config, key, value)
        config.updated_at = utcnow()
        await session.commit()
        await session.refresh(config)
        return config


async def get_payment_config(guild_id: int) -> PaymentConfig | None:
    async with get_session() as session:
        result = await session.execute(
            select(PaymentConfig).where(PaymentConfig.guild_id == guild_id)
        )
        return result.scalar_one_or_none()


async def update_payment_config(guild_id: int, **fields) -> PaymentConfig:
    async with get_session() as session:
        result = await session.execute(
            select(PaymentConfig).where(PaymentConfig.guild_id == guild_id)
        )
        config = result.scalar_one_or_none()
        if config is None:
            config = PaymentConfig(guild_id=guild_id)
            session.add(config)
        for key, value in fields.items():
            setattr(config, key, value)
        config.updated_at = utcnow()
        await session.commit()
        await session.refresh(config)
        return config


async def add_payment_method(guild_id: int, owner_id: int, **fields) -> UserPaymentMethod:
    async with get_session() as session:
        method = UserPaymentMethod(guild_id=guild_id, owner_id=owner_id, **fields)
        session.add(method)
        await session.commit()
        await session.refresh(method)
        return method


async def list_payment_methods(
    guild_id: int,
    owner_id: int | None = None,
) -> list[UserPaymentMethod]:
    async with get_session() as session:
        query = select(UserPaymentMethod).where(UserPaymentMethod.guild_id == guild_id)
        if owner_id is not None:
            query = query.where(UserPaymentMethod.owner_id == owner_id)
        result = await session.execute(
            query.order_by(UserPaymentMethod.owner_id, UserPaymentMethod.name)
        )
        return list(result.scalars().all())


async def get_payment_method(
    guild_id: int,
    owner_id: int,
    name: str,
) -> UserPaymentMethod | None:
    async with get_session() as session:
        result = await session.execute(
            select(UserPaymentMethod).where(
                UserPaymentMethod.guild_id == guild_id,
                UserPaymentMethod.owner_id == owner_id,
                UserPaymentMethod.name == name,
            )
        )
        return result.scalar_one_or_none()


async def update_payment_method(
    guild_id: int,
    owner_id: int,
    name: str,
    **fields,
) -> UserPaymentMethod | None:
    async with get_session() as session:
        result = await session.execute(
            select(UserPaymentMethod).where(
                UserPaymentMethod.guild_id == guild_id,
                UserPaymentMethod.owner_id == owner_id,
                UserPaymentMethod.name == name,
            )
        )
        method = result.scalar_one_or_none()
        if method is None:
            return None
        for key, value in fields.items():
            setattr(method, key, value)
        method.updated_at = utcnow()
        await session.commit()
        await session.refresh(method)
        return method


async def delete_payment_method(
    guild_id: int,
    owner_id: int,
    name: str,
) -> UserPaymentMethod | None:
    async with get_session() as session:
        result = await session.execute(
            select(UserPaymentMethod).where(
                UserPaymentMethod.guild_id == guild_id,
                UserPaymentMethod.owner_id == owner_id,
                UserPaymentMethod.name == name,
            )
        )
        method = result.scalar_one_or_none()
        if method is None:
            return None
        await session.delete(method)
        await session.commit()
        return method


# ---------------------------------------------------------------------------
# Invite system
# ---------------------------------------------------------------------------
async def create_managed_invite(**fields) -> ManagedInvite:
    async with get_session() as session:
        invite = ManagedInvite(**fields)
        session.add(invite)
        await session.commit()
        await session.refresh(invite)
        return invite


async def list_managed_invites(guild_id: int) -> list[ManagedInvite]:
    async with get_session() as session:
        result = await session.execute(
            select(ManagedInvite).where(ManagedInvite.guild_id == guild_id)
        )
        return list(result.scalars().all())


async def get_managed_invite(code: str) -> ManagedInvite | None:
    async with get_session() as session:
        result = await session.execute(
            select(ManagedInvite).where(ManagedInvite.code == code)
        )
        return result.scalar_one_or_none()


async def delete_managed_invite(code: str) -> bool:
    async with get_session() as session:
        result = await session.execute(
            delete(ManagedInvite).where(ManagedInvite.code == code)
        )
        await session.commit()
        return result.rowcount > 0


async def record_invite_join(
    guild_id: int, member_id: int, inviter_id: int | None, code: str | None, is_fake: bool
) -> None:
    async with get_session() as session:
        session.add(
            InviteJoinLog(
                guild_id=guild_id,
                member_id=member_id,
                inviter_id=inviter_id,
                code=code,
                is_fake=is_fake,
            )
        )
        if inviter_id is not None:
            result = await session.execute(
                select(InviteStat).where(
                    InviteStat.guild_id == guild_id, InviteStat.inviter_id == inviter_id
                )
            )
            stat = result.scalar_one_or_none()
            if stat is None:
                stat = InviteStat(
                    guild_id=guild_id,
                    inviter_id=inviter_id,
                    joins=0,
                    leaves=0,
                    fake=0,
                )
                session.add(stat)
            if is_fake:
                stat.fake = (stat.fake or 0) + 1
            else:
                stat.joins = (stat.joins or 0) + 1
        await session.commit()


async def record_invite_leave(guild_id: int, member_id: int) -> None:
    async with get_session() as session:
        result = await session.execute(
            select(InviteJoinLog)
            .where(InviteJoinLog.guild_id == guild_id, InviteJoinLog.member_id == member_id)
            .order_by(InviteJoinLog.joined_at.desc())
        )
        log_entry = result.scalars().first()
        if log_entry is None:
            return
        log_entry.left_at = utcnow()
        if log_entry.inviter_id is not None:
            stat_result = await session.execute(
                select(InviteStat).where(
                    InviteStat.guild_id == guild_id,
                    InviteStat.inviter_id == log_entry.inviter_id,
                )
            )
            stat = stat_result.scalar_one_or_none()
            if stat is not None:
                stat.leaves = (stat.leaves or 0) + 1
        await session.commit()


async def get_invite_leaderboard(guild_id: int, limit: int = 10) -> list[InviteStat]:
    async with get_session() as session:
        result = await session.execute(
            select(InviteStat)
            .where(InviteStat.guild_id == guild_id)
            .order_by(
                (
                    func.coalesce(InviteStat.joins, 0)
                    - func.coalesce(InviteStat.leaves, 0)
                    - func.coalesce(InviteStat.fake, 0)
                ).desc()
            )
            .limit(limit)
        )
        return list(result.scalars().all())


async def get_invite_stat(guild_id: int, inviter_id: int) -> InviteStat | None:
    async with get_session() as session:
        result = await session.execute(
            select(InviteStat).where(
                InviteStat.guild_id == guild_id, InviteStat.inviter_id == inviter_id
            )
        )
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Role dropdown & reaction role
# ---------------------------------------------------------------------------
async def create_role_dropdown(**fields) -> RoleDropdown:
    async with get_session() as session:
        obj = RoleDropdown(**fields)
        session.add(obj)
        await session.commit()
        await session.refresh(obj)
        return obj


async def set_role_dropdown_message(dropdown_id: int, message_id: int) -> None:
    async with get_session() as session:
        await session.execute(
            update(RoleDropdown)
            .where(RoleDropdown.id == dropdown_id)
            .values(message_id=message_id)
        )
        await session.commit()


async def update_role_dropdown(dropdown_id: int, **fields) -> RoleDropdown | None:
    async with get_session() as session:
        result = await session.execute(
            select(RoleDropdown).where(RoleDropdown.id == dropdown_id)
        )
        dropdown = result.scalar_one_or_none()
        if dropdown is None:
            return None
        for key, value in fields.items():
            setattr(dropdown, key, value)
        await session.commit()
        await session.refresh(dropdown)
        return dropdown


async def get_role_dropdown(dropdown_id: int) -> RoleDropdown | None:
    async with get_session() as session:
        result = await session.execute(
            select(RoleDropdown).where(RoleDropdown.id == dropdown_id)
        )
        return result.scalar_one_or_none()


async def get_role_dropdown_by_message(message_id: int) -> RoleDropdown | None:
    async with get_session() as session:
        result = await session.execute(
            select(RoleDropdown).where(RoleDropdown.message_id == message_id)
        )
        return result.scalar_one_or_none()


async def list_role_dropdowns(guild_id: int) -> list[RoleDropdown]:
    async with get_session() as session:
        result = await session.execute(
            select(RoleDropdown).where(RoleDropdown.guild_id == guild_id)
        )
        return list(result.scalars().all())


async def delete_role_dropdown(dropdown_id: int) -> bool:
    async with get_session() as session:
        result = await session.execute(
            delete(RoleDropdown).where(RoleDropdown.id == dropdown_id)
        )
        await session.commit()
        return result.rowcount > 0


async def list_all_role_dropdowns() -> list[RoleDropdown]:
    async with get_session() as session:
        result = await session.execute(select(RoleDropdown))
        return list(result.scalars().all())


async def add_reaction_role(**fields) -> ReactionRole:
    async with get_session() as session:
        obj = ReactionRole(**fields)
        session.add(obj)
        await session.commit()
        await session.refresh(obj)
        return obj


async def get_reaction_role(message_id: int, emoji: str) -> ReactionRole | None:
    async with get_session() as session:
        result = await session.execute(
            select(ReactionRole).where(
                ReactionRole.message_id == message_id, ReactionRole.emoji == emoji
            )
        )
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Image assets
# ---------------------------------------------------------------------------
async def add_image_asset(**fields) -> ImageAsset:
    async with get_session() as session:
        obj = ImageAsset(**fields)
        session.add(obj)
        await session.commit()
        await session.refresh(obj)
        return obj


async def get_image_asset(guild_id: int, name: str) -> ImageAsset | None:
    async with get_session() as session:
        result = await session.execute(
            select(ImageAsset).where(
                ImageAsset.guild_id == guild_id, ImageAsset.name == name
            )
        )
        return result.scalar_one_or_none()


async def list_image_assets(guild_id: int, category: str | None = None) -> list[ImageAsset]:
    async with get_session() as session:
        query = select(ImageAsset).where(ImageAsset.guild_id == guild_id)
        if category:
            query = query.where(ImageAsset.category == category)
        result = await session.execute(query)
        return list(result.scalars().all())


async def delete_image_asset(guild_id: int, name: str) -> ImageAsset | None:
    async with get_session() as session:
        result = await session.execute(
            select(ImageAsset).where(
                ImageAsset.guild_id == guild_id, ImageAsset.name == name
            )
        )
        obj = result.scalar_one_or_none()
        if obj is not None:
            await session.delete(obj)
            await session.commit()
        return obj


# ---------------------------------------------------------------------------
# Custom message / webhook builder
# ---------------------------------------------------------------------------
async def create_custom_message_draft(**fields) -> CustomMessageDraft:
    async with get_session() as session:
        draft = CustomMessageDraft(**fields)
        session.add(draft)
        await session.commit()
        await session.refresh(draft)
        return draft


async def get_custom_message_draft(draft_id: int, guild_id: int) -> CustomMessageDraft | None:
    async with get_session() as session:
        result = await session.execute(
            select(CustomMessageDraft).where(
                CustomMessageDraft.id == draft_id,
                CustomMessageDraft.guild_id == guild_id,
            )
        )
        return result.scalar_one_or_none()


async def get_custom_message_draft_by_token(token: str) -> CustomMessageDraft | None:
    async with get_session() as session:
        result = await session.execute(
            select(CustomMessageDraft).where(CustomMessageDraft.editor_token == token)
        )
        return result.scalar_one_or_none()


async def list_custom_message_drafts(guild_id: int) -> list[CustomMessageDraft]:
    async with get_session() as session:
        result = await session.execute(
            select(CustomMessageDraft)
            .where(CustomMessageDraft.guild_id == guild_id)
            .order_by(CustomMessageDraft.updated_at.desc())
        )
        return list(result.scalars().all())


async def update_custom_message_draft(draft_id: int, guild_id: int, **fields) -> CustomMessageDraft | None:
    async with get_session() as session:
        result = await session.execute(
            select(CustomMessageDraft).where(
                CustomMessageDraft.id == draft_id,
                CustomMessageDraft.guild_id == guild_id,
            )
        )
        draft = result.scalar_one_or_none()
        if draft is None:
            return None
        for key, value in fields.items():
            setattr(draft, key, value)
        draft.updated_at = utcnow()
        await session.commit()
        await session.refresh(draft)
        return draft


async def update_custom_message_draft_by_token(token: str, **fields) -> CustomMessageDraft | None:
    async with get_session() as session:
        result = await session.execute(
            select(CustomMessageDraft).where(CustomMessageDraft.editor_token == token)
        )
        draft = result.scalar_one_or_none()
        if draft is None:
            return None
        for key, value in fields.items():
            setattr(draft, key, value)
        draft.updated_at = utcnow()
        await session.commit()
        await session.refresh(draft)
        return draft


async def delete_custom_message_draft(draft_id: int, guild_id: int) -> bool:
    async with get_session() as session:
        result = await session.execute(
            delete(CustomMessageDraft).where(
                CustomMessageDraft.id == draft_id,
                CustomMessageDraft.guild_id == guild_id,
            )
        )
        await session.commit()
        return bool(result.rowcount)


async def add_review(**fields) -> Review:
    async with get_session() as session:
        review = Review(**fields)
        session.add(review)
        await session.commit()
        await session.refresh(review)
        return review


# ---------------------------------------------------------------------------
# Custom prefix commands
# ---------------------------------------------------------------------------
async def add_prefix_command(**fields) -> PrefixCommand:
    async with get_session() as session:
        command = PrefixCommand(**fields)
        session.add(command)
        await session.commit()
        await session.refresh(command)
        return command


async def get_prefix_command(guild_id: int, name: str) -> PrefixCommand | None:
    async with get_session() as session:
        result = await session.execute(
            select(PrefixCommand).where(PrefixCommand.guild_id == guild_id, PrefixCommand.name == name)
        )
        return result.scalar_one_or_none()


async def list_prefix_commands(guild_id: int) -> list[PrefixCommand]:
    async with get_session() as session:
        result = await session.execute(
            select(PrefixCommand).where(PrefixCommand.guild_id == guild_id).order_by(PrefixCommand.name)
        )
        return list(result.scalars().all())


async def update_prefix_command(guild_id: int, name: str, **fields) -> PrefixCommand | None:
    async with get_session() as session:
        result = await session.execute(
            select(PrefixCommand).where(PrefixCommand.guild_id == guild_id, PrefixCommand.name == name)
        )
        command = result.scalar_one_or_none()
        if command is None:
            return None
        for key, value in fields.items():
            setattr(command, key, value)
        await session.commit()
        await session.refresh(command)
        return command


async def delete_prefix_command(guild_id: int, name: str) -> bool:
    async with get_session() as session:
        result = await session.execute(
            delete(PrefixCommand).where(PrefixCommand.guild_id == guild_id, PrefixCommand.name == name)
        )
        await session.commit()
        return bool(result.rowcount)
