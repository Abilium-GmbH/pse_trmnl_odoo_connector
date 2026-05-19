"""TRMNL profile rendering — bar chart and line chart drawing methods.

PIL drawing for both graph types lives here as static methods on the
trmnl.profile mixin.  The ORM data-aggregation methods (_load_graph_data,
_load_line_data) live in trmnl_profile_render.py; this file only handles
the PIL drawing step that converts aggregated data into PNG bytes.

How graph rendering reaches the device
----------------------------------------
1. Device polls ``/api/display``.
2. ``TrmnlDeviceDisplayMixin.build_display_response()`` triggers
   ``profile._render_and_store_preview()``.
3. ``_render_and_store_preview`` calls ``_dispatch_renderer``.
4. For ``trmnl_layout == 'graph'``, ``_dispatch_renderer`` aggregates ORM
   records into bar/point lists and then calls ``self._render_bar_chart_png()``
   or ``self._render_line_chart_png()`` (defined here).
5. The returned PNG bytes are composited with the footer strip by
   ``_finalize_display_image`` and stored in ``preview_image``.
6. The device downloads the stored PNG from ``/api/profile/image/<id>``.
"""
from __future__ import annotations

import io
import math

from PIL import Image, ImageDraw

from odoo import models

from odoo.addons.trmnl import trmnl_display_canvas as _canvas

# ── Shared chart constants ────────────────────────────────────────────────────
_HEADER_H = 36       # dark title band shared by both chart types
_MARGIN_R = 16       # right margin
_FONT_TITLE = 15
_FONT_NODATA = 15
_BG = _canvas.EINK_WHITE
_INK = _canvas.EINK_INK
_SOFT = _canvas.EINK_INK_SOFT
_RULE = _canvas.EINK_RULE
_RULE_FAINT = _canvas.EINK_RULE_FAINT
_STRIPE = _canvas.EINK_ROW_ALT
_HEADER_BG = _canvas.EINK_HEADER_FILL
_HEADER_FG = _canvas.EINK_HEADER_TEXT

# ── Bar chart geometry ────────────────────────────────────────────────────────
_BAR_MARGIN_L = 20
_BAR_LABEL_COL_W = 180
_BAR_VALUE_COL_W = 60
_BAR_PAD_Y = 6
_BAR_GAP_X = 8
_BAR_MIN_PX = 2
_BAR_FONT_LABEL = 12
_BAR_FONT_VALUE = 11

# ── Line chart geometry ───────────────────────────────────────────────────────
_LINE_MARGIN_L = 62    # y-axis label area width
_LINE_MARGIN_TOP = 14  # headroom above highest data point
_LINE_MARGIN_BOT = 34  # x-axis label area height
_LINE_W = 2
_LINE_POINT_R = 3      # filled-circle radius for regular data-point markers
_LINE_ENDPOINT_R = 5   # larger radius for the first and last points
_LINE_YTICK_N = 4      # number of y-axis grid intervals
_LINE_FONT_AXIS = 10
_AREA_FILL = 248       # under-curve fill colour


# ── Private helpers ───────────────────────────────────────────────────────────

def _trunc_chart(draw, text: str, font, max_px: int) -> str:
    text = str(text)
    if _canvas.text_width(draw, text, font) <= max_px:
        return text
    ell = "…"
    if _canvas.text_width(draw, ell, font) > max_px:
        return ""
    while text and _canvas.text_width(draw, text + ell, font) > max_px:
        text = text[:-1]
    return (text + ell) if text else ell


