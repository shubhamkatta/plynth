"""Product (platform-admin) commands: list / create / update.

All routes here live under ``/api/v1/admin/products`` and require the
platform-admin token (X-Platform-Admin-Token). Run
``plynth login --admin-token <TOKEN>`` first.
"""

from __future__ import annotations

import json as _json
from typing import Any

import click

from plynth_cli.client import API_PREFIX, get_client


@click.group(name="products", help="Manage products (platform admin).")
def group() -> None:
    pass


@group.command("list")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output.")
@click.pass_context
def list_cmd(ctx: click.Context, as_json: bool) -> None:
    """GET /admin/products."""
    from plynth_cli.cli import print_output

    client = get_client(ctx.obj)
    data = client.get(f"{API_PREFIX}/admin/products", as_platform_admin=True)
    print_output(
        data,
        as_json=as_json,
        columns=["slug", "name", "status", "is_active", "description", "id"],
        title="Products",
    )


@group.command("create")
@click.option("--slug", required=True, help="URL-safe identifier (e.g. 'chatbot').")
@click.option("--name", required=True, help="Display name.")
@click.option("--description", default=None, help="Optional product description.")
@click.option(
    "--tenant-type",
    type=click.Choice(["company", "individual"], case_sensitive=False),
    default="company",
    help="Default tenant type for seeded plans.",
)
@click.option(
    "--seed-plans/--no-seed-plans",
    default=True,
    help="Seed the standard plan set for the chosen tenant type.",
)
@click.option(
    "--settings",
    "settings_json",
    default=None,
    help="Optional JSON object for product.settings (e.g. '{\"auth\":{\"refresh_ttl_days\":7}}').",
)
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output.")
@click.pass_context
def create_cmd(
    ctx: click.Context,
    slug: str,
    name: str,
    description: str | None,
    tenant_type: str,
    seed_plans: bool,
    settings_json: str | None,
    as_json: bool,
) -> None:
    """POST /admin/products."""
    from plynth_cli.cli import print_output

    settings_obj: dict[str, Any] = {}
    if settings_json:
        try:
            settings_obj = _json.loads(settings_json)
        except _json.JSONDecodeError as exc:
            raise click.UsageError(f"--settings must be valid JSON ({exc})") from exc
        if not isinstance(settings_obj, dict):
            raise click.UsageError("--settings must be a JSON object")

    body: dict[str, Any] = {
        "slug": slug,
        "name": name,
        "seed_plans": seed_plans,
        "tenant_type": tenant_type.lower(),
        "settings": settings_obj,
    }
    if description is not None:
        body["description"] = description

    client = get_client(ctx.obj)
    data = client.post(f"{API_PREFIX}/admin/products", json_body=body, as_platform_admin=True)
    print_output(data, as_json=as_json, columns=["slug", "name", "status", "is_active", "id"])


@group.command("update")
@click.argument("slug")
@click.option("--name", default=None)
@click.option("--description", default=None)
@click.option(
    "--status",
    type=click.Choice(["active", "disabled", "archived"], case_sensitive=False),
    default=None,
    help="Set product status.",
)
@click.option("--is-active/--not-active", "is_active", default=None, help="Toggle is_active flag.")
@click.option(
    "--settings",
    "settings_json",
    default=None,
    help="JSON object — merged on top of existing settings.",
)
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output.")
@click.pass_context
def update_cmd(
    ctx: click.Context,
    slug: str,
    name: str | None,
    description: str | None,
    status: str | None,
    is_active: bool | None,
    settings_json: str | None,
    as_json: bool,
) -> None:
    """PATCH /admin/products/{slug}."""
    from plynth_cli.cli import print_output

    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if status is not None:
        body["status"] = status.lower()
    if is_active is not None:
        body["is_active"] = is_active
    if settings_json is not None:
        try:
            obj = _json.loads(settings_json)
        except _json.JSONDecodeError as exc:
            raise click.UsageError(f"--settings must be valid JSON ({exc})") from exc
        if not isinstance(obj, dict):
            raise click.UsageError("--settings must be a JSON object")
        body["settings"] = obj

    if not body:
        raise click.UsageError("nothing to update; pass at least one field")

    client = get_client(ctx.obj)
    data = client.patch(
        f"{API_PREFIX}/admin/products/{slug}", json_body=body, as_platform_admin=True
    )
    print_output(data, as_json=as_json, columns=["slug", "name", "status", "is_active", "id"])
