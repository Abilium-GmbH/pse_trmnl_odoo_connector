"""Shared TRMNL e-ink canvas dimensions, palette, font helpers, and footer layout.

``DISPLAY_WIDTH`` (800) and ``DISPLAY_HEIGHT`` (480) are the default fallback
dimensions for standard TRMNL devices. The actual device dimensions are reported
by the firmware in the ``Width`` / ``Height`` request headers and stored on the
``trmnl.device`` record. All rendering functions accept ``width`` / ``content_height``
keyword arguments so they scale to the reported dimensions; these constants are
only used when the device has not yet reported its resolution.

Layout renderers (list, calendar month/week) produce an image of size
``(width, content_height)``. The profile composites that onto a full device
frame and draws the poll footer in the reserved bottom band.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

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


def draw_poll_footer_strip(
    draw,
    *,
    label: str | None,
    font,
    width: int | None = None,
    display_height: int | None = None,
) -> None:
    """Draw the separator, footer background, and optional centered poll label.

    ``label`` / ``font`` may be None when there is nothing to show; the reserved
    band is still painted for a consistent frame.

    ``width`` / ``display_height`` default to the module constants (800 / 480).
    Pass the device's reported dimensions to render at the correct resolution.
    """
    w = width or DISPLAY_WIDTH
    h = display_height or DISPLAY_HEIGHT
    separator_y = h - FOOTER_BAND_HEIGHT
    footer_body_top = separator_y + 1

    draw.line(
        [(0, separator_y), (w - 1, separator_y)],
        fill=FOOTER_SEPARATOR_GRAY,
        width=1,
    )
    draw.rectangle(
        [0, footer_body_top, w - 1, h - 1],
        fill=FOOTER_BAND_FILL,
    )
    if not label or font is None:
        return

    cx = w // 2
    band_bot = h - 1 - FOOTER_BOTTOM_INSET
    cy = (footer_body_top + band_bot) // 2

    try:
        try:
            draw.text((cx, cy), label, fill=EINK_FOOTER_TEXT, font=font, anchor="mm")
        except TypeError:
            bbox = draw.textbbox((0, 0), label, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            x = max(0, (w - tw) // 2)
            y = max(footer_body_top, cy - th // 2 - bbox[1])
            draw.text((x, y), label, fill=EINK_FOOTER_TEXT, font=font)
    except Exception:
        # Separator + fill already drawn; omit footer text rather than failing the request.
        pass


def composite_with_footer(
    content_png: bytes,
    device_w: int,
    device_h: int,
    label: str | None = None,
) -> bytes:
    """Paste content PNG onto a full device frame and draw the poll footer strip.

    *content_png* must be a grayscale PNG of size ``(device_w, device_h -
    FOOTER_BAND_HEIGHT)``.  Returns a grayscale PNG of size ``(device_w,
    device_h)``.  The optional *label* string is truncated to fit within the
    footer band width before rendering.  Returns *content_png* unchanged on
    any PIL error so the device always receives something displayable.
    """
    content_h = device_h - FOOTER_BAND_HEIGHT

    try:
        content = Image.open(io.BytesIO(content_png)).convert("L")
    except Exception:
        return content_png

    cw, ch = content.size
    if cw != device_w:
        return content_png
    if ch == device_h:
        content = content.crop((0, 0, device_w, content_h))
        ch = content_h
    elif ch != content_h:
        return content_png

    out = Image.new("L", (device_w, device_h), 255)
    out.paste(content, (0, 0))
    draw = ImageDraw.Draw(out)

    font = None
    if label:
        font = load_font(11)
        max_text_w = device_w - 16
        while len(label) > 8 and text_width(draw, label + "…", font) > max_text_w:
            label = label[:-1]
        if text_width(draw, label, font) > max_text_w:
            label = (label[: max(4, len(label) - 4)] + "…") if label else ""

    try:
        draw_poll_footer_strip(draw, label=label, font=font, width=device_w, display_height=device_h)
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        # Fallback: emit a valid frame with a plain separator and empty footer band.
        out2 = Image.new("L", (device_w, device_h), 255)
        out2.paste(content, (0, 0))
        d2 = ImageDraw.Draw(out2)
        separator_y = content_h
        d2.line(
            [(0, separator_y), (device_w - 1, separator_y)],
            fill=FOOTER_SEPARATOR_GRAY,
            width=1,
        )
        d2.rectangle(
            [0, separator_y + 1, device_w - 1, device_h - 1],
            fill=FOOTER_BAND_FILL,
        )
        buf2 = io.BytesIO()
        out2.save(buf2, format="PNG")
        return buf2.getvalue()
