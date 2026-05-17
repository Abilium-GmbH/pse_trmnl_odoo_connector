"""Dashboard-style list renderer for TRMNL e-ink displays.

No Odoo ORM imports. Receives pre-shaped row dicts and returns PNG bytes.
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
_ROW_H = 38
_OVERFLOW_RESERVE = 20


def render_list_preview(
    items: list[dict],
    *,
    width: int | None = None,
    content_height: int | None = None,
    title: str = "",
    subtitle: str = "",
    total_count: int | None = None,
    empty_message: str = "No records match your filters",
) -> bytes:
    """Render glanceable list rows (primary + metadata), not a spreadsheet table.

    Each item: ``{"primary": str, "meta": str, "status": "overdue"|"progress"|"done"|""}``.
    """
    w = width or DISPLAY_WIDTH
    h = content_height or DISPLAY_HEIGHT

    img = Image.new("L", (w, h), _BG)
    draw = ImageDraw.Draw(img)

    font_primary = _canvas.load_font(_ui.FONT_PRIMARY, bold=True)
    font_meta = _canvas.load_font(_ui.FONT_META)

    top = _ui.draw_list_header(draw, w, title)

    if not items:
        _ui.draw_empty_centered(draw, w, top, h, empty_message)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    body_bottom = h - _OVERFLOW_RESERVE
    max_rows = max(0, (body_bottom - top) // _ROW_H)
    visible = items[:max_rows]
    cap = total_count if total_count is not None else len(items)
    more = max(0, cap - len(visible))
    text_w = w - _ui.MARGIN_X - _ui.ACCENT_W - 6

    for idx, item in enumerate(visible):
        y0 = top + idx * _ROW_H
        status = (item.get("status") or "").strip().lower()
        accent = _ui.ACCENT_FILL.get(status, _ui.ACCENT_FILL["default"])
        draw.rectangle(
            [_ui.MARGIN_X, y0 + 4, _ui.MARGIN_X + _ui.ACCENT_W - 1, y0 + _ROW_H - 5],
            fill=accent,
        )

        marker = _ui.STATUS_MARKERS.get(status, "")
        primary = marker + str(item.get("primary") or "")
        meta = str(item.get("meta") or "")

        ptext = _ui.trunc(draw, primary, font_primary, text_w)
        draw.text(
            (_ui.MARGIN_X + _ui.ACCENT_W + 6, y0 + 5),
            ptext,
            fill=_INK,
            font=font_primary,
        )
        if meta:
            mtext = _ui.trunc(draw, meta, font_meta, text_w)
            draw.text(
                (_ui.MARGIN_X + _ui.ACCENT_W + 6, y0 + 22),
                mtext,
                fill=_canvas.EINK_INK_SOFT,
                font=font_meta,
            )

        if idx > 0:
            draw.line(
                [(_ui.MARGIN_X, y0), (w - _ui.MARGIN_X, y0)],
                fill=_canvas.EINK_RULE_FAINT,
                width=1,
            )

    if more > 0:
        _ui.draw_overflow_footer(draw, w, top + len(visible) * _ROW_H + 2, more)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
