"""Plan commands: list / create / update.

* ``GET /plans`` is public (no JWT) — only needs ``X-Product-Slug``.
* Mutations require ``plans:write`` permission via JWT (or admin token).
"""

from __future__ import annotations

import json as _json
from typing import Any

import click

from plynth_cli.client import API_PREFIX, get_client


@click.group(name="plans", help="Manage subscription plans.")
def group() -> None:
    pass


def _product_opt(f):  # type: ignore[no-untyped-def]
    return click.option("--product", "product_slug", default=None,
                        help="Override session product slug.")(f)


@group.command("list")
@_product_opt
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def list_cmd(ctx: click.Context, product_slug: str | None, as_json: bool) -> None:
    """GET /plans (public, only public plans)."""
    from plynth_cli.cli import print_output

    client = get_client(ctx.obj)
    data = client.get(f"{API_PREFIX}/plans", product_slug=product_slug, skip_auth=True)
    print_output(
        data,
        as_json=as_json,
        columns=[
            "code", "name", "price_cents", "currency", "interval",
            "trial_days", "is_public", "is_active",
        ],
        title="Plans",
    )


@group.command("create")
@_product_opt
@click.option("--code", required=True, help="URL-safe plan code (e.g. 'pro_monthly').")
@click.option("--name", required=True)
@click.option("--description", default=None)
@click.option("--price-cents", type=int, required=True)
@click.option("--currency", default="USD", show_default=True)
@click.option(
    "--interval",
    type=click.Choice(["month", "year", "week", "day"], case_sensitive=False),
    default="month",
)
@click.option("--trial-days", type=int, default=0, show_default=True)
@click.option("--public/--private", "is_public", default=True)
@click.option(
    "--features",
    "features_json",
    default=None,
    help='JSON array of feature objects, e.g. \'[{"feature_key":"ai_completion","credit_amount":1000}]\'.',
)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def create_cmd(
    ctx: click.Context,
    product_slug: str | None,
    code: str,
    name: str,
    description: str | None,
    price_cents: int,
    currency: str,
    interval: str,
    trial_days: int,
    is_public: bool,
    features_json: str | None,
    as_json: bool,
) -> None:
    """POST /plans."""
    from plynth_cli.cli import print_output

    body: dict[str, Any] = {
        "code": code,
        "name": name,
        "price_cents": price_cents,
        "currency": currency.upper(),
        "interval": interval.lower(),
        "trial_days": trial_days,
        "is_public": is_public,
        "features": [],
    }
    if description is not None:
        body["description"] = description
    if features_json:
        try:
            feats = _json.loads(features_json)
        except _json.JSONDecodeError as exc:
            raise click.UsageError(f"--features must be valid JSON ({exc})") from exc
        if not isinstance(feats, list):
            raise click.UsageError("--features must be a JSON array")
        body["features"] = feats

    client = get_client(ctx.obj)
    data = client.post(f"{API_PREFIX}/plans", json_body=body, product_slug=product_slug)
    print_output(data, as_json=as_json,
                 columns=["code", "name", "price_cents", "currency", "interval", "is_active"])


@group.command("update")
@_product_opt
@click.argument("code")
@click.option("--name", default=None)
@click.option("--description", default=None)
@click.option("--price-cents", type=int, default=None)
@click.option("--public/--private", "is_public", default=None)
@click.option("--active/--inactive", "is_active", default=None)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def update_cmd(
    ctx: click.Context,
    product_slug: str | None,
    code: str,
    name: str | None,
    description: str | None,
    price_cents: int | None,
    is_public: bool | None,
    is_active: bool | None,
    as_json: bool,
) -> None:
    """PATCH /plans/{code}."""
    from plynth_cli.cli import print_output

    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if price_cents is not None:
        body["price_cents"] = price_cents
    if is_public is not None:
        body["is_public"] = is_public
    if is_active is not None:
        body["is_active"] = is_active
    if not body:
        raise click.UsageError("nothing to update; pass at least one field")

    client = get_client(ctx.obj)
    data = client.patch(
        f"{API_PREFIX}/plans/{code}", json_body=body, product_slug=product_slug
    )
    print_output(data, as_json=as_json,
                 columns=["code", "name", "price_cents", "is_public", "is_active"])
