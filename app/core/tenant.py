"""Product + tenant request context.

Two `ContextVar`s carry the active product and tenant for the lifetime of
one request / background job. Repositories MUST consult these and add
`product_id = :pid AND tenant_id = :tid` filters to every query against
scoped tables; the `TenantRepository` in `app.repositories.base` enforces
this automatically.

Cross-product access (platform admin tools, webhooks before lookup) must
wrap the call in `bypass_product()`. Cross-tenant access uses
`bypass_tenant()`. Both are intentionally explicit — grep them.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator
from uuid import UUID

_current_product: ContextVar[UUID | None] = ContextVar("current_product", default=None)
_current_tenant: ContextVar[UUID | None] = ContextVar("current_tenant", default=None)
# Set when a parent-tenant user acts as a child tenant. The user's *home*
# tenant id, so audits can record "who in the parent did this in the child".
_acting_from_tenant: ContextVar[UUID | None] = ContextVar("acting_from_tenant", default=None)
_bypass_tenant_var: ContextVar[bool] = ContextVar("bypass_tenant", default=False)
_bypass_product_var: ContextVar[bool] = ContextVar("bypass_product", default=False)


# --- product ---

def set_current_product(product_id: UUID | None) -> None:
    _current_product.set(product_id)


def current_product_id() -> UUID | None:
    return _current_product.get()


def is_product_bypass() -> bool:
    return _bypass_product_var.get()


@contextmanager
def bypass_product() -> Iterator[None]:
    """Escape hatch for platform-admin tools / webhook lookup before the
    product id is known."""
    token = _bypass_product_var.set(True)
    try:
        yield
    finally:
        _bypass_product_var.reset(token)


# --- tenant ---

def set_current_tenant(tenant_id: UUID | None) -> None:
    _current_tenant.set(tenant_id)


def current_tenant_id() -> UUID | None:
    return _current_tenant.get()


# --- acting-from (parent → child switching) ---

def set_acting_from_tenant(tenant_id: UUID | None) -> None:
    _acting_from_tenant.set(tenant_id)


def acting_from_tenant_id() -> UUID | None:
    return _acting_from_tenant.get()


def is_bypass() -> bool:
    return _bypass_tenant_var.get()


@contextmanager
def bypass_tenant() -> Iterator[None]:
    """Explicit escape hatch — only for login / webhook / platform-admin code."""
    token = _bypass_tenant_var.set(True)
    try:
        yield
    finally:
        _bypass_tenant_var.reset(token)
