"""Golden tests: list/kanban renderers must match tests/samples/*_design_sample.png."""

from __future__ import annotations

import os

from odoo.tests import tagged
from odoo.tests.common import TransactionCase

_SAMPLES = os.path.join(os.path.dirname(__file__), "samples")

_LIST_ITEMS = [
    {"primary": "SO0042 · Acme Corp", "meta": "1,240 · Sale · 15 May", "status": "progress"},
    {"primary": "SO0043 · Beta GmbH", "meta": "890 · Draft · 18 May", "status": ""},
    {"primary": "INV/2026/014 · Northwind", "meta": "Overdue · 2,100", "status": "overdue"},
    {"primary": "SO0040 · Gamma Ltd", "meta": "450 · Done", "status": "done"},
    {"primary": "SO0038 · Delta AG", "meta": "320 · Sale · 10 May", "status": ""},
]

_KANBAN_COLUMNS = [
    {"name": "Todo", "count": 3, "items": ["Prepare proposal", "Update docs", "Review contract"], "hidden": 0},
    {
        "name": "In Progress",
        "count": 5,
        "items": ["API integration", "Calendar renderer", "Device polling"],
        "hidden": 2,
    },
    {"name": "Review", "count": 2, "items": ["UI cleanup", "QA pass"], "hidden": 0},
]


@tagged("-at_install", "post_install")
class TestDesignSamples(TransactionCase):
    def test_list_matches_design_sample_png(self):
        from odoo.addons.trmnl.trmnl_preview import render_list_preview

        path = os.path.join(_SAMPLES, "list_design_sample.png")
        with open(path, "rb") as f:
            expected = f.read()
        actual = render_list_preview(
            _LIST_ITEMS,
            title="My Sales Orders",
            total_count=23,
        )
        self.assertEqual(actual, expected)

    def test_kanban_matches_design_sample_png(self):
        from odoo.addons.trmnl.trmnl_kanban_preview import render_kanban_preview

        path = os.path.join(_SAMPLES, "kanban_design_sample.png")
        with open(path, "rb") as f:
            expected = f.read()
        actual = render_kanban_preview(_KANBAN_COLUMNS, title="Sprint Board")
        self.assertEqual(actual, expected)
