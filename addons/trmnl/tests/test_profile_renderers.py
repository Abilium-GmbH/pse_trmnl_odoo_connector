"""ORM-level renderer tests: verify each _render_*_png method returns valid PNG bytes.

These tests replace the deleted standalone pure-Python renderer tests
(test_list_renderer, test_kanban_renderer, test_calendar_month_renderer).
All six renderers are now static methods on trmnl.profile and called via the ORM.
"""

from __future__ import annotations

import io
from datetime import date, datetime

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


def _png_size(png_bytes: bytes) -> tuple[int, int]:
    from PIL import Image
    return Image.open(io.BytesIO(png_bytes)).size


@tagged("-at_install", "post_install")
class TestListRendererORM(TransactionCase):
    """_render_list_png produces valid, correctly-sized PNG output."""

    _ITEMS = [
        {"primary": "SO0001 · Acme", "meta": "1,000 · Sale · 1 Jan", "status": "progress"},
        {"primary": "SO0002 · Beta", "meta": "200 · Draft", "status": ""},
        {"primary": "INV/001 · Gamma", "meta": "Overdue · 500", "status": "overdue"},
    ]

    def _render(self, **kw):
        return self.env["trmnl.profile"]._render_list_png(self._ITEMS, **kw)

    def test_returns_png_bytes(self):
        result = self._render(title="Sales")
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_default_dimensions(self):
        result = self._render(title="Sales")
        w, h = _png_size(result)
        self.assertEqual(w, 800)
        self.assertGreater(h, 0)

    def test_custom_dimensions(self):
        result = self._render(title="Sales", width=400, content_height=300)
        w, h = _png_size(result)
        self.assertEqual(w, 400)
        self.assertEqual(h, 300)

    def test_empty_items(self):
        result = self.env["trmnl.profile"]._render_list_png([], title="Empty")
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_total_count_does_not_crash(self):
        result = self._render(title="Sales", total_count=42)
        self.assertTrue(result.startswith(b"\x89PNG"))


@tagged("-at_install", "post_install")
class TestKanbanRendererORM(TransactionCase):
    """_render_kanban_png produces valid, correctly-sized PNG output."""

    _COLUMNS = [
        {"name": "Todo", "count": 3, "items": ["Task A", "Task B"], "hidden": 0},
        {"name": "In Progress", "count": 4, "items": ["Task C", "Task D"], "hidden": 1},
        {"name": "Done", "count": 2, "items": ["Task E"], "hidden": 0},
    ]

    def _render(self, **kw):
        return self.env["trmnl.profile"]._render_kanban_png(self._COLUMNS, **kw)

    def test_returns_png_bytes(self):
        result = self._render(title="Board")
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_default_dimensions(self):
        result = self._render(title="Board")
        w, h = _png_size(result)
        self.assertEqual(w, 800)
        self.assertGreater(h, 0)

    def test_custom_dimensions(self):
        result = self._render(title="Board", width=600, content_height=350)
        w, h = _png_size(result)
        self.assertEqual(w, 600)
        self.assertEqual(h, 350)

    def test_empty_columns(self):
        result = self.env["trmnl.profile"]._render_kanban_png([], title="Empty")
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_single_column(self):
        cols = [{"name": "Solo", "count": 1, "items": ["Only task"], "hidden": 0}]
        result = self.env["trmnl.profile"]._render_kanban_png(cols, title="Solo")
        self.assertTrue(result.startswith(b"\x89PNG"))


@tagged("-at_install", "post_install")
class TestCalendarMonthRendererORM(TransactionCase):
    """_render_calendar_month_png produces valid PNG output."""

    _EVENTS = [
        {"start": date(2026, 5, 5), "title": "Team standup", "time_str": "09:00"},
        {"start": date(2026, 5, 12), "title": "Sprint review", "time_str": "14:00"},
        {"start": date(2026, 5, 20), "title": "All-hands", "time_str": ""},
    ]

    def _render(self, **kw):
        return self.env["trmnl.profile"]._render_calendar_month_png(
            self._EVENTS, 2026, 5, **kw
        )

    def test_returns_png_bytes(self):
        result = self._render()
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_default_dimensions(self):
        result = self._render()
        w, h = _png_size(result)
        self.assertEqual(w, 800)
        self.assertGreater(h, 0)

    def test_custom_dimensions(self):
        result = self._render(width=400, content_height=280)
        w, h = _png_size(result)
        self.assertEqual(w, 400)
        self.assertEqual(h, 280)

    def test_empty_events(self):
        result = self.env["trmnl.profile"]._render_calendar_month_png([], 2026, 1)
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_february_leap_year(self):
        result = self.env["trmnl.profile"]._render_calendar_month_png([], 2028, 2)
        self.assertTrue(result.startswith(b"\x89PNG"))


