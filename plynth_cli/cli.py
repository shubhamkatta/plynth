"""Top-level Click app for plynth_cli.

Mounts every subcommand group from ``plynth_cli.commands.*`` and provides
shared formatting / error helpers used across the codebase.

Global options:

* ``--base-url``           — override the API base URL for this invocation.
* ``--product-slug``       — override the session's product for one call.
* ``--acting-tenant-slug`` — act-as a child tenant for this call.
* ``--json``               — emit raw JSON instead of a pretty table.

Errors from the API (``ApiCallError``) are caught at the entry point and
rendered as ``<code>: <message>``. Exit status 1 on any API error.
"""

from __future__ import annotations

import json as _json
import sys
from typing import Any

import click

from plynth_cli import __version__
from plynth_cli.client import ApiCallError
from plynth_cli.commands import (
    audit,
    auth,
    credits,
    plans,
    products,
    subscription,
    tenants,
    users,
)

# ---- optional rich rendering ----------------------------------------------

try:
    from rich.console import Console
    from rich.table import Table

    _RICH = True
    _console = Console()
    _err_console = Console(stderr=True)
except Exception:  # pragma: no cover — degrade gracefully
    _RICH = False
    _console = None  # type: ignore[assignment]
    _err_console = None  # type: ignore[assignment]


def echo_error(message: str) -> None:
    """Print an error message in red (if rich available) to stderr."""
    if _RICH and _err_console is not None:
        _err_console.print(f"[red]{message}[/red]")
    else:
        click.echo(message, err=True)


def echo_info(message: str) -> None:
    if _RICH and _console is not None:
        _console.print(message)
    else:
        click.echo(message)


def _coerce_rows(data: Any) -> list[dict[str, Any]]:
    if data is None:
        return []
    if isinstance(data, list):
        return [r if isinstance(r, dict) else {"value": r} for r in data]
    if isinstance(data, dict):
        return [data]
    return [{"value": data}]


def print_output(
    data: Any,
    *,
    as_json: bool,
    columns: list[str] | None = None,
    title: str | None = None,
) -> None:
    """Print ``data`` either as raw JSON or as a pretty table.

    ``columns`` picks/orders fields; defaults to the union of keys.
    """
    if as_json:
        click.echo(_json.dumps(data, indent=2, sort_keys=True, default=str))
        return

    rows = _coerce_rows(data)
    if not rows:
        echo_info("(no results)")
        return

    if columns is None:
        seen: list[str] = []
        for r in rows:
            for k in r.keys():
                if k not in seen:
                    seen.append(k)
        columns = seen

    if _RICH and _console is not None:
        table = Table(title=title, show_lines=False, header_style="bold cyan")
        for c in columns:
            table.add_column(c)
        for r in rows:
            table.add_row(*[_stringify(r.get(c)) for c in columns])
        _console.print(table)
    else:
        # Minimal fallback: pipe-delimited rows.
        click.echo(" | ".join(columns))
        click.echo("-+-".join("-" * len(c) for c in columns))
        for r in rows:
            click.echo(" | ".join(_stringify(r.get(c)) for c in columns))


def _stringify(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return _json.dumps(value, default=str)
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


# ---- root group -----------------------------------------------------------


@click.group(
    name="plynth",
    help=(
        "Plynth CLI — terminal admin for the Plynth multi-tenant platform.\n\n"
        "Wraps the REST API at /api/v1/*. See `plynth_cli/README.md` for usage."
    ),
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(__version__, prog_name="plynth")
@click.option(
    "--base-url",
    envvar="PLYNTH_BASE_URL",
    default=None,
    help="Override the API base URL (default: from config or http://localhost:8000).",
)
@click.option(
    "--product-slug",
    envvar="PLYNTH_PRODUCT_SLUG",
    default=None,
    help="Override the session product for this invocation (X-Product-Slug).",
)
@click.option(
    "--acting-tenant-slug",
    envvar="PLYNTH_ACTING_TENANT_SLUG",
    default=None,
    help="Act-as a child tenant for this invocation (X-Acting-Tenant-Slug).",
)
@click.pass_context
def main(
    ctx: click.Context,
    base_url: str | None,
    product_slug: str | None,
    acting_tenant_slug: str | None,
) -> None:
    """Root command — stores globals on the Click context for subcommands."""
    ctx.ensure_object(dict)
    ctx.obj["base_url"] = base_url
    ctx.obj["product_slug"] = product_slug
    ctx.obj["acting_tenant_slug"] = acting_tenant_slug


# Mount every commands/*.py group.
main.add_command(auth.group)
main.add_command(products.group)
main.add_command(tenants.group)
main.add_command(users.group)
main.add_command(plans.group)
main.add_command(subscription.group)
main.add_command(credits.group)
main.add_command(audit.group)


# Wrap the underlying invoke so we catch API errors centrally.
_original_main = main.main  # type: ignore[attr-defined]


def _safe_main(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover — top-level glue
    try:
        return _original_main(*args, **kwargs)
    except ApiCallError as exc:
        echo_error(f"{exc.code}: {exc.message}")
        if exc.details:
            echo_error(_json.dumps(exc.details, indent=2, default=str))
        sys.exit(1)
    except click.ClickException:
        raise
    except KeyboardInterrupt:
        echo_error("interrupted")
        sys.exit(130)


main.main = _safe_main  # type: ignore[assignment]
