"""Tests for the TRMNL calendar month renderer (trmnl_calendar_preview.py).

All tests are pure-Python: the renderer has no Odoo ORM dependencies.
"""

from __future__ import annotations

import calendar as _cal
import datetime
import io

from odoo.addons.trmnl.trmnl_display_canvas import CONTENT_HEIGHT
from odoo.tests import TransactionCase, tagged


def _render(year, month, events=None):
    from odoo.addons.trmnl.trmnl_calendar_preview import render_calendar_preview
    return render_calendar_preview(events or [], year, month)


def _img(png_bytes):
    from PIL import Image
    return Image.open(io.BytesIO(png_bytes))


def _count_weeks(year, month):
    """Mirror the renderer's trimming logic: return the number of visible week rows."""
    weeks = _cal.monthcalendar(year, month)
    while weeks and not any(weeks[-1]):
        weeks.pop()
    return len(weeks)


# Grid constants from the renderer (kept in sync manually).
GRID_TOP = 60   # HEADER_H(36) + DOW_H(24)
GRAY_GRID = 180


def _row_h(year, month):
    """Expected row height for the given month."""
    n = _count_weeks(year, month)
    return (CONTENT_HEIGHT - GRID_TOP) // n


@tagged("-at_install", "post_install")
class TestCalendarMonthRendererOutputSize(TransactionCase):
    """Output image matches content strip dimensions (footer is added by profile)."""

    def test_size_5_row_month(self):
        self.assertEqual(_img(_render(2026, 5)).size, (800, CONTENT_HEIGHT))

    def test_size_6_row_month(self):
        self.assertEqual(_img(_render(2022, 10)).size, (800, CONTENT_HEIGHT))

    def test_size_4_row_month(self):
        # Feb 2021 starts on Monday and has 28 days → exactly 4 complete weeks
        self.assertEqual(_img(_render(2021, 2)).size, (800, CONTENT_HEIGHT))

    def test_size_with_events(self):
        events = [{"start": datetime.date(2026, 5, 15), "title": "Test", "time_str": ""}]
        self.assertEqual(_img(_render(2026, 5, events)).size, (800, CONTENT_HEIGHT))


@tagged("-at_install", "post_install")
class TestCalendarMonthWeekRowCount(TransactionCase):
    """Verify the correct number of week rows for various months."""

    def test_may_2026_has_5_rows(self):
        # May 2026 ends on Sunday the 31st — no trailing empty row.
        self.assertEqual(_count_weeks(2026, 5), 5)

    def test_october_2022_has_6_rows(self):
        # Oct 2022 starts on Saturday → day 31 falls in a 6th row.
        self.assertEqual(_count_weeks(2022, 10), 6)

    def test_february_2021_has_4_rows(self):
        # Feb 2021 starts on Monday, 28 days → 4 complete weeks.
        self.assertEqual(_count_weeks(2021, 2), 4)

    def test_march_2026_has_6_rows(self):
        # March 2026 starts on Sunday → day 31 falls in a 6th row.
        self.assertEqual(_count_weeks(2026, 3), 6)

    def test_6_row_month_last_week_has_real_day(self):
        # The last week of Oct 2022 contains day 31 and must NOT be trimmed.
        weeks = _cal.monthcalendar(2022, 10)
        self.assertIn(31, weeks[-1])
        trimmed = list(weeks)
        while trimmed and not any(trimmed[-1]):
            trimmed.pop()
        self.assertEqual(len(trimmed), 6)

    def test_trailing_all_zero_row_is_removed(self):
        # Defensive: if a caller passes weeks with an artificial all-zero tail,
        # the trimming loop removes it.
        weeks = [[1, 2, 3, 4, 5, 6, 7], [8, 9, 10, 0, 0, 0, 0], [0] * 7]
        while weeks and not any(weeks[-1]):
            weeks.pop()
        self.assertEqual(len(weeks), 2)


@tagged("-at_install", "post_install")
class TestCalendarMonthGridLinePositions(TransactionCase):
    """Verify grid layout by inspecting rendered pixel colors.

    Strategy: a horizontal grid line is drawn in GRAY_GRID (180) across the
    full width. The pixel at (x=0, y=<line>) is therefore exactly 180.
    Row heights follow ``(CONTENT_HEIGHT - GRID_TOP) // n_rows``.
    """

    def _px(self, year, month, x, y):
        return _img(_render(year, month)).load()[x, y]

    def test_may_2026_has_grid_line_at_row4_top(self):
        rh = _row_h(2026, 5)
        self.assertEqual(self._px(2026, 5, 0, GRID_TOP + 4 * rh), GRAY_GRID)

    def test_may_2026_has_no_grid_line_at_6row_boundary(self):
        # y=410 would be the 5→6 row boundary in a 6-row layout.
        # For a 5-row layout it is inside a cell and should NOT be a grid line.
        self.assertNotEqual(self._px(2026, 5, 0, 410), GRAY_GRID)

    def test_october_2022_has_grid_line_at_5_to_6_boundary(self):
        rh = _row_h(2022, 10)
        self.assertEqual(self._px(2022, 10, 0, GRID_TOP + 5 * rh), GRAY_GRID)

    def test_february_2021_has_grid_line_at_row3_top(self):
        rh = _row_h(2021, 2)
        self.assertEqual(self._px(2021, 2, 0, GRID_TOP + 3 * rh), GRAY_GRID)

    def test_february_2021_has_no_grid_at_5row_boundary(self):
        # y=396 would be row 4→5 boundary in a 5-row layout; not a line for 4-row.
        self.assertNotEqual(self._px(2021, 2, 0, 396), GRAY_GRID)


@tagged("-at_install", "post_install")
class TestCalendarMonthWithEvents(TransactionCase):
    """Events do not break rendering and the row with events is kept."""

    def test_events_on_last_day_of_5_row_month(self):
        events = [
            {"start": datetime.date(2026, 5, 31), "title": "End of month", "time_str": "09:00"},
        ]
        img = _img(_render(2026, 5, events))
        self.assertEqual(img.size, (800, CONTENT_HEIGHT))
        rh = _row_h(2026, 5)
        self.assertEqual(img.load()[0, GRID_TOP + 4 * rh], GRAY_GRID)

    def test_events_on_last_day_of_6_row_month_keeps_6_rows(self):
        # Oct 2022: day 31 is in row 5 (0-indexed). Events there must not trim the row.
        events = [
            {"start": datetime.date(2022, 10, 31), "title": "Halloween", "time_str": ""},
        ]
        img = _img(_render(2022, 10, events))
        self.assertEqual(img.size, (800, CONTENT_HEIGHT))
        rh = _row_h(2022, 10)
        self.assertEqual(img.load()[0, GRID_TOP + 5 * rh], GRAY_GRID)

    def test_multiple_events_same_day(self):
        events = [
            {"start": datetime.date(2026, 5, 20), "title": f"Event {i}", "time_str": ""}
            for i in range(10)
        ]
        img = _img(_render(2026, 5, events))
        self.assertEqual(img.size, (800, CONTENT_HEIGHT))

    def test_events_outside_month_are_ignored(self):
        events = [
            {"start": datetime.date(2026, 4, 30), "title": "April event", "time_str": ""},
            {"start": datetime.date(2026, 6, 1), "title": "June event", "time_str": ""},
        ]
        img = _img(_render(2026, 5, events))
        self.assertEqual(img.size, (800, CONTENT_HEIGHT))
