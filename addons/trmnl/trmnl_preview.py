"""Generic list/table preview renderer for TRMNL e-ink displays.

Pure Python — no Odoo imports. Receives already-extracted string data
and returns PNG bytes. Keeps PIL logic entirely outside the ORM layer.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

from . import trmnl_display_canvas as _canvas

DISPLAY_WIDTH = _canvas.DISPLAY_WIDTH
DISPLAY_HEIGHT = _canvas.CONTENT_HEIGHT

# Pull palette from shared canvas tokens for cohesion with other renderers.
_BG = _canvas.EINK_WHITE
_FG = _canvas.EINK_INK
_HEADER_BG = _canvas.EINK_HEADER_FILL
_HEADER_FG = _canvas.EINK_HEADER_TEXT
_STRIPE = _canvas.EINK_ROW_ALT
_COL_RULE = _canvas.EINK_RULE
_HEADER_RULE = _canvas.EINK_RULE_FAINT
_OUTLINE = _canvas.EINK_RULE_FAINT

_MARGIN_X = 24
_CELL_PAD_X = 8
_HEADER_H = 44
_ROW_H = 32
_FONT_HEADER = 15
_FONT_CELL = 13


def _trunc(draw: ImageDraw.ImageDraw, text: str, font, max_px: int) -> str:
    text = str(text)
    if _canvas.text_width(draw, text, font) <= max_px:
        return text
    ell = "…"
    if _canvas.text_width(draw, ell, font) > max_px:
        return ""
    while text and _canvas.text_width(draw, text + ell, font) > max_px:
        text = text[:-1]
    return text + ell if text else ell


def render_list_preview(rows: list[list[str]], field_labels: list[str]) -> bytes:
    """Render a list of string rows as a grayscale 800×CONTENT_HEIGHT PNG.

    The profile composites this into a full 800×480 frame with a footer strip.

    :param rows: table data — each inner list is one row of cell strings.
    :param field_labels: column headers — same length as each row.
    :return: PNG file content as raw bytes.
    """
    img = Image.new("L", (DISPLAY_WIDTH, DISPLAY_HEIGHT), _BG)
    draw = ImageDraw.Draw(img)

    font_header = _canvas.load_font(_FONT_HEADER, bold=True)
    font_cell = _canvas.load_font(_FONT_CELL)

    n_cols = max(len(field_labels), 1)
    inner_w = DISPLAY_WIDTH - 2 * _MARGIN_X
    col_w = inner_w // n_cols

    # Header bar + subtle bottom edge (separates title from data)
    draw.rectangle([0, 0, DISPLAY_WIDTH, _HEADER_H], fill=_HEADER_BG)
    draw.line(
        [(0, _HEADER_H - 1), (DISPLAY_WIDTH - 1, _HEADER_H - 1)],
        fill=_HEADER_RULE,
        width=1,
    )

    for i, raw_label in enumerate(field_labels):
        x = _MARGIN_X + i * col_w + _CELL_PAD_X
        label = _trunc(draw, str(raw_label), font_header, col_w - 2 * _CELL_PAD_X)
        bbox = draw.textbbox((0, 0), label, font=font_header)
        th = bbox[3] - bbox[1]
        y = (_HEADER_H - th) // 2 - bbox[1]
        draw.text((x, y), label, fill=_HEADER_FG, font=font_header)

    # Column guides (below header)
    for i in range(1, n_cols):
        x = _MARGIN_X + i * col_w
        draw.line(
            [(x, _HEADER_H), (x, DISPLAY_HEIGHT - 2)],
            fill=_COL_RULE,
            width=1,
        )

    max_rows = (DISPLAY_HEIGHT - _HEADER_H) // _ROW_H
    for row_idx, row in enumerate(rows[:max_rows]):
        y_top = _HEADER_H + row_idx * _ROW_H
        if row_idx % 2 == 1:
            draw.rectangle([0, y_top, DISPLAY_WIDTH, y_top + _ROW_H], fill=_STRIPE)

        # Light row baseline (e-ink friendly rhythm)
        if row_idx > 0:
            draw.line(
                [(0, y_top), (DISPLAY_WIDTH - 1, y_top)],
                fill=_HEADER_RULE,
                width=1,
            )

        for col_idx, cell in enumerate(row):
            x = _MARGIN_X + col_idx * col_w + _CELL_PAD_X
            max_cell = col_w - 2 * _CELL_PAD_X
            t = _trunc(draw, cell, font_cell, max_cell)
            bbox = draw.textbbox((0, 0), t, font=font_cell)
            th = bbox[3] - bbox[1]
            y_text = y_top + (_ROW_H - th) // 2 - bbox[1]
            draw.text((x, y_text), t, fill=_FG, font=font_cell)

    draw.rectangle(
        [0, 0, DISPLAY_WIDTH - 1, DISPLAY_HEIGHT - 1],
        outline=_OUTLINE,
        width=1,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
