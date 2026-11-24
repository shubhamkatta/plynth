"""Email content: the Acme-themed HTML layout plus one function per template.

Why templates are **functions** and not format strings
------------------------------------------------------
The previous ``TEMPLATES`` dict held ``str.format``-style bodies and ``render``
called ``format_map`` on them. That cannot carry HTML: a stylesheet is full of
``{`` and ``}``, so ``format_map`` either raises or silently eats the CSS. Each
template is therefore a function taking the context and returning both bodies.
No braces are special, and the subject/text/HTML of one email stay together
where they can be read side by side.

Design
------
Tokens come from ``example-app/docs/DESIGN_SYSTEM.md`` — the **light** column,
because an email is read on whatever background the client chooses and light is
the app's default. Mail clients are not browsers, so:

* layout is tables, not flexbox or grid;
* every style that matters is **inline** — Gmail strips ``<head><style>``, so
  the ``<style>`` block carries only progressive enhancement (dark mode, small
  screens) and never anything the email needs to be legible;
* the logo is a **CSS rounded square with a letter in it**, not an image.
  Images are blocked by default in most clients, and a brand mark that only
  appears after "display images" is a brand mark most readers never see;
* a preheader (the grey snippet after the subject in an inbox list) is set
  explicitly — left unset, clients scrape the first text they find, which is
  usually "View this email" or a bare URL.

Voice
-----
Warm and plain-spoken: short sentences, second person, no "Dear valued user",
no corporate hedging. Security mail (reset codes, OTPs) stays warm but drops
the playfulness — someone reading "did you just try to sign in?" wants a clear
answer, not a joke.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

# --- tokens (DESIGN_SYSTEM.md, light column) --------------------------------
BG = "#fafaf9"  # stone-50
SURFACE = "#ffffff"
BORDER = "#e4e4e7"  # zinc-200
ACCENT = "#0d9488"  # teal-600 — teal-400 fails contrast on white
ACCENT_FG = "#ffffff"
LOGO_BG = "#2dd4bf"  # teal-400: the brand mark is unchanged in light mode
LOGO_FG = "#09090b"  # zinc-950
TEXT = "#18181b"  # zinc-900
MUTED = "#52525b"  # zinc-600
SOFT = "#f4f4f5"  # zinc-100, for inset panels
POSITIVE = "#059669"  # emerald-600

FONT = (
    "'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
    "Helvetica,Arial,sans-serif"
)
MONO = "'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"


class RenderedEmail(NamedTuple):
    """Subject plus both bodies. Multipart alternative needs the text part to
    be a real alternative, not an afterthought — some clients and most
    accessibility tooling read it, and a text part that just says "use an HTML
    client" is what gets mail scored as spam."""

    subject: str
    text: str
    html: str


def _esc(value: Any) -> str:
    """Escape for HTML text/attribute context.

    Context values are user-controlled (display names, practice names), so
    they are escaped on the way into the HTML — never trusted because they
    "came from our own database".
    """
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _greeting(name: str | None) -> str:
    """"Hi Priya," when we know the name, "Hi," when we don't.

    Never "Hi there," or "Hi {name}," with an empty name — a greeting with a
    hole in it reads worse than no name at all.
    """
    clean = (name or "").strip()
    return f"Hi {clean}," if clean else "Hi,"


def _button(label: str, href: str) -> str:
    """A pill CTA. Uses a table rather than a styled ``<a>`` because Outlook
    ignores padding on inline elements and the button collapses to a link."""
    return f"""
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:28px 0;">
        <tr>
          <td align="center" bgcolor="{ACCENT}" style="border-radius:9999px;">
            <a href="{_esc(href)}"
               style="display:inline-block;padding:14px 32px;font-family:{FONT};
                      font-size:16px;font-weight:600;line-height:1;color:{ACCENT_FG};
                      text-decoration:none;border-radius:9999px;">{_esc(label)}</a>
          </td>
        </tr>
      </table>"""


