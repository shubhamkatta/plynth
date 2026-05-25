"""Credit commands: wallets / ledger / grant.

Routes live under ``/api/v1/credits``. Operate on the caller's effective
tenant — use ``--tenant <slug>`` to act-as a child.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import click

from plynth_cli.client import API_PREFIX, get_client


@click.group(name="credits", help="Inspect / grant feature credits.")
def group() -> None:
    pass


def _scope_opts(f):  # type: ignore[no-untyped-def]
    f = click.option("--product", "product_slug", default=None,
                     help="Override session product (X-Product-Slug).")(f)
    f = click.option("--tenant", "acting_tenant_slug", default=None,
                     help="Act-as a child tenant (X-Acting-Tenant-Slug).")(f)
    return f


def _validate_amount(amount: str) -> str:
    """Validate decimal but pass through as string to preserve precision."""
    try:
        d = Decimal(amount)
    except InvalidOperation as exc:
        raise click.UsageError(f"--amount must be a decimal number ({exc})") from exc
    if d <= 0:
        raise click.UsageError("--amount must be > 0")
    return str(d)


@group.command("wallets")
@_scope_opts
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def wallets_cmd(
    ctx: click.Context, product_slug: str | None,
    acting_tenant_slug: str | None, as_json: bool,
) -> None:
    """GET /credits/wallets."""
    from plynth_cli.cli import print_output

    client = get_client(ctx.obj)
    data = client.get(
        f"{API_PREFIX}/credits/wallets",
        product_slug=product_slug,
        acting_tenant_slug=acting_tenant_slug,
    )
    print_output(
        data,
        as_json=as_json,
        columns=["feature_key", "balance", "tenant_id", "updated_at", "id"],
        title="Credit Wallets",
    )


@group.command("ledger")
@_scope_opts
@click.option("--limit", type=int, default=100, show_default=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def ledger_cmd(
    ctx: click.Context,
    product_slug: str | None,
    acting_tenant_slug: str | None,
    limit: int,
    as_json: bool,
) -> None:
    """GET /credits/ledger."""
    from plynth_cli.cli import print_output

    client = get_client(ctx.obj)
    data = client.get(
        f"{API_PREFIX}/credits/ledger",
        params={"limit": limit},
        product_slug=product_slug,
        acting_tenant_slug=acting_tenant_slug,
    )
    print_output(
        data,
        as_json=as_json,
        columns=[
            "created_at", "entry_type", "amount", "balance_after",
            "reason", "reference", "wallet_id",
        ],
        title="Credit Ledger",
    )


@group.command("grant")
@_scope_opts
@click.option("--feature", "feature_key", required=True, help="Feature key (e.g. 'ai_completion').")
@click.option("--amount", required=True, help="Decimal amount to grant.")
@click.option("--reason", default=None)
@click.option("--reference", default=None, help="Idempotency reference key.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def grant_cmd(
    ctx: click.Context,
    product_slug: str | None,
    acting_tenant_slug: str | None,
    feature_key: str,
    amount: str,
    reason: str | None,
    reference: str | None,
    as_json: bool,
) -> None:
    """POST /credits/grant."""
    from plynth_cli.cli import print_output

    body: dict[str, Any] = {
        "feature_key": feature_key,
        "amount": _validate_amount(amount),
    }
    if reason is not None:
        body["reason"] = reason
    if reference is not None:
        body["reference"] = reference

    client = get_client(ctx.obj)
    data = client.post(
        f"{API_PREFIX}/credits/grant",
        json_body=body,
        product_slug=product_slug,
        acting_tenant_slug=acting_tenant_slug,
    )
    print_output(data, as_json=as_json, columns=["feature_key", "balance", "tenant_id", "id"])
