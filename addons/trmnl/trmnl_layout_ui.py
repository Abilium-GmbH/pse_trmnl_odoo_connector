"""Shared PIL drawing helpers for TRMNL dashboard layouts (list, kanban, calendar, graph).

No Odoo imports. Layout renderers import typography, truncation, and band drawing
from here plus palette constants from ``trmnl_display_canvas``.
"""
from __future__ import annotations

from PIL import ImageDraw

from . import trmnl_display_canvas as _c

# Typography scale
FONT_TITLE = 15
FONT_LIST_TITLE = 20
FONT_SECTION = 13
FONT_PRIMARY = 14
FONT_META = 11
FONT_SMALL = 10
FONT_EMPTY = 14
FONT_CHART_SUMMARY = 11

_LIST_HEADER_PAD_TOP = 10
_LIST_HEADER_LINE_GAP = 8
_LIST_HEADER_PAD_BOTTOM = 12
LIST_HEADER_PAD_TOP = _LIST_HEADER_PAD_TOP
MARGIN_X = 16
ACCENT_W = 4

STATUS_MARKERS = {
    "overdue": "[!] ",
    "progress": "[~] ",
    "done": "[v] ",
}

ACCENT_FILL = {
    "overdue": _c.EINK_INK,
    "progress": 72,
    "done": 160,
    "default": _c.EINK_RULE_FAINT,
}

_INK = _c.EINK_INK
_SOFT = _c.EINK_INK_SOFT
_HEADER_BG = _c.EINK_HEADER_FILL
_HEADER_FG = _c.EINK_HEADER_TEXT
_RULE = _c.EINK_RULE_FAINT


def trunc(draw: ImageDraw.ImageDraw, text: str, font, max_px: int) -> str:
    text = str(text)
    if _c.text_width(draw, text, font) <= max_px:
        return text
    ell = "…"
    if _c.text_width(draw, ell, font) > max_px:
        return ""
    while text and _c.text_width(draw, text + ell, font) > max_px:
        text = text[:-1]
    return text + ell if text else ell


def draw_list_header(draw: ImageDraw.ImageDraw, w: int, title: str) -> int:
    """List/kanban: large black title on white, black rule underneath. Returns y below header."""
    font = _c.load_font(FONT_LIST_TITLE, bold=True)
    y = _LIST_HEADER_PAD_TOP
    if title:
        t = trunc(draw, title, font, w - 2 * MARGIN_X)
        draw.text((MARGIN_X, y), t, fill=_INK, font=font)
        bb = draw.textbbox((0, 0), t, font=font)
        line_y = y + (bb[3] - bb[1]) + _LIST_HEADER_LINE_GAP
        draw.line([(MARGIN_X, line_y), (w - MARGIN_X, line_y)], fill=_INK, width=1)
        return line_y + _LIST_HEADER_PAD_BOTTOM
    return _LIST_HEADER_PAD_TOP + _LIST_HEADER_PAD_BOTTOM


def draw_kanban_column_header(
    draw: ImageDraw.ImageDraw,
    x0: int,
    col_w: int,
    y: int,
    label: str,
    *,
    line_gap: int = 4,
    pad_bottom: int = 6,
) -> int:
    """Stage title + black rule within one kanban column. Returns y below the rule."""
    font = _c.load_font(FONT_SECTION, bold=True)
    pad = 4
    text = trunc(draw, label, font, col_w - 2 * pad)
    draw.text((x0 + pad, y), text, fill=_INK, font=font)
    bb = draw.textbbox((0, 0), text, font=font)
    line_y = y + (bb[3] - bb[1]) + line_gap
    draw.line([(x0 + pad, line_y), (x0 + col_w - pad, line_y)], fill=_INK, width=1)
    return line_y + pad_bottom


def draw_empty_centered(
    draw: ImageDraw.ImageDraw,
    w: int,
    y0: int,
    y1: int,
    message: str,
) -> None:
    font = _c.load_font(FONT_EMPTY)
    bb = draw.textbbox((0, 0), message, font=font)
    tw = bb[2] - bb[0]
    th = bb[3] - bb[1]
    cx = w // 2
    cy = (y0 + y1) // 2
    draw.text((cx - tw // 2, cy - th // 2 - bb[1]), message, fill=_SOFT, font=font)


def draw_overflow_footer(
    draw: ImageDraw.ImageDraw,
    w: int,
    y: int,
    more_count: int,
) -> None:
    if more_count <= 0:
        return
    font = _c.load_font(FONT_SMALL)
    msg = f"+{more_count} more"
    tw = _c.text_width(draw, msg, font)
    draw.text((w - MARGIN_X - tw, y), msg, fill=_SOFT, font=font)


def draw_chart_header(
    draw: ImageDraw.ImageDraw,
    w: int,
    title: str,
    *,
    height: int = 36,
) -> int:
    """Centered title on dark band (bar/line charts)."""
    draw.rectangle([0, 0, w - 1, height - 1], fill=_HEADER_BG)
    draw.line([(0, height - 1), (w - 1, height - 1)], fill=_RULE, width=1)
    font = _c.load_font(FONT_TITLE, bold=True)
    title = str(title) if title else "Chart"
    tw = _c.text_width(draw, title, font)
    bb = draw.textbbox((0, 0), title, font=font)
    th = bb[3] - bb[1]
    draw.text(((w - tw) // 2, (height - th) // 2 - bb[1]), title, fill=_HEADER_FG, font=font)
    return height


def draw_summary_lines(
    draw: ImageDraw.ImageDraw,
    w: int,
    y0: int,
    lines: list[str],
) -> int:
    """Soft gray summary rows under chart title; returns y below last line."""
    if not lines:
        return y0
    font = _c.load_font(FONT_CHART_SUMMARY)
    y = y0 + 4
    for line in lines:
        text = trunc(draw, line, font, w - 2 * MARGIN_X)
        draw.text((MARGIN_X, y), text, fill=_SOFT, font=font)
        bb = draw.textbbox((0, 0), text, font=font)
        y += (bb[3] - bb[1]) + 3
    return y + 2
