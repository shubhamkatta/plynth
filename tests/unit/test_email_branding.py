"""Transactional email carries no hard-coded brand.

This is a product-agnostic platform, and its email templates used to contain
one deployment's name, tagline and marketing copy. That is a reuse problem
before it is anything else: nobody could adopt the scaffold without editing
the template module, and the brand travelled into every fork of the repo.

Branding is now `Settings.brand_*`, resolved once in `notifications.render`
and merged *underneath* the caller's context so any key can be overridden
per-send. These pin the three properties that matter: an unconfigured
deployment still sends complete mail, a configured one is fully branded, and
bad configuration never costs anyone their email.
"""

from __future__ import annotations

import pytest

from app.providers import email_templates, notifications

ALL_TEMPLATES = (
    "invite",
    "welcome",
    "onboarding_complete",
    "password_reset",
    "mfa_otp",
    "payment_reminder",
)

CONTEXT = {
    "name": "Pat",
    "inviter": "Sam",
    "link": "https://app.example.com/x",
    "code": "123456",
    "practice_name": "Oak Clinic",
    "tenant_name": "Oak Clinic",
    "amount_cents": 2900,
    "currency": "INR",
    "due_at": "1 December",
    "url": "https://app.example.com/pay",
    "expires_days": 7,
    "expires_minutes": 60,
}


def _rendered(template: str, **overrides) -> str:
    message = notifications.render(template, {**CONTEXT, **overrides})
    return f"{message.subject}\n{message.text}\n{message.html}"


@pytest.mark.parametrize("template", ALL_TEMPLATES)
def test_no_template_hard_codes_a_product_name(template: str, monkeypatch) -> None:
    """The regression this guards: a brand string re-entering the templates.

    Checked differentially rather than by searching for a forbidden word —
    naming the old brand here would put it back in the repo, which is the
    thing being prevented. Render the same template under two unrelated
    brands: a name baked into the template appears in BOTH outputs, while a
    name that arrives through configuration appears in exactly one.
    """
    outputs: dict[str, str] = {}
    for brand in ("Northwind", "Zephyr"):
        monkeypatch.setattr(email_templates.settings, "brand_name", brand)
        outputs[brand] = _rendered(template)

    assert "Northwind" not in outputs["Zephyr"], f"{template} leaks a brand"
    assert "Zephyr" not in outputs["Northwind"], f"{template} leaks a brand"
    # The shipped default must not survive into a configured render either.
    assert "Acme" not in outputs["Zephyr"], f"{template} hard-codes the default"


@pytest.mark.parametrize("template", ALL_TEMPLATES)
def test_every_template_renders_unconfigured(template: str) -> None:
    """Defaults are a working unbranded set, not placeholders to be replaced:
    a deployment that configures nothing still sends correct mail."""
    message = notifications.render(template, dict(CONTEXT))
    assert message.subject.strip()
    assert message.text.strip()
    assert "<!doctype html>" in message.html.lower()
    # No empty-paragraph artefacts from the optional copy being absent.
    assert "<p" in message.html


def test_configuration_brands_every_surface(monkeypatch) -> None:
    monkeypatch.setattr(notifications.settings, "brand_name", "Northwind")
    monkeypatch.setattr(notifications.settings, "brand_tagline", "a tagline")
    monkeypatch.setattr(email_templates.settings, "brand_name", "Northwind")
    monkeypatch.setattr(email_templates.settings, "brand_tagline", "a tagline")

    welcome = notifications.render("welcome", dict(CONTEXT))
    assert "Northwind" in welcome.subject
    # The footer line and the logo square both follow the configured name.
    assert "a tagline" in welcome.html
    assert "an account with Northwind" in welcome.html

    otp = notifications.render("mfa_otp", dict(CONTEXT))
    assert "Northwind" in otp.subject


def test_the_context_overrides_configuration() -> None:
    """The hook a future per-product branding lookup uses: one deployment can
    serve several products, so the brand must be overridable per-send."""
    body = _rendered("welcome", brand_name="PerProduct")
    assert "PerProduct" in body


def test_optional_copy_is_omitted_rather_than_rendered_empty(monkeypatch) -> None:
    monkeypatch.setattr(email_templates.settings, "brand_pitch", "")
    monkeypatch.setattr(email_templates.settings, "brand_promise", "")
    invite = notifications.render("invite", dict(CONTEXT))
    # No stray blank paragraph or double newline where the pitch would be.
    assert "\n\n\n" not in invite.text

    monkeypatch.setattr(email_templates.settings, "brand_pitch", "It does the thing.")
    assert "It does the thing." in notifications.render("invite", dict(CONTEXT)).text


@pytest.mark.parametrize(
    "configured",
    [
        '["<strong>First.</strong> Do this.", "<strong>Second.</strong> Then this."]',
        "<strong>First.</strong> Do this.|<strong>Second.</strong> Then this.",
    ],
    ids=["json", "pipe-separated"],
)
def test_welcome_steps_come_from_configuration(monkeypatch, configured: str) -> None:
    """Both formats, because the pipe-separated one is what survives an env
    file: a JSON array has to get through dotenv AND Docker Compose's
    `env_file` parser with its nested double quotes intact."""
    monkeypatch.setattr(email_templates.settings, "brand_welcome_steps", configured)
    welcome = notifications.render("welcome", dict(CONTEXT))
    assert "Do this." in welcome.html and "Then this." in welcome.html
    # The plain-text part strips the inline tags rather than escaping them into
    # visible markup, and numbers the steps itself.
    assert "1. First. Do this." in welcome.text
    assert "<strong>" not in welcome.text


def test_malformed_welcome_steps_degrade_to_the_generic_set(monkeypatch) -> None:
    """Bad configuration must never cost someone their welcome email. Only
    values that announce themselves as JSON (a leading `[`) are parsed as
    JSON; anything else is treated as a pipe-separated list, so these are the
    cases that genuinely cannot yield steps."""
    for bad in ("[", "[}", "[]", "[1, 2, 3]", '{"a": 1}', "   ", "|||"):
        monkeypatch.setattr(email_templates.settings, "brand_welcome_steps", bad)
        welcome = notifications.render("welcome", dict(CONTEXT))
        assert welcome.subject
        assert "Finish your profile" in welcome.html, f"no fallback for {bad!r}"


def test_a_hostile_brand_name_is_escaped(monkeypatch) -> None:
    monkeypatch.setattr(email_templates.settings, "brand_name", "<script>x</script>")
    html = notifications.render("welcome", dict(CONTEXT)).html
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
