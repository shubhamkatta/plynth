"""Subscription commands: show / purchase / change / cancel.

Routes live under ``/api/v1/subscription`` and operate on the caller's
(effective) tenant. Use ``--tenant <slug>`` to act on a child tenant.
"""

from __future__ import annotations

from typing import Any

import click

from plynth_cli.client import API_PREFIX, get_client

_COLS = [
    "plan_code", "status", "has_access",
    "current_period_start", "current_period_end",
    "trial_end", "cancel_at_period_end",
]


@click.group(name="subscription", help="Manage the active tenant's subscription.")
def group() -> None:
    pass


def _scope_opts(f):  # type: ignore[no-untyped-def]
    f = click.option("--product", "product_slug", default=None,
                     help="Override session product (X-Product-Slug).")(f)
    f = click.option("--tenant", "acting_tenant_slug", default=None,
                     help="Act-as a child tenant (X-Acting-Tenant-Slug).")(f)
    return f


@group.command("show")
@_scope_opts
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def show_cmd(
    ctx: click.Context, product_slug: str | None,
    acting_tenant_slug: str | None, as_json: bool,
) -> None:
    """GET /subscription."""
    from plynth_cli.cli import print_output

    client = get_client(ctx.obj)
    data = client.get(
        f"{API_PREFIX}/subscription",
        product_slug=product_slug,
        acting_tenant_slug=acting_tenant_slug,
    )
    print_output(data, as_json=as_json, columns=_COLS, title="Subscription")


@group.command("purchase")
@_scope_opts
@click.option("--plan-code", required=True)
@click.option("--payment-method-token", default=None, help="Provider token (e.g. Stripe 'pm_...').")
@click.option("--idempotency-key", default=None, help="Optional explicit Idempotency-Key.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def purchase_cmd(
    ctx: click.Context,
    product_slug: str | None,
    acting_tenant_slug: str | None,
    plan_code: str,
    payment_method_token: str | None,
    idempotency_key: str | None,
    as_json: bool,
) -> None:
    """POST /subscription/purchase."""
    from plynth_cli.cli import print_output

    body: dict[str, Any] = {"plan_code": plan_code}
    if payment_method_token:
        body["payment_method_token"] = payment_method_token

    client = get_client(ctx.obj)
    data = client.post(
        f"{API_PREFIX}/subscription/purchase",
        json_body=body,
        product_slug=product_slug,
        acting_tenant_slug=acting_tenant_slug,
        idempotent=True,
        idempotency_key=idempotency_key,
    )
    print_output(data, as_json=as_json, columns=_COLS)


@group.command("change")
@_scope_opts
@click.option("--plan-code", required=True)
@click.option("--proration/--no-proration", default=True)
@click.option("--idempotency-key", default=None)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def change_cmd(
    ctx: click.Context,
    product_slug: str | None,
    acting_tenant_slug: str | None,
    plan_code: str,
    proration: bool,
    idempotency_key: str | None,
    as_json: bool,
) -> None:
    """POST /subscription/change."""
    from plynth_cli.cli import print_output

    body: dict[str, Any] = {"plan_code": plan_code, "proration": proration}

    client = get_client(ctx.obj)
    data = client.post(
        f"{API_PREFIX}/subscription/change",
        json_body=body,
        product_slug=product_slug,
        acting_tenant_slug=acting_tenant_slug,
        idempotent=True,
        idempotency_key=idempotency_key,
    )
    print_output(data, as_json=as_json, columns=_COLS)


@group.command("cancel")
@_scope_opts
@click.option(
    "--immediately",
    is_flag=True,
    help="Cancel immediately instead of waiting for the period end.",
)
@click.option("--reason", default=None)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def cancel_cmd(
    ctx: click.Context,
    product_slug: str | None,
    acting_tenant_slug: str | None,
    immediately: bool,
    reason: str | None,
    as_json: bool,
) -> None:
    """POST /subscription/cancel."""
    from plynth_cli.cli import print_output

    body: dict[str, Any] = {"at_period_end": not immediately}
    if reason:
        body["reason"] = reason

    client = get_client(ctx.obj)
    data = client.post(
        f"{API_PREFIX}/subscription/cancel",
        json_body=body,
        product_slug=product_slug,
        acting_tenant_slug=acting_tenant_slug,
    )
    print_output(data, as_json=as_json, columns=_COLS)
