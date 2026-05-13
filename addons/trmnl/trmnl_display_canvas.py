"""Shared TRMNL e-ink canvas dimensions, palette, font helpers, and footer layout.

Layout renderers (list, calendar month/week) produce an image of size
``(DISPLAY_WIDTH, CONTENT_HEIGHT)``. The profile composites that onto a full
``800×480`` frame and draws the poll footer in the reserved bottom band.
"""
from __future__ import annotations

from PIL import ImageDraw, ImageFont

# System font paths tried in order when loading TrueType fonts.
_FONT_REGULAR = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
)
_FONT_BOLD = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
)


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load a system TrueType font; falls back to regular weight then PIL default."""
    for path in (_FONT_BOLD if bold else _FONT_REGULAR):
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            pass
    if bold:
        for path in _FONT_REGULAR:
            try:
                return ImageFont.truetype(path, size)
            except (IOError, OSError):
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    """Return the pixel width of *text* rendered with *font*."""
    try:
        return int(draw.textlength(text, font=font))
    except AttributeError:
        return draw.textsize(text, font=font)[0]

DISPLAY_WIDTH = 800
DISPLAY_HEIGHT = 480

# Bottom band: 1 px separator + text area (~25 px). Total 20–28 px as requested.
FOOTER_BAND_HEIGHT = 26
CONTENT_HEIGHT = DISPLAY_HEIGHT - FOOTER_BAND_HEIGHT

# Y coordinate of the horizontal separator (last content row is y < SEPARATOR_Y).
SEPARATOR_Y = CONTENT_HEIGHT
FOOTER_BODY_TOP = SEPARATOR_Y + 1

# Footer strip styling (e-ink friendly; tests may assert these values).
FOOTER_SEPARATOR_GRAY = 180
FOOTER_BAND_FILL = 248
# Keep footer glyphs slightly above the physical bottom edge.
FOOTER_BOTTOM_INSET = 3

# ---------------------------------------------------------------------------
# Shared e-ink palette & type rhythm (list / calendar PIL renderers)
# ---------------------------------------------------------------------------
EINK_WHITE = 255
EINK_BLACK = 0
EINK_INK = 24
EINK_INK_SOFT = 96
EINK_RULE = 188
EINK_RULE_FAINT = 218
EINK_ROW_ALT = 248
EINK_HEADER_FILL = 26
EINK_HEADER_TEXT = 255
EINK_FOOTER_TEXT = 28


def draw_poll_footer_strip(draw, *, label: str | None, font) -> None:
    """Draw the separator, footer background, and optional centered poll label.

    ``label`` / ``font`` may be None when there is nothing to show; the reserved
    band is still painted for a consistent frame.
    """
    draw.line(
        [(0, SEPARATOR_Y), (DISPLAY_WIDTH - 1, SEPARATOR_Y)],
        fill=FOOTER_SEPARATOR_GRAY,
        width=1,
    )
    draw.rectangle(
        [0, FOOTER_BODY_TOP, DISPLAY_WIDTH - 1, DISPLAY_HEIGHT - 1],
        fill=FOOTER_BAND_FILL,
    )
    if not label or font is None:
        return

    cx = DISPLAY_WIDTH // 2
    band_top = FOOTER_BODY_TOP
    band_bot = DISPLAY_HEIGHT - 1 - FOOTER_BOTTOM_INSET
    cy = (band_top + band_bot) // 2

    try:
        try:
            draw.text((cx, cy), label, fill=EINK_FOOTER_TEXT, font=font, anchor="mm")
        except TypeError:
            bbox = draw.textbbox((0, 0), label, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            x = max(0, (DISPLAY_WIDTH - tw) // 2)
            y = max(band_top, cy - th // 2 - bbox[1])
            draw.text((x, y), label, fill=EINK_FOOTER_TEXT, font=font)
    except Exception:
        # Separator + fill already drawn; omit footer text rather than failing the request.
        pass