@tagged("-at_install", "post_install")
class TestCalendarWeekRendererORM(TransactionCase):
    """_render_calendar_week_png produces valid PNG output."""

    _EVENTS = [
        {
            "start_datetime": datetime(2026, 5, 18, 9, 0),
            "end_datetime": datetime(2026, 5, 18, 10, 0),
            "title": "Morning sync",
        },
        {
            "start_datetime": datetime(2026, 5, 20, 14, 0),
            "end_datetime": datetime(2026, 5, 20, 15, 30),
            "title": "Design review",
        },
    ]

    def _render(self, week_mode="work_week", **kw):
        return self.env["trmnl.profile"]._render_calendar_week_png(
            self._EVENTS, date(2026, 5, 18), week_mode, **kw
        )

    def test_returns_png_bytes(self):
        result = self._render()
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_work_week_default_dimensions(self):
        result = self._render(week_mode="work_week")
        w, h = _png_size(result)
        self.assertEqual(w, 800)
        self.assertGreater(h, 0)

    def test_full_week_mode(self):
        result = self._render(week_mode="full_week")
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_custom_dimensions(self):
        result = self._render(width=400, content_height=300)
        w, h = _png_size(result)
        self.assertEqual(w, 400)
        self.assertEqual(h, 300)

    def test_empty_events(self):
        result = self.env["trmnl.profile"]._render_calendar_week_png(
            [], date(2026, 5, 18), "work_week"
        )
        self.assertTrue(result.startswith(b"\x89PNG"))


@tagged("-at_install", "post_install")
class TestBarChartRendererORM(TransactionCase):
    """_render_bar_chart_png produces valid PNG output."""

    _BARS = [
        {"label": "Alpha", "value": 10.0},
        {"label": "Beta", "value": 7.0},
        {"label": "Gamma", "value": 3.0},
    ]

    def _render(self, **kw):
        return self.env["trmnl.profile"]._render_bar_chart_png(
            self._BARS, "Test Chart", "Count", **kw
        )

    def test_returns_png_bytes(self):
        result = self._render()
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_default_dimensions(self):
        result = self._render()
        w, h = _png_size(result)
        self.assertEqual(w, 800)
        self.assertGreater(h, 0)

    def test_custom_dimensions(self):
        result = self._render(width=400, content_height=300)
        w, h = _png_size(result)
        self.assertEqual(w, 400)
        self.assertEqual(h, 300)

    def test_empty_bars(self):
        result = self.env["trmnl.profile"]._render_bar_chart_png([], "Empty", "Count")
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_all_zero_values(self):
        bars = [{"label": "A", "value": 0.0}, {"label": "B", "value": 0.0}]
        result = self.env["trmnl.profile"]._render_bar_chart_png(bars, "Zeros", "Count")
        self.assertTrue(result.startswith(b"\x89PNG"))


@tagged("-at_install", "post_install")
class TestLineChartRendererORM(TransactionCase):
    """_render_line_chart_png produces valid PNG output."""

    _POINTS = [
        {"label": "Jan", "value": 100.0},
        {"label": "Feb", "value": 150.0},
        {"label": "Mar", "value": 120.0},
    ]

    def _render(self, **kw):
        return self.env["trmnl.profile"]._render_line_chart_png(
            self._POINTS, "Revenue", "EUR", **kw
        )

    def test_returns_png_bytes(self):
        result = self._render()
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_default_dimensions(self):
        result = self._render()
        w, h = _png_size(result)
        self.assertEqual(w, 800)
        self.assertGreater(h, 0)

    def test_custom_dimensions(self):
        result = self._render(width=400, content_height=300)
        w, h = _png_size(result)
        self.assertEqual(w, 400)
        self.assertEqual(h, 300)

    def test_empty_points(self):
        result = self.env["trmnl.profile"]._render_line_chart_png([], "Empty", "Count")
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_single_point(self):
        result = self.env["trmnl.profile"]._render_line_chart_png(
            [{"label": "Only", "value": 42.0}], "Single", "Count"
        )
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_all_zero_values(self):
        points = [{"label": "A", "value": 0.0}, {"label": "B", "value": 0.0}]
        result = self.env["trmnl.profile"]._render_line_chart_png(points, "Zeros", "Count")
        self.assertTrue(result.startswith(b"\x89PNG"))
