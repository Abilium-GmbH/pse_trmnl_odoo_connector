"""Generic list/table preview renderer for TRMNL e-ink displays.

Pure Python — no Odoo imports. Receives already-extracted string data
and returns PNG bytes. Keeps PIL logic entirely outside the ORM layer.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

DISPLAY_WIDTH = 800
DISPLAY_HEIGHT = 480

_BG = 255        # white background
_FG = 0          # black text / borders
_HEADER_BG = 0   # black header bar
_HEADER_FG = 255 # white header text
_STRIPE = 240    # light grey alternate row
_DIVIDER = 180   # column separator

_MARGIN = 16
_HEADER_H = 36
_ROW_H = 26
_FONT_SIZE = 14

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def render_list_preview(rows: list[list[str]], field_labels: list[str]) -> bytes:
    """Render a list of string rows as a black-and-white 800×480 PNG.

    :param rows: table data — each inner list is one row of cell strings.
    :param field_labels: column headers — same length as each row.
    :return: PNG file content as raw bytes.
    """
    img = Image.new("L", (DISPLAY_WIDTH, DISPLAY_HEIGHT), _BG)
    draw = ImageDraw.Draw(img)

    font = _load_font(_FONT_SIZE)

    n_cols = max(len(field_labels), 1)
    col_w = (DISPLAY_WIDTH - 2 * _MARGIN) // n_cols

    # Header bar
    draw.rectangle([0, 0, DISPLAY_WIDTH, _HEADER_H], fill=_HEADER_BG)
    for i, label in enumerate(field_labels):
        x = _MARGIN + i * col_w
        y = (_HEADER_H - _FONT_SIZE) // 2
        draw.text((x, y), _truncate(label, col_w), fill=_HEADER_FG, font=font)

    # Column dividers (skip first — that's the left margin)
    for i in range(1, n_cols):
        x = _MARGIN + i * col_w - 1
        draw.line([x, 0, x, DISPLAY_HEIGHT], fill=_DIVIDER, width=1)

    # Data rows
    max_rows = (DISPLAY_HEIGHT - _HEADER_H) // _ROW_H
    for row_idx, row in enumerate(rows[:max_rows]):
        y_top = _HEADER_H + row_idx * _ROW_H
        if row_idx % 2 == 1:
            draw.rectangle([0, y_top, DISPLAY_WIDTH, y_top + _ROW_H], fill=_STRIPE)
        y_text = y_top + (_ROW_H - _FONT_SIZE) // 2
        for col_idx, cell in enumerate(row):
            x = _MARGIN + col_idx * col_w
            draw.text((x, y_text), _truncate(str(cell), col_w), fill=_FG, font=font)

    # Outer border
    draw.rectangle([0, 0, DISPLAY_WIDTH - 1, DISPLAY_HEIGHT - 1], outline=_FG, width=1)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _truncate(text: str, col_width_px: int) -> str:
    """Trim text so it fits inside col_width_px pixels (rough char-width estimate)."""
    max_chars = max(4, col_width_px // 8)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"
