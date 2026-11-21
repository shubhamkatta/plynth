"""Invite lifecycle: create (+ email) → preview → accept.

Tokens are random, single-use, stored as SHA-256 only. Every failure on the
public preview/accept path returns the SAME NotFound message so a caller can't
tell unknown from expired from used.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import Conflict, NotFound, ValidationFailed
from app.core.tenant import bypass_product, bypass_tenant, set_current_product, set_current_tenant
from app.models.invite import INVITE_KIND_JOIN_TENANT, INVITE_KIND_NEW_TENANT, InviteToken
from app.models.product import Product
from app.models.role import Role
from app.models.tenant import Tenant
from app.models.user import User
from app.providers import notifications
from app.services import audit
from app.services import auth as auth_svc
from app.services import user as user_svc

_INVALID = "invite is invalid or has expired"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def build_link(product: Product, raw_token: str) -> str:
    """Product's own app (`settings.app_url`) if set, else the hosted page."""
    app_url = (product.settings or {}).get("app_url")
    if app_url:
        return f"{str(app_url).rstrip('/')}/accept-invite?token={raw_token}"
    return f"{settings.public_base_url.rstrip('/')}/invite?token={raw_token}"


async def create_invite(
    db: AsyncSession,
    *,
    product_id: UUID,
    kind: str,
    tenant_id: UUID | None,
    email: str,
    full_name: str | None,
    role_codes: list[str],
    plan_code: str | None,
    actor_user_id: UUID | None,
    inviter_label: str,
    send_email: bool = True,
) -> tuple[InviteToken, str]:
    """Create the invite, revoke older pending ones for the same email, email
    the link (unless `send_email` is False). Returns (invite, link)."""
    email = email.lower()
    if kind == INVITE_KIND_JOIN_TENANT and tenant_id is None:
        raise ValidationFailed("join_tenant invites need a tenant")

    with bypass_product(), bypass_tenant():
        product = await db.get(Product, product_id)
        if product is None:
            raise NotFound("product not found")

        live_user = await db.scalar(
            select(User.id).where(
                User.product_id == product_id,
                User.email == email,
                User.deleted_at.is_(None),
                *([User.tenant_id == tenant_id] if kind == INVITE_KIND_JOIN_TENANT else []),
            )
        )
        if live_user is not None:
            raise Conflict(f"user with email {email!r} already exists")

        # Fail early on bad role codes rather than at accept time.
        for code in role_codes:
            exists = await db.scalar(
                select(Role.id).where(
                    Role.name == code, Role.product_id == product_id,
                    (Role.tenant_id == tenant_id) | (Role.tenant_id.is_(None)),
                )
            )
            if exists is None:
                raise NotFound(f"role {code!r} not found in this product")

        now = datetime.now(UTC)
        pending = (
            await db.scalars(
                select(InviteToken).where(
                    InviteToken.product_id == product_id,
                    InviteToken.email == email,
                    InviteToken.accepted_at.is_(None),
                    InviteToken.revoked_at.is_(None),
                )
            )
        ).all()
        for old in pending:
            old.revoked_at = now

        raw = secrets.token_urlsafe(32)
        invite = InviteToken(
            product_id=product_id, kind=kind, tenant_id=tenant_id, email=email,
            full_name=full_name, role_codes=role_codes or [], plan_code=plan_code,
            token_hash=_hash(raw),
            expires_at=now + timedelta(days=settings.invite_ttl_days),
            invited_by=actor_user_id,
        )
        db.add(invite)
        await db.flush()

        link = build_link(product, raw)
        await audit.record(
            db, action="invite.create", actor_user_id=actor_user_id,
            resource_type="invite", resource_id=invite.id,
            tenant_id=tenant_id, product_id=product_id,
            diff={"email": email, "kind": kind, "roles": role_codes,
                  "plan_code": plan_code, "emailed": send_email},
        )
        product_name = product.name

    if send_email:
        await notifications.send_email(
            to=email, template="invite",
            context={
                "name": full_name or email, "inviter": inviter_label,
                "product_name": product_name, "link": link,
                "expires_days": settings.invite_ttl_days,
            },
        )
    return invite, link


async def _load_valid(db: AsyncSession, raw: str, *, lock: bool = False) -> InviteToken:
    stmt = select(InviteToken).where(InviteToken.token_hash == _hash(raw))
    if lock:
        stmt = stmt.with_for_update()
    with bypass_product(), bypass_tenant():
        invite = await db.scalar(stmt)
    now = datetime.now(UTC)
    if (
        invite is None
        or invite.accepted_at is not None
        or invite.revoked_at is not None
        or invite.expires_at <= now
    ):
        raise NotFound(_INVALID)
    return invite


async def preview(db: AsyncSession, *, raw: str) -> tuple[InviteToken, str]:
    invite = await _load_valid(db, raw)
    with bypass_product(), bypass_tenant():
        name = await db.scalar(select(Product.name).where(Product.id == invite.product_id))
    return invite, name or ""


async def accept(
    db: AsyncSession,
    *,
    raw: str,
    password: str,
    full_name: str | None,
    user_agent: str | None,
    ip_address: str | None,
) -> tuple[str, str, datetime]:
    """Consume the invite, create the account, return (access, refresh, exp)."""
    invite = await _load_valid(db, raw, lock=True)  # row lock → single use
    name = full_name or invite.full_name

    with bypass_product(), bypass_tenant():
        tenant_slug: str | None
        if invite.kind == INVITE_KIND_NEW_TENANT:
            user, tenant = await auth_svc.register_individual(
                db, product_id=invite.product_id, email=invite.email,
                password=password, full_name=name,
            )
            tenant_slug = tenant.slug
        else:
            set_current_product(invite.product_id)
            assert invite.tenant_id is not None
            set_current_tenant(invite.tenant_id)
            user, _ = await user_svc.invite_user(
                db, product_id=invite.product_id, tenant_id=invite.tenant_id,
                email=invite.email, full_name=name,
                role_codes=list(invite.role_codes or []),
                actor_user_id=invite.invited_by, initial_password=password,
            )
            joined = await db.get(Tenant, invite.tenant_id)
            tenant_slug = joined.slug if joined else None
        # Following the emailed link proves control of the address.
        user.is_verified = True
        invite.accepted_at = datetime.now(UTC)
        await db.flush()
        await audit.record(
            db, action="invite.accept", actor_user_id=user.id,
            resource_type="invite", resource_id=invite.id,
            tenant_id=user.tenant_id, product_id=invite.product_id,
            diff={"kind": invite.kind},
        )

    _, access, refresh, exp = await auth_svc.login(
        db, product_id=invite.product_id, email=invite.email, password=password,
        tenant_slug=tenant_slug, user_agent=user_agent, ip_address=ip_address,
    )
    return access, refresh, exp
