"""`scripts.seed_acme` must take its target product from configuration.

The seed creates the product when no product carries the configured slug, so
the slug decides between "update the catalog I meant" and "provision a second,
parallel product". That makes the resolution worth pinning down: the scaffold
default, the environment override, and the fact that it is read per call rather
than frozen at import.
"""

from __future__ import annotations

from app.core.config import settings
from scripts import seed_acme


def test_defaults_to_the_scaffold_product() -> None:
    assert seed_acme.target_product() == ("acme-practice", "Acme Practice")


def test_environment_overrides_both_slug_and_name(monkeypatch) -> None:
    monkeypatch.setattr(settings, "seed_product_slug", "someproduct-practice")
    monkeypatch.setattr(settings, "seed_product_name", "Someproduct Practice")
    assert seed_acme.target_product() == ("someproduct-practice", "Someproduct Practice")


def test_read_per_call_not_bound_at_import(monkeypatch) -> None:
    """A module-level constant would make the override silently ineffective
    for anything that imported the module before the environment was set."""
    first = seed_acme.target_product()
    monkeypatch.setattr(settings, "seed_product_slug", "changed-midflight")
    assert seed_acme.target_product()[0] == "changed-midflight"
    assert first[0] != "changed-midflight"


def test_no_hardcoded_product_slug_left_in_the_script() -> None:
    """Guards the regression this change exists to prevent: a literal slug in
    the script is how the live product lost its provisioning path."""
    import inspect

    src = inspect.getsource(seed_acme)
    # Strip the docstrings/comments that legitimately name the env var.
    code = "\n".join(
        line for line in src.splitlines()
        if not line.lstrip().startswith("#") and "``" not in line
    )
    assert 'slug == "' not in code
    assert 'name="Acme Practice"' not in code
