"""User commands: list / invite / activate / deactivate / delete.

Routes live under ``/api/v1/users``. Pass ``--tenant`` to switch into a
child tenant (X-Acting-Tenant-Slug) for the invite/list/etc.
"""

from __future__ import annotations

from typing import Any

import click

from plynth_cli.client import API_PREFIX, get_client


@click.group(name="users", help="Manage users within the active tenant.")
def group() -> None:
    pass


def _scope_opts(f):  # type: ignore[no-untyped-def]
    f = click.option(
        "--product",
        "product_slug",
        default=None,
        help="Override session product (X-Product-Slug).",
    )(f)
    f = click.option(
        "--tenant",
        "acting_tenant_slug",
        default=None,
        help="Act-as a child tenant for this call (X-Acting-Tenant-Slug).",
    )(f)
    return f


@group.command("list")
@_scope_opts
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def list_cmd(
    ctx: click.Context,
    product_slug: str | None,
    acting_tenant_slug: str | None,
    as_json: bool,
) -> None:
    """GET /users."""
    from plynth_cli.cli import print_output

    client = get_client(ctx.obj)
    data = client.get(
        f"{API_PREFIX}/users",
        product_slug=product_slug,
        acting_tenant_slug=acting_tenant_slug,
    )
    print_output(
        data,
        as_json=as_json,
        columns=["email", "full_name", "is_active", "is_verified", "tenant_id", "id"],
        title="Users",
    )


@group.command("invite")
@_scope_opts
@click.option("--email", required=True)
@click.option("--full-name", default=None)
@click.option(
    "--role",
    "role_codes",
    multiple=True,
    help="One or more role codes to assign (e.g. --role admin --role billing).",
)
@click.option(
    "--initial-password",
    default=None,
    help="Optional pre-set password (otherwise the server generates one).",
)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def invite_cmd(
    ctx: click.Context,
    product_slug: str | None,
    acting_tenant_slug: str | None,
    email: str,
    full_name: str | None,
    role_codes: tuple[str, ...],
    initial_password: str | None,
    as_json: bool,
) -> None:
    """POST /users — invite a user; prints the one-shot initial password."""
    from plynth_cli.cli import print_output

    body: dict[str, Any] = {
        "email": email,
        "role_codes": list(role_codes),
    }
    if full_name is not None:
        body["full_name"] = full_name
    if initial_password:
        body["initial_password"] = initial_password

    client = get_client(ctx.obj)
    data = client.post(
        f"{API_PREFIX}/users",
        json_body=body,
        product_slug=product_slug,
        acting_tenant_slug=acting_tenant_slug,
    )
    print_output(
        data,
        as_json=as_json,
        columns=["email", "full_name", "is_active", "initial_password", "id"],
    )


@group.command("activate")
@_scope_opts
@click.argument("user_id")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def activate_cmd(
    ctx: click.Context,
    product_slug: str | None,
    acting_tenant_slug: str | None,
    user_id: str,
    as_json: bool,
) -> None:
    """POST /users/{id}/activate."""
    from plynth_cli.cli import print_output

    client = get_client(ctx.obj)
    data = client.post(
        f"{API_PREFIX}/users/{user_id}/activate",
        product_slug=product_slug,
        acting_tenant_slug=acting_tenant_slug,
    )
    print_output(data, as_json=as_json, columns=["email", "is_active", "id"])


@group.command("deactivate")
@_scope_opts
@click.argument("user_id")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def deactivate_cmd(
    ctx: click.Context,
    product_slug: str | None,
    acting_tenant_slug: str | None,
    user_id: str,
    as_json: bool,
) -> None:
    """POST /users/{id}/deactivate."""
    from plynth_cli.cli import print_output

    client = get_client(ctx.obj)
    data = client.post(
        f"{API_PREFIX}/users/{user_id}/deactivate",
        product_slug=product_slug,
        acting_tenant_slug=acting_tenant_slug,
    )
    print_output(data, as_json=as_json, columns=["email", "is_active", "id"])


@group.command("delete")
@_scope_opts
@click.argument("user_id")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def delete_cmd(
    ctx: click.Context,
    product_slug: str | None,
    acting_tenant_slug: str | None,
    user_id: str,
    yes: bool,
) -> None:
    """DELETE /users/{id} (soft-delete)."""
    if not yes:
        click.confirm(f"soft-delete user {user_id}?", abort=True)
    client = get_client(ctx.obj)
    client.delete(
        f"{API_PREFIX}/users/{user_id}",
        product_slug=product_slug,
        acting_tenant_slug=acting_tenant_slug,
    )
    click.echo(f"deleted user {user_id}")
