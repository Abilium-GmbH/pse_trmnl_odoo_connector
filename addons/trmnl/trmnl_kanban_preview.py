"""TRMNL-native kanban renderer — horizontal stage columns for e-ink.

No Odoo ORM imports. Expects pre-grouped columns from the profile layer.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

from . import trmnl_display_canvas as _canvas
from . import trmnl_layout_ui as _ui

DISPLAY_WIDTH = _canvas.DISPLAY_WIDTH
DISPLAY_HEIGHT = _canvas.CONTENT_HEIGHT

_BG = _canvas.EINK_WHITE
_INK = _canvas.EINK_INK
_SOFT = _canvas.EINK_INK_SOFT

_MIN_COL_W = 168
_COL_RULE_W = 1
_ITEM_H = 14
_ITEM_BULLET = "· "
_STAGE_HEADER_H = 22
_OVERFLOW_RESERVE = 18
_MAX_COLUMNS = 5


def _column_layout(w: int, n_stages: int) -> tuple[int, int, list[int]]:
    """Return (n_visible, col_w, list of column x0 positions)."""
    inner = w - 2 * _ui.MARGIN_X
    max_fit = max(1, (inner + _COL_RULE_W) // (_MIN_COL_W + _COL_RULE_W))
    n_vis = min(n_stages, max_fit, _MAX_COLUMNS)
    rules = max(0, n_vis - 1)
    col_w = max(1, (inner - rules * _COL_RULE_W) // n_vis)
    xs = [_ui.MARGIN_X + i * (col_w + _COL_RULE_W) for i in range(n_vis)]
    return n_vis, col_w, xs


def render_kanban_preview(
    columns: list[dict],
    *,
    width: int | None = None,
    content_height: int | None = None,
    title: str = "",
    subtitle: str = "",
    empty_message: str = "No items match current filters",
) -> bytes:
    """Render horizontal kanban columns (stages side by side).

    Each column: ``{"name": str, "count": int, "items": [str, ...], "hidden": int}``.
    """
    w = width or DISPLAY_WIDTH
    h = content_height or DISPLAY_HEIGHT

    img = Image.new("L", (w, h), _BG)
    draw = ImageDraw.Draw(img)

    font_item = _canvas.load_font(_ui.FONT_SMALL)

    y0 = _ui.draw_list_header(draw, w, title)

    if not columns:
        _ui.draw_empty_centered(draw, w, y0, h, empty_message)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    y_body_top = y0 + 4
    y_max = h - _OVERFLOW_RESERVE
    body_h = max(0, y_max - y_body_top)
    max_items = max(1, (body_h - _STAGE_HEADER_H) // _ITEM_H)

    n_vis, col_w, col_xs = _column_layout(w, len(columns))
    visible = columns[:n_vis]
    hidden_cols = len(columns) - n_vis

    for i, col in enumerate(visible):
        x0 = col_xs[i]
        name = str(col.get("name") or "—").upper()
        count = int(col.get("count") or 0)
        cy = _ui.draw_kanban_column_header(draw, x0, col_w, y_body_top, f"{name} ({count})")

        items = list(col.get("items") or [])
        hidden = int(col.get("hidden") or 0)
        shown = items[:max_items]
        hidden += max(0, len(items) - len(shown))

        pad = 4
        max_text = col_w - 2 * pad - 6
        for line in shown:
            text = _ITEM_BULLET + _ui.trunc(draw, str(line), font_item, max_text)
            draw.text((x0 + pad, cy), text, fill=_INK, font=font_item)
            cy += _ITEM_H

        if hidden > 0:
            more = _ui.trunc(draw, f"+{hidden}", font_item, max_text)
            draw.text((x0 + pad, cy), more, fill=_SOFT, font=font_item)

        if i < len(visible) - 1:
            vx = x0 + col_w
            draw.line([(vx, y_body_top), (vx, y_max)], fill=_canvas.EINK_RULE_FAINT, width=1)

    if hidden_cols > 0:
        _ui.draw_overflow_footer(draw, w, y_max - 2, hidden_cols)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