def _panel(inner_html: str) -> str:
    """Inset panel for codes, amounts and summaries.

    The ``mv-panel`` class is load-bearing, not decoration. Panel contents use
    ``mv-text``, which the dark-mode block flips to near-white; without
    ``mv-panel`` flipping the background to match, that is near-white text on a
    near-white panel — invisible for every reader whose client honours
    ``prefers-color-scheme``, which is most of them.
    """
    return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
             style="margin:24px 0;">
        <tr>
          <td class="mv-panel"
              style="background:{SOFT};border:1px solid {BORDER};border-radius:16px;padding:20px 24px;">
            {inner_html}
          </td>
        </tr>
      </table>"""


def _layout(*, preheader: str, heading: str, body_html: str, footnote: str = "") -> str:
    """Wrap content in the Acme shell.

    ``footnote`` is the small print directly under the content (e.g. "if you
    didn't ask for this, ignore it") — kept separate from the standing footer
    so it reads as part of the message rather than boilerplate.
    """
    foot = (
        f"""<p style="margin:24px 0 0;font-family:{FONT};font-size:14px;
                      line-height:22px;color:{MUTED};">{footnote}</p>"""
        if footnote
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>{_esc(heading)}</title>
<style>
  /* Progressive enhancement only. Everything the email needs to be readable
     is inline; Gmail discards this block entirely. */
  @media (prefers-color-scheme: dark) {{
    .mv-bg {{ background:#09090b !important; }}
    .mv-card {{ background:#18181b !important; border-color:rgba(255,255,255,0.08) !important; }}
    .mv-text {{ color:#f4f4f5 !important; }}
    .mv-muted {{ color:#a1a1aa !important; }}
    .mv-panel {{ background:#27272a !important; border-color:rgba(255,255,255,0.08) !important; }}
  }}
  @media (max-width:620px) {{
    .mv-card {{ border-radius:0 !important; padding:28px 22px !important; }}
    .mv-h1 {{ font-size:24px !important; line-height:32px !important; }}
  }}
</style>
</head>
<body class="mv-bg" style="margin:0;padding:0;background:{BG};">
  <!-- preheader: the inbox snippet. Hidden in the body itself. -->
  <div style="display:none;font-size:1px;color:{BG};line-height:1px;max-height:0;
              max-width:0;opacity:0;overflow:hidden;">{_esc(preheader)}</div>

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
         class="mv-bg" style="background:{BG};">
    <tr>
      <td align="center" style="padding:32px 16px;">

        <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"
               style="width:100%;max-width:600px;">

          <!-- brand -->
          <tr>
            <td style="padding:0 4px 20px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td width="36" height="36" align="center" valign="middle"
                      bgcolor="{LOGO_BG}"
                      style="width:36px;height:36px;border-radius:10px;
                             font-family:{FONT};font-size:22px;font-weight:700;
                             color:{LOGO_FG};text-align:center;line-height:36px;">m</td>
                  <td style="padding-left:10px;font-family:{FONT};font-size:17px;
                             font-weight:600;color:{TEXT};" class="mv-text">Acme</td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- card -->
          <tr>
            <td class="mv-card"
                style="background:{SURFACE};border:1px solid {BORDER};border-radius:24px;
                       padding:40px;">
              <h1 class="mv-h1 mv-text"
                  style="margin:0 0 18px;font-family:{FONT};font-size:28px;line-height:36px;
                         font-weight:700;color:{TEXT};letter-spacing:-0.02em;">{_esc(heading)}</h1>
              {body_html}
              {foot}
            </td>
          </tr>

          <!-- footer -->
          <tr>
            <td style="padding:24px 8px 0;">
              <p class="mv-muted" style="margin:0;font-family:{FONT};font-size:13px;
                        line-height:20px;color:{MUTED};">
                Acme — the front desk your practice never had.<br>
                You're getting this because you have a Acme account.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _p(text_html: str, *, muted: bool = False) -> str:
    cls = "mv-muted" if muted else "mv-text"
    color = MUTED if muted else TEXT
    return (
        f'<p class="{cls}" style="margin:0 0 16px;font-family:{FONT};font-size:16px;'
        f'line-height:26px;color:{color};">{text_html}</p>'
    )


# --- templates ---------------------------------------------------------------


def _invite(ctx: Mapping[str, Any]) -> RenderedEmail:
    product = _esc(ctx.get("product_name") or "Acme")
    inviter = _esc(ctx.get("inviter") or "Someone")
    link = str(ctx.get("link") or "")
    days = ctx.get("expires_days") or 7
    name = ctx.get("name")

    text = (
        f"{_greeting(name)}\n\n"
        f"{inviter} set up a {product} account for you.\n\n"
        f"Pick a password and you're in — the link works for {days} days:\n{link}\n\n"
        "Acme answers your messages, books your sessions and chases your payments, "
        "so you can spend your day with clients instead of your inbox.\n\n"
        "Not expecting this? You can ignore this email and nothing will happen.\n"
    )
    html = _layout(
        preheader=f"{inviter} set up a {product} account for you — pick a password and you're in.",
        heading="Your practice just got a front desk",
        body_html=(
            _p(f"{_greeting(name)}")
            + _p(f"<strong>{inviter}</strong> set up a {product} account for you.")
            + _p("Pick a password and you're in. Takes about a minute.")
            + _button("Set my password", link)
            + _p(
                "Once you're in, Acme starts answering messages, booking sessions and "
                "chasing payments — so your day goes to your clients, not your inbox.",
                muted=True,
            )
        ),
        footnote=(
            f"This link works for {days} days. "
            "Not expecting it? Ignore this email and nothing happens."
        ),
    )
    return RenderedEmail(f"{inviter} invited you to {product}", text, html)


def _welcome(ctx: Mapping[str, Any]) -> RenderedEmail:
    name = ctx.get("name")
    product = _esc(ctx.get("product_name") or "Acme")
    link = str(ctx.get("link") or ctx.get("app_url") or "")

    steps = "".join(
        f"""<tr>
              <td width="28" valign="top" style="font-family:{MONO};font-size:14px;
                  font-weight:700;color:{ACCENT};padding:0 0 14px;">{i}</td>
              <td class="mv-text" valign="top" style="font-family:{FONT};font-size:15px;
                  line-height:24px;color:{TEXT};padding:0 0 14px;">{s}</td>
            </tr>"""
        for i, s in enumerate(
            (
                "<strong>Add your hours.</strong> Acme only offers slots you'd actually say yes to.",
                "<strong>Connect WhatsApp.</strong> Your number keeps working on your phone — "
                "Acme just stops letting messages sit unanswered.",
                "<strong>Add a client or two.</strong> Enough to see your week take shape.",
            ),
            start=1,
        )
    )

    text = (
        f"{_greeting(name)}\n\n"
        f"Welcome to {product} — your account is ready.\n\n"
        "Three things make the difference on day one:\n"
        "  1. Add your hours — Acme only offers slots you'd say yes to.\n"
        "  2. Connect WhatsApp — your number keeps working on your phone.\n"
        "  3. Add a client or two — enough to see your week take shape.\n\n"
        f"Start here: {link}\n\n"
        "Nothing goes out to a client without you saying so. Acme drafts; you decide.\n"
    )
    html = _layout(
        preheader="Your account is ready. Three things make the difference on day one.",
        heading=f"Welcome to {product} 🌿",
        body_html=(
            _p(f"{_greeting(name)}")
            + _p("Your account is ready. Here's what actually pays off on day one:")
            + _panel(
                f'<table role="presentation" width="100%" cellpadding="0" '
                f'cellspacing="0" border="0">{steps}</table>'
            )
            + _button("Set up my practice", link)
            + _p(
                "One promise worth knowing up front: nothing reaches a client without you "
                "saying so. Acme drafts, you decide.",
                muted=True,
            )
        ),
        footnote="Stuck on something? Reply to this email — a human reads it.",
    )
    return RenderedEmail(f"Welcome to {product} — let's get you set up", text, html)


def _onboarding_complete(ctx: Mapping[str, Any]) -> RenderedEmail:
    name = ctx.get("name")
    practice = _esc(ctx.get("practice_name") or "your practice")
    link = str(ctx.get("link") or ctx.get("app_url") or "")

    text = (
        f"{_greeting(name)}\n\n"
        f"{practice} is live on Acme. You're set up.\n\n"
        "From here on: messages get answered, sessions get booked, reminders go out "
        "before each session, and anything urgent comes straight to you.\n\n"
        "Nothing is on autopilot that you didn't switch on yourself.\n\n"
        f"Your dashboard: {link}\n"
    )
    html = _layout(
        preheader=f"{practice} is live on Acme. Here's what happens from here.",
        heading="You're all set ✨",
        body_html=(
            _p(f"{_greeting(name)}")
            + _p(f"<strong>{practice}</strong> is live on Acme.")
            + _p("From here on, without you lifting a finger:")
            + _panel(
                _p("💬 &nbsp;Messages get answered — drafts wait for your yes.")
                .replace("margin:0 0 16px", "margin:0 0 10px")
                + _p("📅 &nbsp;Sessions get booked into slots you approved.").replace(
                    "margin:0 0 16px", "margin:0 0 10px"
                )
                + _p("🔔 &nbsp;Reminders go out before each session.").replace(
                    "margin:0 0 16px", "margin:0 0 10px"
                )
                + _p("⚠️ &nbsp;Anything urgent comes straight to you, instantly.").replace(
                    "margin:0 0 16px", "margin:0"
                )
            )
            + _button("Open my dashboard", link)
            + _p(
                "Nothing is on autopilot that you didn't switch on yourself — and you can "
                "switch any of it back off in Settings.",
                muted=True,
            )
        ),
    )
    return RenderedEmail(f"{practice} is live on Acme", text, html)


def _password_reset(ctx: Mapping[str, Any]) -> RenderedEmail:
    link = str(ctx.get("link") or "")
    minutes = ctx.get("expires_minutes") or 60
    name = ctx.get("name")

    text = (
        f"{_greeting(name)}\n\n"
        f"Here's your link to set a new password. It works for the next {minutes} minutes:\n"
        f"{link}\n\n"
        "Didn't ask for this? Ignore this email — your password stays as it is.\n"
    )
    html = _layout(
        preheader=f"Set a new password — this link works for {minutes} minutes.",
        heading="Let's get you back in",
        body_html=(
            _p(f"{_greeting(name)}")
            + _p("Click below to choose a new password.")
            + _button("Set a new password", link)
            + _p(
                f"The link works for <strong>{minutes} minutes</strong>, then it stops "
                "working — that's deliberate.",
                muted=True,
            )
        ),
        footnote=(
            "Didn't ask for this? Ignore this email and your password stays exactly as it is. "
            "Nobody can get in with this link alone."
        ),
    )
    return RenderedEmail("Set a new password", text, html)


def _mfa_otp(ctx: Mapping[str, Any]) -> RenderedEmail:
    code = _esc(ctx.get("code") or "")
    minutes = ctx.get("expires_minutes") or 5

    text = (
        f"Your Acme verification code is {code}\n\n"
        f"It expires in {minutes} minutes.\n\n"
        "If you weren't signing in just now, someone has your password — "
        "change it as soon as you can.\n"
    )
    html = _layout(
        preheader=f"Your code is {code} — it expires in {minutes} minutes.",
        heading="Your sign-in code",
        body_html=(
            _p("Enter this to finish signing in:")
            + _panel(
                f'<div style="font-family:{MONO};font-size:34px;font-weight:700;'
                f'letter-spacing:0.18em;color:{TEXT};text-align:center;" '
                f'class="mv-text">{code}</div>'
            )
            + _p(f"It expires in {minutes} minutes.", muted=True)
        ),
        footnote=(
            "Weren't signing in just now? Someone else has your password — "
            "please change it as soon as you can."
        ),
    )
    return RenderedEmail("Your Acme verification code", text, html)


def _payment_reminder(ctx: Mapping[str, Any]) -> RenderedEmail:
    tenant = _esc(ctx.get("tenant") or "your practice")
    currency = _esc(ctx.get("currency") or "INR")
    due_at = _esc(ctx.get("due_at") or "")
    url = str(ctx.get("hosted_url") or "")
    # amount_cents arrives as an int from the billing tables but as a string
    # from a webhook payload, and may be absent entirely on a partial context.
    # Format it as money only when it really is a whole number of cents;
    # otherwise show it through as-is rather than inventing a figure.
    raw_cents = str(ctx.get("amount_cents") or "")
    amount = f"{int(raw_cents) / 100:,.2f}" if raw_cents.isdigit() else _esc(raw_cents)

    text = (
        f"A quick nudge about {tenant}.\n\n"
        f"Amount due: {amount} {currency}\n"
        f"Due: {due_at}\n\n"
        f"{url}\n\n"
        "Already paid? Then ignore this — it crossed in the post.\n"
    )
    html = _layout(
        preheader=f"{amount} {currency} due {due_at} for {tenant}.",
        heading="A quick nudge about your subscription",
        body_html=(
            _p(f"This is about <strong>{tenant}</strong>.")
            + _panel(
                f'<div class="mv-muted" style="font-family:{FONT};font-size:13px;'
                f'text-transform:uppercase;letter-spacing:0.06em;color:{MUTED};'
                f'margin-bottom:6px;">Amount due</div>'
                f'<div class="mv-text" style="font-family:{MONO};font-size:28px;'
                f'font-weight:700;color:{TEXT};">{amount} {currency}</div>'
                f'<div class="mv-muted" style="font-family:{FONT};font-size:14px;'
                f'color:{MUTED};margin-top:8px;">Due {due_at}</div>'
            )
            + _button("Pay now", url)
            + _p("Already paid? Then this crossed in the post — ignore it.", muted=True)
        ),
    )
    return RenderedEmail(f"Payment reminder for {tenant}", text, html)


#: template name -> renderer. Unknown names raise KeyError (programmer error).
TEMPLATES: dict[str, Callable[[Mapping[str, Any]], RenderedEmail]] = {
    "invite": _invite,
    "welcome": _welcome,
    "onboarding_complete": _onboarding_complete,
    "password_reset": _password_reset,
    "mfa_otp": _mfa_otp,
    "payment_reminder": _payment_reminder,
}
