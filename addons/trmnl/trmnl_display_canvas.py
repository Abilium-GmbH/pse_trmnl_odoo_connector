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
import os

from PIL import Image, ImageDraw, ImageFont

_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))

# Bundled + system font paths (TrueType). Avoid PIL's bitmap default — it looks
# blocky on e-ink and unlike the design samples.
_FONT_REGULAR = (
    os.path.join(_MODULE_DIR, "static", "fonts", "DejaVuSans.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
)
_FONT_BOLD = (
    os.path.join(_MODULE_DIR, "static", "fonts", "DejaVuSans-Bold.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
)


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load a TrueType font; falls back to regular weight then PIL default."""
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

# Threshold for list layout: map anti-aliased grays to pure B/W (no Floyd noise).
# Kanban/calendar/graph pass binarize=False to preserve column rules and greys.
EINK_BINARIZE_THRESHOLD = 200

# ---------------------------------------------------------------------------
# Layout geometry — shared constants used by render model methods and tests
# ---------------------------------------------------------------------------
LIST_HEADER_PAD_TOP = 10
_LIST_HEADER_LINE_GAP = 8
_LIST_HEADER_PAD_BOTTOM = 12
MARGIN_X = 16
ACCENT_W = 4

# Calendar grid geometry (month view at default 800 px width)
CALENDAR_HEADER_H = 36
CALENDAR_DOW_H = 24
CALENDAR_GRID_TOP = CALENDAR_HEADER_H + CALENDAR_DOW_H   # 60
CALENDAR_COLS = 7
CALENDAR_COL_W = DISPLAY_WIDTH // CALENDAR_COLS           # 114

# Typography scale
FONT_TITLE = 15
FONT_LIST_TITLE = 20
FONT_SECTION = 13
FONT_PRIMARY = 14
FONT_META = 11
FONT_SMALL = 10
FONT_EMPTY = 14
FONT_CHART_SUMMARY = 11

STATUS_MARKERS = {
    "overdue": "[!] ",
    "progress": "[~] ",
    "done": "[v] ",
}

ACCENT_FILL = {
    "overdue": EINK_INK,
    "progress": 72,
    "done": 160,
    "default": EINK_RULE_FAINT,
}


# ---------------------------------------------------------------------------
# Shared PIL drawing helpers used by list, kanban, calendar, and graph renders
# ---------------------------------------------------------------------------

def save_png(img: Image.Image) -> bytes:
    """Serialize a PIL image to PNG bytes."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def trunc(draw, text: str, font, max_px: int) -> str:
    """Truncate *text* with an ellipsis so it fits within *max_px* pixels."""
    text = str(text)
    if text_width(draw, text, font) <= max_px:
        return text
    ell = "…"
    if text_width(draw, ell, font) > max_px:
        return ""
    while text and text_width(draw, text + ell, font) > max_px:
        text = text[:-1]
    return text + ell if text else ell


def draw_list_header(draw, w: int, title: str) -> int:
    """Large bold title on white, black rule underneath. Returns y below header."""
    font = load_font(FONT_LIST_TITLE, bold=True)
    y = LIST_HEADER_PAD_TOP
    if title:
        t = trunc(draw, title, font, w - 2 * MARGIN_X)
        draw.text((MARGIN_X, y), t, fill=EINK_INK, font=font)
        bb = draw.textbbox((0, 0), t, font=font)
        line_y = y + (bb[3] - bb[1]) + _LIST_HEADER_LINE_GAP
        draw.line([(MARGIN_X, line_y), (w - MARGIN_X, line_y)], fill=EINK_INK, width=1)
        return line_y + _LIST_HEADER_PAD_BOTTOM
    return LIST_HEADER_PAD_TOP + _LIST_HEADER_PAD_BOTTOM


def draw_kanban_column_header(
    draw,
    x0: int,
    col_w: int,
    y: int,
    label: str,
    *,
    line_gap: int = 4,
    pad_bottom: int = 6,
) -> int:
    """Stage title + rule within one kanban column. Returns y below rule."""
    font = load_font(FONT_SECTION, bold=True)
    pad = 4
    text = trunc(draw, label, font, col_w - 2 * pad)
    draw.text((x0 + pad, y), text, fill=EINK_INK, font=font)
    bb = draw.textbbox((0, 0), text, font=font)
    line_y = y + (bb[3] - bb[1]) + line_gap
    draw.line([(x0 + pad, line_y), (x0 + col_w - pad, line_y)], fill=EINK_INK, width=1)
    return line_y + pad_bottom


def draw_empty_centered(draw, w: int, y0: int, y1: int, message: str) -> None:
    """Draw *message* centered in the rect (0, y0, w, y1)."""
    font = load_font(FONT_EMPTY)
    bb = draw.textbbox((0, 0), message, font=font)
    tw = bb[2] - bb[0]
    th = bb[3] - bb[1]
    cx = w // 2
    cy = (y0 + y1) // 2
    draw.text((cx - tw // 2, cy - th // 2 - bb[1]), message, fill=EINK_INK_SOFT, font=font)


def draw_overflow_footer(draw, w: int, y: int, more_count: int) -> None:
    """Draw '+N more' right-aligned at y."""
    if more_count <= 0:
        return
    font = load_font(FONT_SMALL)
    msg = f"+{more_count} more"
    tw = text_width(draw, msg, font)
    draw.text((w - MARGIN_X - tw, y), msg, fill=EINK_INK_SOFT, font=font)


def draw_chart_header(draw, w: int, title: str, *, height: int = 36) -> int:
    """Centered title on dark band (bar/line charts). Returns y below band."""
    draw.rectangle([0, 0, w - 1, height - 1], fill=EINK_HEADER_FILL)
    draw.line([(0, height - 1), (w - 1, height - 1)], fill=EINK_RULE_FAINT, width=1)
    font = load_font(FONT_TITLE, bold=True)
    title = str(title) if title else "Chart"
    tw = text_width(draw, title, font)
    bb = draw.textbbox((0, 0), title, font=font)
    th = bb[3] - bb[1]
    draw.text(((w - tw) // 2, (height - th) // 2 - bb[1]), title, fill=EINK_HEADER_TEXT, font=font)
    return height


def draw_summary_lines(draw, w: int, y0: int, lines: list) -> int:
    """Soft gray summary rows under chart title. Returns y below last line."""
    if not lines:
        return y0
    font = load_font(FONT_CHART_SUMMARY)
    y = y0 + 4
    for line in lines:
        text = trunc(draw, line, font, w - 2 * MARGIN_X)
        draw.text((MARGIN_X, y), text, fill=EINK_INK_SOFT, font=font)
        bb = draw.textbbox((0, 0), text, font=font)
        y += (bb[3] - bb[1]) + 3
    return y + 2


def binarize_for_eink(img: Image.Image, threshold: int = EINK_BINARIZE_THRESHOLD) -> Image.Image:
    """Convert grayscale to pure black/white without error-diffusion dither."""
    t = int(threshold)
    return img.point(lambda p, cut=t: 255 if p >= cut else 0, mode="L")


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
    *,
    binarize: bool = True,
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
        if binarize:
            # Pure B/W (threshold only). Matches TRMNL 1-bit output better than
            # Floyd–Steinberg and keeps form preview === device download bytes.
            out = binarize_for_eink(out)
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