def _draw_nodata_centered(
    draw,
    text: str,
    area_rect: tuple[int, int, int, int],
    font,
) -> None:
    left, top, right, bottom = area_rect
    cx = (left + right) // 2
    cy = (top + bottom) // 2
    bb = draw.textbbox((0, 0), text, font=font)
    tw = bb[2] - bb[0]
    th = bb[3] - bb[1]
    draw.text((cx - tw // 2, cy - th // 2 - bb[1]), text, fill=_SOFT, font=font)


def _nice_max(val: float) -> float:
    """Round *val* up to a 'nice' y-axis ceiling."""
    if val <= 0:
        return 10.0
    exp = math.floor(math.log10(val))
    magnitude = 10 ** exp
    for factor in (1, 2, 5, 10, 20):
        candidate = factor * magnitude
        if candidate >= val:
            return float(candidate)
    return float(math.ceil(val * 1.1))


def _fmt_y(val: float) -> str:
    """Format a y-axis tick value, abbreviating large numbers (k / M)."""
    if val >= 1_000_000:
        v = val / 1_000_000
        return f"{v:.0f}M" if v == int(v) else f"{v:.1f}M"
    if val >= 1_000:
        v = val / 1_000
        return f"{v:.0f}k" if v == int(v) else f"{v:.1f}k"
    return str(int(val)) if val == int(val) else f"{val:.1f}"


def _fmt_bar_value(v: float) -> str:
    return str(int(v)) if v == int(v) else f"{v:.1f}"


# ── Model mixin ───────────────────────────────────────────────────────────────

class TrmnlProfileRenderGraphMixin(models.Model):
    """Adds bar chart and line chart PIL rendering to trmnl.profile."""

    _inherit = "trmnl.profile"

    # ── Bar chart renderer ────────────────────────────────────────────────────

    @staticmethod
    def _render_bar_chart_png(
        bars: list[dict],
        title: str,
        measure_label: str,
        *,
        width: int | None = None,
        content_height: int | None = None,
        summary_lines: list[str] | None = None,
        empty_message: str = "No data for selected period",
    ) -> bytes:
        """Render a horizontal bar chart as a grayscale PNG.

        ``bars`` is a list of ``{"label": str, "value": float}`` dicts produced
        by ``_load_graph_data()``, already sorted and capped at ``graph_max_groups``.

        ``width`` / ``content_height`` come from the linked device record;
        falls back to 800×CONTENT_HEIGHT when not yet reported.
        """
        w = width or _canvas.DISPLAY_WIDTH
        h = content_height or _canvas.CONTENT_HEIGHT

        img = Image.new("L", (w, h), _BG)
        draw = ImageDraw.Draw(img)

        font_label = _canvas.load_font(_BAR_FONT_LABEL)
        font_value = _canvas.load_font(_BAR_FONT_VALUE)
        font_nodata = _canvas.load_font(_FONT_NODATA)

        # Dark header band with centered title.
        bars_top = _canvas.draw_chart_header(draw, w, str(title) if title else "Graph")
        if summary_lines:
            bars_top = _canvas.draw_summary_lines(draw, w, bars_top, summary_lines)
        bars_h = h - bars_top

        if not bars:
            _draw_nodata_centered(draw, empty_message, (0, bars_top, w, h), font_nodata)
            draw.rectangle([0, 0, w - 1, h - 1], outline=_RULE_FAINT, width=1)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()

        n = len(bars)
        row_h = max(18, bars_h // n)
        max_visible = bars_h // row_h
        visible = bars[:max_visible]
        n_vis = len(visible)

        label_right = _BAR_MARGIN_L + _BAR_LABEL_COL_W
        value_left = w - _MARGIN_R - _BAR_VALUE_COL_W
        bar_left = label_right + _BAR_GAP_X
        bar_right = value_left - _BAR_GAP_X
        max_bar_w = max(1, bar_right - bar_left)
        max_val = max((b.get("value") or 0) for b in visible) if visible else 0

        for row_i, bar in enumerate(visible):
            y0 = bars_top + row_i * row_h
            y1 = y0 + row_h - 1

            if row_i % 2 == 1:
                draw.rectangle([0, y0, w - 1, y1], fill=_STRIPE)
            if row_i > 0:
                draw.line([(0, y0), (w - 1, y0)], fill=_RULE_FAINT, width=1)

            lbl = _trunc_chart(draw, str(bar.get("label", "")), font_label, _BAR_LABEL_COL_W - 4)
            l_bb = draw.textbbox((0, 0), lbl, font=font_label)
            l_h = l_bb[3] - l_bb[1]
            draw.text(
                (_BAR_MARGIN_L, y0 + (row_h - l_h) // 2 - l_bb[1]),
                lbl,
                fill=_INK,
                font=font_label,
            )

            raw = bar.get("value") or 0
            if max_val > 0:
                bar_px = max(_BAR_MIN_PX, int(max_bar_w * raw / max_val)) if raw > 0 else 0
            else:
                bar_px = 0
            bar_y0 = y0 + _BAR_PAD_Y
            bar_y1 = y1 - _BAR_PAD_Y
            if bar_px > 0 and bar_y1 > bar_y0:
                draw.rectangle([bar_left, bar_y0, bar_left + bar_px - 1, bar_y1], fill=_INK)

            val_str = _fmt_bar_value(raw)
            v_bb = draw.textbbox((0, 0), val_str, font=font_value)
            v_w = v_bb[2] - v_bb[0]
            v_h = v_bb[3] - v_bb[1]
            draw.text(
                (value_left + (_BAR_VALUE_COL_W - v_w) // 2, y0 + (row_h - v_h) // 2 - v_bb[1]),
                val_str,
                fill=_INK,
                font=font_value,
            )

        overflow = n - n_vis
        if overflow > 0 and n_vis > 0:
            more_y = bars_top + n_vis * row_h + 2
            if more_y < h - 4:
                more_text = f"+{overflow} more"
                m_bb = draw.textbbox((0, 0), more_text, font=font_value)
                draw.text((_BAR_MARGIN_L, more_y - m_bb[1]), more_text, fill=_SOFT, font=font_value)

        draw.rectangle([0, 0, w - 1, h - 1], outline=_RULE_FAINT, width=1)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    # ── Line chart renderer ───────────────────────────────────────────────────

    @staticmethod
    def _render_line_chart_png(
        points: list[dict],
        title: str,
        measure_label: str,
        *,
        width: int | None = None,
        content_height: int | None = None,
        summary_lines: list[str] | None = None,
        empty_message: str = "No data for selected period",
    ) -> bytes:
        """Render a single-series time-series line chart as a grayscale PNG.

        ``points`` is a list of ``{"label": str, "value": float}`` dicts produced
        by ``_load_line_data()``, sorted chronologically and capped at
        ``line_max_points``.

        ``width`` / ``content_height`` come from the linked device record;
        falls back to 800×CONTENT_HEIGHT when not yet reported.
        """
        w = width or _canvas.DISPLAY_WIDTH
        h = content_height or _canvas.CONTENT_HEIGHT

        img = Image.new("L", (w, h), _BG)
        draw = ImageDraw.Draw(img)

        font_axis = _canvas.load_font(_LINE_FONT_AXIS)
        font_nodata = _canvas.load_font(_FONT_NODATA)

        # Dark header band with centered title.
        chart_top_base = _canvas.draw_chart_header(draw, w, str(title) if title else "Line Chart")
        if summary_lines:
            chart_top_base = _canvas.draw_summary_lines(draw, w, chart_top_base, summary_lines)

        chart_left = _LINE_MARGIN_L
        chart_right = w - _MARGIN_R
        chart_top = chart_top_base + _LINE_MARGIN_TOP
        chart_bot = h - _LINE_MARGIN_BOT
        chart_w = chart_right - chart_left
        chart_h = chart_bot - chart_top

        # Axes
        draw.line([(chart_left, chart_top), (chart_left, chart_bot)], fill=_RULE, width=1)
        draw.line([(chart_left, chart_bot), (chart_right, chart_bot)], fill=_RULE, width=1)

        if not points:
            _draw_nodata_centered(
                draw,
                empty_message,
                (chart_left, chart_top, chart_right, chart_bot),
                font_nodata,
            )
            draw.rectangle([0, 0, w - 1, h - 1], outline=_RULE_FAINT, width=1)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()

        # Y-axis grid and labels
        max_val = max(p["value"] for p in points)
        y_max = _nice_max(max_val)

        for i in range(_LINE_YTICK_N + 1):
            tick_val = y_max * i / _LINE_YTICK_N
            py = int(chart_bot - (tick_val / y_max) * chart_h)
            draw.line([(chart_left, py), (chart_right, py)], fill=_RULE_FAINT, width=1)
            draw.line([(chart_left - 3, py), (chart_left, py)], fill=_RULE, width=1)
            label = _fmt_y(tick_val)
            lb = draw.textbbox((0, 0), label, font=font_axis)
            lw = lb[2] - lb[0]
            lh = lb[3] - lb[1]
            draw.text((chart_left - 5 - lw, py - lh // 2 - lb[1]), label, fill=_INK, font=font_axis)

        # X-axis labels
        n = len(points)
        if n == 1:
            xs = [chart_left + chart_w // 2]
        else:
            xs = [int(chart_left + i * chart_w / (n - 1)) for i in range(n)]

        max_lw = max(_canvas.text_width(draw, p["label"], font_axis) for p in points) + 6
        max_visible = max(1, chart_w // max_lw) if max_lw > 0 else n
        stride = max(1, math.ceil(n / max_visible))

        for i, (p, px) in enumerate(zip(points, xs)):
            draw.line([(px, chart_bot), (px, chart_bot + 3)], fill=_RULE, width=1)
            if i % stride == 0 or i == n - 1:
                lbl = _trunc_chart(draw, p["label"], font_axis, max_lw + 6)
                lb = draw.textbbox((0, 0), lbl, font=font_axis)
                lw = lb[2] - lb[0]
                draw.text((px - lw // 2, chart_bot + 6 - lb[1]), lbl, fill=_INK, font=font_axis)

        # Data line, fill area, and point markers
        def _py(val: float) -> int:
            return int(chart_bot - (val / y_max) * chart_h)

        pixel_pts = [(xs[i], _py(points[i]["value"])) for i in range(n)]

        if n >= 2:
            area_poly = [(chart_left, chart_bot)] + pixel_pts + [(chart_right, chart_bot)]
            draw.polygon(area_poly, fill=_AREA_FILL)
            draw.line(pixel_pts, fill=_INK, width=_LINE_W + 1)

        for i, (px, py) in enumerate(pixel_pts):
            r = _LINE_ENDPOINT_R if (i == 0 or i == n - 1) else _LINE_POINT_R
            draw.ellipse([px - r, py - r, px + r, py + r], fill=_INK)
            if i == n - 1 and n > 1:
                draw.ellipse(
                    [px - r - 1, py - r - 1, px + r + 1, py + r + 1],
                    outline=_INK,
                    width=1,
                )

        if n == 1:
            val_lbl = _fmt_y(points[0]["value"])
            vb = draw.textbbox((0, 0), val_lbl, font=font_axis)
            vw = vb[2] - vb[0]
            draw.text(
                (pixel_pts[0][0] - vw // 2, pixel_pts[0][1] - _LINE_POINT_R - 12 - vb[1]),
                val_lbl,
                fill=_INK,
                font=font_axis,
            )

        draw.rectangle([0, 0, w - 1, h - 1], outline=_RULE_FAINT, width=1)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
