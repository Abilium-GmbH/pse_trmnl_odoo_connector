"""Horizontal bar-chart renderer for TRMNL e-ink displays.

No Odoo ORM imports. Receives pre-aggregated bar data and returns PNG bytes.
The Odoo profile model handles all data loading; this module only handles
PIL rendering.

Defaults to 800×CONTENT_HEIGHT (standard TRMNL device). Pass ``width`` and
``content_height`` to ``render_graph_preview`` to render at the device's
actual reported resolution.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw

from . import trmnl_display_canvas as _canvas

# ── Geometry ────────────────────────────────────────────────────────────────
HEADER_H = 36
_MARGIN_L = 20
_MARGIN_R = 16
_LABEL_COL_W = 180
_VALUE_COL_W = 60
_BAR_PAD_Y = 6
_BAR_GAP_X = 8
_MIN_BAR_PX = 2

# ── Font sizes ───────────────────────────────────────────────────────────────
_FONT_TITLE = 15
_FONT_LABEL = 12
_FONT_VALUE = 11
_FONT_NODATA = 15

# ── Palette (from shared canvas tokens) ─────────────────────────────────────
_BG = _canvas.EINK_WHITE
_INK = _canvas.EINK_INK
_SOFT = _canvas.EINK_INK_SOFT
_STRIPE = _canvas.EINK_ROW_ALT
_HEADER_BG = _canvas.EINK_HEADER_FILL
_HEADER_FG = _canvas.EINK_HEADER_TEXT
_RULE_FAINT = _canvas.EINK_RULE_FAINT


def _trunc(draw: ImageDraw.ImageDraw, text: str, font, max_px: int) -> str:
    text = str(text)
    if _canvas.text_width(draw, text, font) <= max_px:
        return text
    ell = "…"
    if _canvas.text_width(draw, ell, font) > max_px:
        return ""
    while text and _canvas.text_width(draw, text + ell, font) > max_px:
        text = text[:-1]
    return (text + ell) if text else ell


def render_graph_preview(
    bars: list[dict],
    title: str,
    measure_label: str,
    *,
    width: int | None = None,
    content_height: int | None = None,
) -> bytes:
    """Render a horizontal bar chart as a grayscale PNG.

    :param bars: aggregated data — list of ``{"label": str, "value": float}``,
        sorted by the caller, limited to at most ``graph_max_groups`` entries.
    :param title: chart title shown in the dark header band.
    :param measure_label: human-readable measure name (e.g. "Count" or
        the field description), shown as a subtle sub-header.
    :param width: canvas width in pixels (default: DISPLAY_WIDTH).
    :param content_height: canvas height in pixels (default: CONTENT_HEIGHT).
    :return: PNG bytes.
    """
    w = width or _canvas.DISPLAY_WIDTH
    h = content_height or _canvas.CONTENT_HEIGHT

    img = Image.new("L", (w, h), _BG)
    draw = ImageDraw.Draw(img)

    font_title = _canvas.load_font(_FONT_TITLE, bold=True)
    font_label = _canvas.load_font(_FONT_LABEL)
    font_value = _canvas.load_font(_FONT_VALUE)
    font_nodata = _canvas.load_font(_FONT_NODATA)

    # Header band
    draw.rectangle([0, 0, w - 1, HEADER_H - 1], fill=_HEADER_BG)
    draw.line([(0, HEADER_H - 1), (w - 1, HEADER_H - 1)], fill=_RULE_FAINT, width=1)
    title_text = str(title) if title else "Graph"
    t_tw = _canvas.text_width(draw, title_text, font_title)
    t_bb = draw.textbbox((0, 0), title_text, font=font_title)
    t_th = t_bb[3] - t_bb[1]
    draw.text(
        ((w - t_tw) // 2, (HEADER_H - t_th) // 2 - t_bb[1]),
        title_text,
        fill=_HEADER_FG,
        font=font_title,
    )

    bars_top = HEADER_H
    bars_h = h - bars_top

    if not bars:
        nd = "No data"
        nd_bb = draw.textbbox((0, 0), nd, font=font_nodata)
        nd_w = nd_bb[2] - nd_bb[0]
        nd_h = nd_bb[3] - nd_bb[1]
        draw.text(
            ((w - nd_w) // 2, bars_top + (bars_h - nd_h) // 2 - nd_bb[1]),
            nd,
            fill=_SOFT,
            font=font_nodata,
        )
        draw.rectangle([0, 0, w - 1, h - 1], outline=_RULE_FAINT, width=1)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    n = len(bars)
    row_h = max(18, bars_h // n)
    max_visible = bars_h // row_h
    visible = bars[:max_visible]
    n_vis = len(visible)

    # Layout columns
    label_right = _MARGIN_L + _LABEL_COL_W
    value_left = w - _MARGIN_R - _VALUE_COL_W
    bar_left = label_right + _BAR_GAP_X
    bar_right = value_left - _BAR_GAP_X
    max_bar_w = max(1, bar_right - bar_left)

    max_val = max((b.get("value") or 0) for b in visible) if visible else 0

    def _fmt(v: float) -> str:
        if v == int(v):
            return str(int(v))
        return f"{v:.1f}"

    for row_i, bar in enumerate(visible):
        y0 = bars_top + row_i * row_h
        y1 = y0 + row_h - 1

        if row_i % 2 == 1:
            draw.rectangle([0, y0, w - 1, y1], fill=_STRIPE)
        if row_i > 0:
            draw.line([(0, y0), (w - 1, y0)], fill=_RULE_FAINT, width=1)

        # Label
        lbl = _trunc(draw, str(bar.get("label", "")), font_label, _LABEL_COL_W - 4)
        l_bb = draw.textbbox((0, 0), lbl, font=font_label)
        l_h = l_bb[3] - l_bb[1]
        draw.text(
            (_MARGIN_L, y0 + (row_h - l_h) // 2 - l_bb[1]),
            lbl,
            fill=_INK,
            font=font_label,
        )

        # Bar
        raw = bar.get("value") or 0
        if max_val > 0:
            bar_px = max(_MIN_BAR_PX, int(max_bar_w * raw / max_val)) if raw > 0 else 0
        else:
            bar_px = 0
        bar_y0 = y0 + _BAR_PAD_Y
        bar_y1 = y1 - _BAR_PAD_Y
        if bar_px > 0 and bar_y1 > bar_y0:
            draw.rectangle(
                [bar_left, bar_y0, bar_left + bar_px - 1, bar_y1],
                fill=_INK,
            )

        # Value
        val_str = _fmt(raw)
        v_bb = draw.textbbox((0, 0), val_str, font=font_value)
        v_w = v_bb[2] - v_bb[0]
        v_h = v_bb[3] - v_bb[1]
        draw.text(
            (value_left + (_VALUE_COL_W - v_w) // 2, y0 + (row_h - v_h) // 2 - v_bb[1]),
            val_str,
            fill=_INK,
            font=font_value,
        )

    # Overflow indicator
    overflow = n - n_vis
    if overflow > 0 and n_vis > 0:
        more_y = bars_top + n_vis * row_h + 2
        if more_y < h - 4:
            more_text = f"+{overflow} more"
            m_bb = draw.textbbox((0, 0), more_text, font=font_value)
            draw.text(
                (_MARGIN_L, more_y - m_bb[1]),
                more_text,
                fill=_SOFT,
                font=font_value,
            )

    draw.rectangle([0, 0, w - 1, h - 1], outline=_RULE_FAINT, width=1)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
