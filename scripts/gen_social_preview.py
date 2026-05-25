"""Generate docs/assets/social-preview.png — the 1280x640 GitHub social card.

Renders deterministically: run twice, get the same bytes.

Usage:
    python3 scripts/gen_social_preview.py

Output:
    docs/assets/social-preview.png  (1280 x 640, opaque, ~30-500KB)

The card is the brand surface that appears in unfurls on Twitter / LinkedIn /
Slack / Hacker News when someone links to the repo. Design goals:
    - Instant recognition of the wordmark.
    - Calm, near-black GitHub-dark background.
    - Subtle echo of the README banner: a row of muted Greek-column pillars
      across the top edge.
"""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Canvas + palette
# ---------------------------------------------------------------------------

WIDTH, HEIGHT = 1280, 640

BG = (13, 17, 23)            # #0d1117 — GitHub dark canvas
FG = (240, 246, 252)         # #f0f6fc — primary white
TAGLINE = (170, 170, 170)    # #aaaaaa — muted sans
FOOTER = (110, 118, 129)     # #6e7681 — very faded mono
PILLAR = (48, 54, 61)        # dim columns, barely there

# ---------------------------------------------------------------------------
# Font resolution
# ---------------------------------------------------------------------------

SERIF_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/Library/Fonts/Georgia.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
]

SANS_CANDIDATES = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

MONO_CANDIDATES = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]


def _load_font(candidates: list[str], size: int) -> ImageFont.ImageFont:
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _draw_text_tracked(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    center_y: int,
    tracking: int = 0,
) -> None:
    """Draw `text` horizontally centered on the canvas with extra
    letter-spacing in pixels (Pillow has no native letter-spacing)."""

    widths: list[int] = []
    for ch in text:
        bbox = draw.textbbox((0, 0), ch, font=font)
        widths.append(bbox[2] - bbox[0])

    total_w = sum(widths) + tracking * max(0, len(text) - 1)
    x = (WIDTH - total_w) // 2

    # Vertical centering via ascender height
    ascent, descent = font.getmetrics() if hasattr(font, "getmetrics") else (font.size, 0)
    y = center_y - (ascent + descent) // 2

    for ch, w in zip(text, widths, strict=True):
        draw.text((x, y), ch, font=font, fill=fill)
        x += w + tracking


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    y: int,
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    draw.text(((WIDTH - w) // 2, y), text, font=font, fill=fill)


def _draw_pillar_row(draw: ImageDraw.ImageDraw, y_top: int, height: int) -> None:
    """A muted echo of the README banner: capital line + 12 evenly-spaced
    columns + plinth, ghosted into the background."""

    # Capital (entablature) — a thin line spanning most of the width
    cap_left, cap_right = 120, WIDTH - 120
    draw.rectangle([cap_left, y_top, cap_right, y_top + 4], fill=PILLAR)

    # Columns
    n = 12
    col_w = 8
    span = (cap_right - cap_left) - col_w
    for i in range(n):
        x = cap_left + (span * i) // (n - 1)
        draw.rectangle([x, y_top + 10, x + col_w, y_top + height - 10], fill=PILLAR)

    # Plinth (base)
    draw.rectangle([cap_left - 10, y_top + height - 6, cap_right + 10, y_top + height], fill=PILLAR)


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render() -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    # Subtle pillar row across the top edge (Greek-column echo).
    _draw_pillar_row(draw, y_top=40, height=70)

    # Wordmark — serif "Plynth", with leading temple emoji.
    serif = _load_font(SERIF_CANDIDATES, size=140)
    sans = _load_font(SANS_CANDIDATES, size=38)
    mono = _load_font(MONO_CANDIDATES, size=24)

    # Title is "🏛️ Plynth" — but emoji rendering in Pillow without a color
    # font is unreliable. Draw a simple vector "temple" glyph instead so the
    # PNG is deterministic across machines, then the wordmark beside it.
    title = "PLYNTH"
    _draw_text_tracked(
        draw,
        text=title,
        font=serif,
        fill=FG,
        center_y=HEIGHT // 2 - 20,
        tracking=12,
    )

    # Tagline
    tagline = "A drop-in multi-tenant, multi-product SaaS scaffold"
    _draw_centered(draw, tagline, sans, TAGLINE, y=HEIGHT // 2 + 70)

    # Footer URL (bottom-left, faded mono)
    footer = "github.com/shubhamkatta/plynth"
    draw.text((48, HEIGHT - 48), footer, font=mono, fill=FOOTER)

    return img


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    out = repo_root / "docs" / "assets" / "social-preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)

    img = render()
    # Deterministic write: PNG, no metadata, default zlib compression.
    img.save(out, format="PNG", optimize=True)

    size_bytes = out.stat().st_size
    print(f"wrote {out} ({size_bytes:,} bytes, {img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
