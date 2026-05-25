"""Tenant commands: list / create / activate / deactivate / expire.

Routes live under ``/api/v1/tenants``. Most require a user JWT (or admin
god-mode) and ``X-Product-Slug`` to scope the call. Pass
``--product <slug>`` on any subcommand to override the session product.
"""

from __future__ import annotations

import json as _json
from datetime import UTC, datetime
from typing import Any

import click

from plynth_cli.client import API_PREFIX, get_client


@click.group(name="tenants", help="Manage tenants within a product.")
def group() -> None:
    pass


def _product_opt(f):  # type: ignore[no-untyped-def]
    return click.option(
        "--product",
        "product_slug",
        default=None,
        help="Override session product slug (X-Product-Slug).",
    )(f)


@group.command("list")
@_product_opt
@click.option("--children", is_flag=True, help="List direct children (with can_act_as).")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output.")
@click.pass_context
def list_cmd(
    ctx: click.Context, product_slug: str | None, children: bool, as_json: bool
) -> None:
    """GET /tenants (or /tenants/children)."""
    from plynth_cli.cli import print_output

    client = get_client(ctx.obj)
    path = f"{API_PREFIX}/tenants/children" if children else f"{API_PREFIX}/tenants"
    data = client.get(path, product_slug=product_slug)
    if children:
        cols = ["slug", "name", "status", "can_act_as", "reason", "id"]
    else:
        cols = ["slug", "name", "status", "type", "is_root", "parent_id", "expires_at", "id"]
    print_output(data, as_json=as_json, columns=cols, title="Tenants")


@group.command("create")
@_product_opt
@click.option("--slug", required=True, help="URL-safe tenant slug.")
@click.option("--name", required=True, help="Tenant display name.")
@click.option(
    "--type",
    "tenant_type",
    type=click.Choice(["company", "individual"], case_sensitive=False),
    default="company",
)
@click.option("--parent-id", default=None, help="Parent tenant UUID (defaults to caller's tenant).")
@click.option("--expires-at", default=None, help="ISO datetime hard expiry cap.")
@click.option(
    "--settings",
    "settings_json",
    default=None,
    help="JSON object for tenant.settings.",
)
@click.option("--owner-email", default=None, help="Bootstrap owner email (admin only).")
@click.option("--owner-password", default=None, help="Bootstrap owner password (admin only).")
@click.option("--owner-name", default=None, help="Bootstrap owner full name.")
@click.option("--plan-code", default=None, help="Plan code to start on trial (admin bootstrap).")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output.")
@click.pass_context
def create_cmd(
    ctx: click.Context,
    product_slug: str | None,
    slug: str,
    name: str,
    tenant_type: str,
    parent_id: str | None,
    expires_at: str | None,
    settings_json: str | None,
    owner_email: str | None,
    owner_password: str | None,
    owner_name: str | None,
    plan_code: str | None,
    as_json: bool,
) -> None:
    """POST /tenants. Pass owner-* to atomically bootstrap an owner user."""
    from plynth_cli.cli import print_output

    body: dict[str, Any] = {
        "slug": slug,
        "name": name,
        "type": tenant_type.lower(),
        "settings": {},
    }
    if parent_id:
        body["parent_id"] = parent_id
    if expires_at:
        body["expires_at"] = expires_at
    if settings_json:
        try:
            obj = _json.loads(settings_json)
        except _json.JSONDecodeError as exc:
            raise click.UsageError(f"--settings must be valid JSON ({exc})") from exc
        if not isinstance(obj, dict):
            raise click.UsageError("--settings must be a JSON object")
        body["settings"] = obj
    if owner_email:
        if not owner_password:
            owner_password = click.prompt("owner password", hide_input=True)
        body["owner"] = {
            "email": owner_email,
            "password": owner_password,
            "full_name": owner_name,
        }
    if plan_code:
        body["plan_code"] = plan_code

    client = get_client(ctx.obj)
    data = client.post(f"{API_PREFIX}/tenants", json_body=body, product_slug=product_slug)
    print_output(data, as_json=as_json, columns=["slug", "name", "status", "type", "id"])


@group.command("activate")
@_product_opt
@click.argument("tenant_id")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def activate_cmd(
    ctx: click.Context, product_slug: str | None, tenant_id: str, as_json: bool
) -> None:
    """POST /tenants/{id}/activate."""
    from plynth_cli.cli import print_output

    client = get_client(ctx.obj)
    data = client.post(
        f"{API_PREFIX}/tenants/{tenant_id}/activate", product_slug=product_slug
    )
    print_output(data, as_json=as_json, columns=["slug", "name", "status", "id"])


@group.command("deactivate")
@_product_opt
@click.argument("tenant_id")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def deactivate_cmd(
    ctx: click.Context, product_slug: str | None, tenant_id: str, as_json: bool
) -> None:
    """POST /tenants/{id}/deactivate."""
    from plynth_cli.cli import print_output

    client = get_client(ctx.obj)
    data = client.post(
        f"{API_PREFIX}/tenants/{tenant_id}/deactivate", product_slug=product_slug
    )
    print_output(data, as_json=as_json, columns=["slug", "name", "status", "id"])


@group.command("expire")
@_product_opt
@click.argument("tenant_id")
@click.option(
    "--at",
    "expires_at",
    default=None,
    help="ISO datetime (defaults to 'now' to expire immediately). Pass 'null' to clear.",
)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def expire_cmd(
    ctx: click.Context,
    product_slug: str | None,
    tenant_id: str,
    expires_at: str | None,
    as_json: bool,
) -> None:
    """PATCH /tenants/{id} — set the hard expiry cap (admin override)."""
    from plynth_cli.cli import print_output

    if expires_at == "null":
        body: dict[str, Any] = {"expires_at": None}
    elif expires_at is None:
        body = {"expires_at": datetime.now(UTC).isoformat()}
    else:
        body = {"expires_at": expires_at}

    client = get_client(ctx.obj)
    data = client.patch(
        f"{API_PREFIX}/tenants/{tenant_id}", json_body=body, product_slug=product_slug
    )
    print_output(
        data,
        as_json=as_json,
        columns=["slug", "name", "status", "expires_at", "id"],
    )
