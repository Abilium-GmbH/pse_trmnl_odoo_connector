"""TRMNL profile rendering — list and kanban layout drawing methods.

PIL drawing for list and kanban views lives here as static methods on the
trmnl.profile mixin.  The ORM data-preparation methods (_prepare_list_items,
_prepare_kanban_columns) live in trmnl_profile.py and trmnl_profile_render.py;
this file only handles the PIL drawing step that converts prepared data into
PNG bytes.

How list rendering reaches the device
--------------------------------------
1. Device polls ``/api/display``.
2. ``TrmnlDeviceDisplayMixin.build_display_response()`` calls
   ``profile._render_and_store_preview()`` when a refresh is due.
3. ``_render_and_store_preview`` resolves device dimensions, loads ORM records,
   and calls ``_dispatch_renderer``.
4. ``_dispatch_renderer`` calls ``self._render_list_png()`` or
   ``self._render_kanban_png()`` (defined here) and returns PNG bytes.
5. The bytes are composited with the footer strip by ``_finalize_display_image``
   and stored in ``preview_image``.
6. The device downloads the stored PNG from ``/api/profile/image/<id>``.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from odoo import models

from odoo.addons.trmnl import trmnl_display_canvas as _canvas


class TrmnlProfileRenderListMixin(models.Model):
    """Adds list and kanban PIL rendering to trmnl.profile."""

    _inherit = "trmnl.profile"

    # ── List renderer ─────────────────────────────────────────────────────────

    @staticmethod
    def _render_list_png(
        items: list[dict],
        *,
        width: int | None = None,
        content_height: int | None = None,
        title: str = "",
        total_count: int | None = None,
        empty_message: str = "No records match your filters",
    ) -> bytes:
        """Render a glanceable list as a grayscale PNG and return the bytes.

        Each item dict: ``{"primary": str, "meta": str, "status": str}``.
        ``status`` drives the left accent-bar colour and an optional marker
        prefix ("overdue", "progress", "done").

        ``width`` / ``content_height`` come from ``device.display_width`` /
        ``device.display_height`` minus the footer band; falls back to the
        default 800×CONTENT_HEIGHT when the device has not yet reported its
        resolution.
        """
        _ROW_H = 38
        _OVERFLOW_RESERVE = 20

        w = width or _canvas.DISPLAY_WIDTH
        h = content_height or _canvas.CONTENT_HEIGHT

        img = Image.new("L", (w, h), _canvas.EINK_WHITE)
        draw = ImageDraw.Draw(img)

        font_primary = _canvas.load_font(_canvas.FONT_PRIMARY, bold=True)
        font_meta = _canvas.load_font(_canvas.FONT_META)

        # Header: large bold title with a black underline rule.
        top = _canvas.draw_list_header(draw, w, title)

        if not items:
            _canvas.draw_empty_centered(draw, w, top, h, empty_message)
            return _canvas.save_png(img)

        body_bottom = h - _OVERFLOW_RESERVE
        max_rows = max(0, (body_bottom - top) // _ROW_H)
        visible = items[:max_rows]
        cap = total_count if total_count is not None else len(items)
        more = max(0, cap - len(visible))
        text_w = w - _canvas.MARGIN_X - _canvas.ACCENT_W - 6

        for idx, item in enumerate(visible):
            y0 = top + idx * _ROW_H
            status = (item.get("status") or "").strip().lower()
            accent = _canvas.ACCENT_FILL.get(status, _canvas.ACCENT_FILL["default"])

            # Coloured accent bar on the left edge of each row.
            draw.rectangle(
                [
                    _canvas.MARGIN_X,
                    y0 + 4,
                    _canvas.MARGIN_X + _canvas.ACCENT_W - 1,
                    y0 + _ROW_H - 5,
                ],
                fill=accent,
            )

            marker = _canvas.STATUS_MARKERS.get(status, "")
            primary = marker + str(item.get("primary") or "")
            meta = str(item.get("meta") or "")

            ptext = _canvas.trunc(draw, primary, font_primary, text_w)
            draw.text(
                (_canvas.MARGIN_X + _canvas.ACCENT_W + 6, y0 + 5),
                ptext,
                fill=_canvas.EINK_INK,
                font=font_primary,
            )
            if meta:
                mtext = _canvas.trunc(draw, meta, font_meta, text_w)
                draw.text(
                    (_canvas.MARGIN_X + _canvas.ACCENT_W + 6, y0 + 22),
                    mtext,
                    fill=_canvas.EINK_INK_SOFT,
                    font=font_meta,
                )

            if idx > 0:
                draw.line(
                    [(_canvas.MARGIN_X, y0), (w - _canvas.MARGIN_X, y0)],
                    fill=_canvas.EINK_RULE_FAINT,
                    width=1,
                )

        if more > 0:
            _canvas.draw_overflow_footer(draw, w, top + len(visible) * _ROW_H + 2, more)

        return _canvas.save_png(img)

    # ── Kanban renderer ───────────────────────────────────────────────────────

    @staticmethod
    def _render_kanban_png(
        columns: list[dict],
        *,
        width: int | None = None,
        content_height: int | None = None,
        title: str = "",
        empty_message: str = "No items match current filters",
    ) -> bytes:
        """Render horizontal kanban stage columns as a grayscale PNG.

        Each column dict:
        ``{"name": str, "count": int, "items": [str, ...], "hidden": int}``.
        Columns beyond the visible width (or _MAX_COLUMNS) are clipped; an
        overflow indicator is drawn at the bottom when stages are hidden.
        """
        _MIN_COL_W = 168
        _COL_RULE_W = 1
        _ITEM_H = 14
        _ITEM_BULLET = "· "
        _STAGE_HEADER_H = 22
        _OVERFLOW_RESERVE = 18
        _MAX_COLUMNS = 5

        w = width or _canvas.DISPLAY_WIDTH
        h = content_height or _canvas.CONTENT_HEIGHT

        img = Image.new("L", (w, h), _canvas.EINK_WHITE)
        draw = ImageDraw.Draw(img)

        font_item = _canvas.load_font(_canvas.FONT_SMALL)

        # Same list-style header as the list layout (large title + rule).
        y0 = _canvas.draw_list_header(draw, w, title)

        if not columns:
            _canvas.draw_empty_centered(draw, w, y0, h, empty_message)
            return _canvas.save_png(img)

        y_body_top = y0 + 4
        y_max = h - _OVERFLOW_RESERVE
        body_h = max(0, y_max - y_body_top)
        max_items = max(1, (body_h - _STAGE_HEADER_H) // _ITEM_H)

        # Compute how many columns fit and their x positions.
        inner = w - 2 * _canvas.MARGIN_X
        max_fit = max(1, (inner + _COL_RULE_W) // (_MIN_COL_W + _COL_RULE_W))
        n_vis = min(len(columns), max_fit, _MAX_COLUMNS)
        rules = max(0, n_vis - 1)
        col_w = max(1, (inner - rules * _COL_RULE_W) // n_vis)
        col_xs = [_canvas.MARGIN_X + i * (col_w + _COL_RULE_W) for i in range(n_vis)]

        visible = columns[:n_vis]
        hidden_cols = len(columns) - n_vis

        for i, col in enumerate(visible):
            x0 = col_xs[i]
            name = str(col.get("name") or "—").upper()
            count = int(col.get("count") or 0)
            cy = _canvas.draw_kanban_column_header(draw, x0, col_w, y_body_top, f"{name} ({count})")

            items = list(col.get("items") or [])
            hidden = int(col.get("hidden") or 0)
            shown = items[:max_items]
            hidden += max(0, len(items) - len(shown))

            pad = 4
            max_text = col_w - 2 * pad - 6
            for line in shown:
                text = _ITEM_BULLET + _canvas.trunc(draw, str(line), font_item, max_text)
                draw.text((x0 + pad, cy), text, fill=_canvas.EINK_INK, font=font_item)
                cy += _ITEM_H

            if hidden > 0:
                more = _canvas.trunc(draw, f"+{hidden}", font_item, max_text)
                draw.text((x0 + pad, cy), more, fill=_canvas.EINK_INK_SOFT, font=font_item)

            # Vertical rule between adjacent columns.
            if i < len(visible) - 1:
                vx = x0 + col_w
                draw.line([(vx, y_body_top), (vx, y_max)], fill=_canvas.EINK_RULE_FAINT, width=1)

        if hidden_cols > 0:
            _canvas.draw_overflow_footer(draw, w, y_max - 2, hidden_cols)

        return _canvas.save_png(img)
