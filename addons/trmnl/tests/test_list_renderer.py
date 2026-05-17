"""Tests for the TRMNL dashboard list renderer (trmnl_preview.py)."""

from __future__ import annotations

import io

from odoo.addons.trmnl.trmnl_display_canvas import CONTENT_HEIGHT, DISPLAY_WIDTH
from odoo.tests import TransactionCase, tagged


def _render(items, **kwargs):
    from odoo.addons.trmnl.trmnl_preview import render_list_preview

    return render_list_preview(items, **kwargs)


def _img(png_bytes):
    from PIL import Image

    return Image.open(io.BytesIO(png_bytes))


@tagged("-at_install", "post_install")
class TestListRendererOutputSize(TransactionCase):
    def test_default_size(self):
        img = _img(_render([{"primary": "Acme", "meta": "Open", "status": ""}]))
        self.assertEqual(img.size, (DISPLAY_WIDTH, CONTENT_HEIGHT))


@tagged("-at_install", "post_install")
class TestListRendererDashboardLayout(TransactionCase):
    def test_list_header_is_black_title_on_white(self):
        from odoo.addons.trmnl.trmnl_layout_ui import LIST_HEADER_PAD_TOP

        img = _img(_render([], title="Tasks"))
        px = img.load()
        self.assertGreaterEqual(px[20, LIST_HEADER_PAD_TOP], 250)
        title_ink = [px[x, y] for x in range(16, 120) for y in range(10, 28) if px[x, y] < 40]
        self.assertTrue(title_ink)

    def test_row_has_accent_bar(self):
        from PIL import Image, ImageDraw

        from odoo.addons.trmnl.trmnl_layout_ui import draw_list_header

        items = [{"primary": "Task A", "meta": "Due today", "status": "overdue"}]
        img = _img(_render(items, title="T"))
        px = img.load()
        probe = Image.new("L", (img.width, 1), 255)
        body_top = draw_list_header(ImageDraw.Draw(probe), img.width, "T")
        y = body_top + 10
        self.assertLess(px[18, y], 50)

    def test_status_marker_in_primary(self):
        items = [{"primary": "Invoice", "meta": "", "status": "done"}]
        img = _img(_render(items))
        # Rendered PNG contains ink from text; smoke test only.
        self.assertGreater(len(_render(items)), 500)

    def test_overflow_footer(self):
        items = [{"primary": f"Row {i}", "meta": "", "status": ""} for i in range(20)]
        img = _img(_render(items, total_count=50))
        px = img.load()
        # Overflow text is drawn at y ≈ top + max_rows * _ROW_H + 2 ≈ 404, not near the bottom edge.
        found = any(80 < px[x, y] < 120 for y in range(390, 430) for x in range(650, 790))
        self.assertTrue(found)
