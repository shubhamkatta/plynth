"""Audit commands: list.

Note: the platform does not yet ship a public ``GET /api/v1/audit``
endpoint — see ``docs/architecture.md`` § 6 ("Audit — GET /api/v1/credits/ledger
as stand-in until /api/v1/audit ships"). Until then, ``plynth audit list``
proxies to the credit ledger as a best-available recent-activity view and
prints a hint. When the audit endpoint lands, switch ``_AUDIT_PATH``
below to ``/audit`` — no other change needed.
"""

from __future__ import annotations

import click

from plynth_cli.client import API_PREFIX, ApiCallError, get_client

# Flip this to "/audit" once the platform exposes it.
_AUDIT_PATH = "/audit"
_LEDGER_FALLBACK = "/credits/ledger"


@click.group(name="audit", help="Inspect audit log (uses credit ledger as fallback for now).")
def group() -> None:
    pass


@group.command("list")
@click.option("--product", "product_slug", default=None,
              help="Override session product (X-Product-Slug).")
@click.option("--tenant", "acting_tenant_slug", default=None,
              help="Act-as a child tenant (X-Acting-Tenant-Slug).")
@click.option("--limit", type=int, default=100, show_default=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def list_cmd(
    ctx: click.Context,
    product_slug: str | None,
    acting_tenant_slug: str | None,
    limit: int,
    as_json: bool,
) -> None:
    """GET /audit if available, else /credits/ledger."""
    from plynth_cli.cli import echo_info, print_output

    client = get_client(ctx.obj)
    try:
        data = client.get(
            f"{API_PREFIX}{_AUDIT_PATH}",
            params={"limit": limit},
            product_slug=product_slug,
            acting_tenant_slug=acting_tenant_slug,
        )
        cols = ["created_at", "action", "actor_user_id", "resource_type", "resource_id", "diff"]
        title = "Audit Log"
    except ApiCallError as exc:
        if exc.status != 404:
            raise
        if not as_json:
            echo_info("[dim]/audit not implemented; falling back to /credits/ledger[/dim]")
        data = client.get(
            f"{API_PREFIX}{_LEDGER_FALLBACK}",
            params={"limit": limit},
            product_slug=product_slug,
            acting_tenant_slug=acting_tenant_slug,
        )
        cols = ["created_at", "entry_type", "amount", "balance_after", "reason", "reference"]
        title = "Credit Ledger (audit fallback)"

    print_output(data, as_json=as_json, columns=cols, title=title)
