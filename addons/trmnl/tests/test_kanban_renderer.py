"""Tests for TRMNL kanban renderer (trmnl_kanban_preview.py)."""

from __future__ import annotations

import io

from odoo.addons.trmnl.trmnl_display_canvas import CONTENT_HEIGHT, DISPLAY_WIDTH
from odoo.tests import TransactionCase, tagged


def _render(columns, **kwargs):
    from odoo.addons.trmnl.trmnl_kanban_preview import render_kanban_preview

    return render_kanban_preview(columns, **kwargs)


def _img(png):
    from PIL import Image

    return Image.open(io.BytesIO(png))


@tagged("-at_install", "post_install")
class TestKanbanRenderer(TransactionCase):
    def test_size(self):
        cols = [{"name": "Todo", "count": 1, "items": ["Fix API"], "hidden": 0}]
        self.assertEqual(_img(_render(cols)).size, (DISPLAY_WIDTH, CONTENT_HEIGHT))

    def test_three_columns_use_horizontal_layout(self):
        cols = [
            {"name": "Todo", "count": 1, "items": ["A"], "hidden": 0},
            {"name": "Doing", "count": 1, "items": ["B"], "hidden": 0},
            {"name": "Done", "count": 1, "items": ["C"], "hidden": 0},
        ]
        img = _img(_render(cols, title="Board"))
        px = img.load()
        # For 3 cols at width=800: col_w≈255, x0s=[16, 272, 528].
        # Column headers (text + rule) occupy y≈26–50. Scan within each column's x range.
        y_range = range(26, 52)
        left_ink = any(px[x, y] < 80 for x in range(20, 80) for y in y_range)
        mid_ink = any(px[x, y] < 80 for x in range(276, 360) for y in y_range)
        right_ink = any(px[x, y] < 80 for x in range(532, 620) for y in y_range)
        self.assertTrue(left_ink and mid_ink and right_ink, "ink expected in all three column headers")

    def test_list_style_header_on_kanban(self):
        from odoo.addons.trmnl.trmnl_layout_ui import LIST_HEADER_PAD_TOP

        cols = [{"name": "Todo", "count": 1, "items": ["X"], "hidden": 0}]
        img = _img(_render(cols, title="Sprint"))
        px = img.load()
        self.assertGreaterEqual(px[20, LIST_HEADER_PAD_TOP], 250)
        self.assertLess(px[20, LIST_HEADER_PAD_TOP + 8], 40)

    def test_empty_state(self):
        img = _img(_render([], empty_message="No tasks"))
        self.assertEqual(img.size[1], CONTENT_HEIGHT)
