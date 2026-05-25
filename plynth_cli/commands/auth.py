"""Authentication commands: login / logout / me / whoami.

`login` supports two flavours:

* ``plynth login --product <slug>`` — email + password against the product.
  The password is prompted and never echoed. Tokens persist to
  ``~/.config/plynth/config.json``.
* ``plynth login --admin-token <TOKEN>`` — store the platform admin token
  instead. Subsequent ``plynth admin / products / …`` calls send
  ``X-Platform-Admin-Token``.
"""

from __future__ import annotations

from typing import Any

import click

from plynth_cli import config as cfg_mod
from plynth_cli.client import API_PREFIX, ApiClient


@click.group(name="auth", help="Authentication: login / logout / whoami / me.")
def group() -> None:
    pass


@group.command("login")
@click.option("--product", "product_slug", help="Product slug for email/password login.")
@click.option("--email", help="Account email (prompted if missing).")
@click.option("--tenant", "tenant_slug", default=None, help="Tenant slug (optional disambiguation).")
@click.option(
    "--admin-token",
    "admin_token",
    default=None,
    help="Save a platform-admin token instead of doing an email/password login.",
)
@click.option(
    "--admin-product",
    "admin_product",
    default=None,
    help="Default product slug to use under admin god-mode (for non-/admin paths).",
)
@click.pass_context
def login_cmd(
    ctx: click.Context,
    product_slug: str | None,
    email: str | None,
    tenant_slug: str | None,
    admin_token: str | None,
    admin_product: str | None,
) -> None:
    """Save credentials for subsequent calls."""
    cfg = cfg_mod.load_config()

    # Allow --base-url to override what we persist as the default base URL.
    base_url_override = ctx.obj.get("base_url") if ctx.obj else None
    if base_url_override:
        cfg["base_url"] = base_url_override

    if admin_token:
        cfg["admin_token"] = admin_token
        if admin_product:
            cfg["admin_product_slug"] = admin_product
        cfg_mod.save_config(cfg)
        click.echo("saved platform-admin token to " + str(cfg_mod.config_path()))
        return

    if not product_slug:
        raise click.UsageError("either --admin-token or --product is required")

    if not email:
        email = click.prompt("email")
    password = click.prompt("password", hide_input=True)

    client = ApiClient(base_url=cfg["base_url"], product_slug=product_slug)
    payload: dict[str, Any] = {"email": email, "password": password}
    if tenant_slug:
        payload["tenant_slug"] = tenant_slug

    tokens = client.post(
        f"{API_PREFIX}/auth/login",
        json_body=payload,
        skip_auth=True,
        product_slug=product_slug,
    )

    cfg["session"] = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "expires_at": tokens.get("expires_at"),
        "product_slug": product_slug,
        "email": email,
    }
    cfg_mod.save_config(cfg)
    click.echo(f"logged in as {email} on product '{product_slug}'")


@group.command("logout")
@click.option("--all-sessions", is_flag=True, help="Revoke every active refresh token for the user.")
@click.option("--admin", is_flag=True, help="Also clear the saved platform-admin token.")
@click.pass_context
def logout_cmd(ctx: click.Context, all_sessions: bool, admin: bool) -> None:
    """Clear the local session (and optionally revoke it server-side)."""
    cfg = cfg_mod.load_config()
    session = cfg.get("session")

    if session:
        try:
            client = ApiClient(
                base_url=cfg["base_url"],
                product_slug=session.get("product_slug"),
            )
            client.post(
                f"{API_PREFIX}/auth/logout",
                json_body={
                    "refresh_token": session.get("refresh_token"),
                    "all_sessions": all_sessions,
                },
            )
        except Exception as exc:  # noqa: BLE001 — server may already be gone
            click.echo(f"warning: server-side logout failed ({exc}); clearing local session anyway",
                       err=True)

    cfg_mod.clear_session()
    if admin:
        cfg_mod.clear_admin_token()
        click.echo("logged out and cleared admin token")
    else:
        click.echo("logged out")


@group.command("me")
@click.option("--json", "as_json", is_flag=True, help="Raw JSON output.")
@click.pass_context
def me_cmd(ctx: click.Context, as_json: bool) -> None:
    """Show the authenticated user (calls GET /auth/me)."""
    from plynth_cli.cli import print_output
    from plynth_cli.client import get_client

    client = get_client(ctx.obj)
    data = client.get(f"{API_PREFIX}/auth/me")
    print_output(
        data,
        as_json=as_json,
        columns=["email", "full_name", "tenant_id", "product_id", "is_active", "is_verified", "permissions"],
    )


@group.command("whoami")
@click.pass_context
def whoami_cmd(ctx: click.Context) -> None:
    """Show current local session/auth scope (no API call)."""
    cfg = cfg_mod.load_config()
    session = cfg.get("session")
    admin_token = cfg.get("admin_token")
    base = ctx.obj.get("base_url") if ctx.obj else None
    click.echo(f"config:        {cfg_mod.config_path()}")
    click.echo(f"base_url:      {base or cfg.get('base_url')}")
    click.echo(f"admin token:   {'yes' if admin_token else 'no'}")
    if cfg.get("admin_product_slug"):
        click.echo(f"admin product: {cfg['admin_product_slug']}")
    if session:
        click.echo("session:")
        click.echo(f"  email:        {session.get('email')}")
        click.echo(f"  product slug: {session.get('product_slug')}")
        click.echo(f"  expires at:   {session.get('expires_at')}")
    else:
        click.echo("session:       none")
    if cfg.get("acting_tenant_slug"):
        click.echo(f"acting tenant: {cfg['acting_tenant_slug']}")
