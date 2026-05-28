"""Profile pipeline: list and kanban layouts use dashboard renderers."""

from __future__ import annotations

import base64
import io
from datetime import datetime, timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


def _png_pixels(png_b64):
    from PIL import Image

    return Image.open(io.BytesIO(base64.b64decode(png_b64))).load()


@tagged("-at_install", "post_install")
class TestProfileDashboardLayout(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Profile = cls.env["trmnl.profile"]
        cls._device = cls.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:88",
            "approval_state": "accepted",
            "registration_source": "setup",
        })
        cls._partner_model = cls.env["ir.model"].sudo().search(
            [("model", "=", "res.partner")], limit=1
        )
        cls._name_field = cls.env["ir.model.fields"].sudo().search(
            [("model", "=", "res.partner"), ("name", "=", "name")], limit=1
        )
        cls._country_field = cls.env["ir.model.fields"].sudo().search(
            [("model", "=", "res.partner"), ("name", "=", "country_id")], limit=1
        )

    def _profile(self, layout, **extra):
        values = {
            "name": "Dashboard layout test",
            "device_id": self._device.id,
            "app_model_id": self._partner_model.id,
            "trmnl_layout": layout,
            "filter_preset": "none",
            "filter_domain": "[('name', '!=', False)]",
            "display_field_ids": [(6, 0, [self._name_field.id, self._country_field.id])],
        }
        values.update(extra)
        return self.Profile.sudo().create(values)

    def test_list_profile_uses_white_header_not_dark_band(self):
        profile = self._profile("list")
        profile._render_and_store_preview()
        px = _png_pixels(profile.preview_image)
        self.assertGreaterEqual(px[20, 4], 250)
        self.assertLess(px[20, 18], 40)

    def test_list_profile_prepares_dashboard_items(self):
        profile = self._profile("list")
        records = profile._load_records("res.partner", ["name", "country_id"])
        items = profile._prepare_list_items(records[:3], ["name", "country_id"], "res.partner")
        self.assertTrue(items)
        self.assertIn("primary", items[0])
        self.assertIn("meta", items[0])
        self.assertIn("status", items[0])

    def test_infer_item_status_datetime_deadline_vs_today(self):
        """project.task date_deadline is datetime — must not crash list render."""
        if "project.task" not in self.env:
            self.skipTest("project module not installed")
        task_model = self.env["ir.model"].sudo().search(
            [("model", "=", "project.task")], limit=1
        )
        name_field = self.env["ir.model.fields"].sudo().search(
            [("model", "=", "project.task"), ("name", "=", "name")], limit=1
        )
        profile = self._profile(
            "list",
            app_model_id=task_model.id,
            display_field_ids=[(6, 0, [name_field.id])],
            filter_preset="none",
            filter_domain="[]",
        )
        yesterday = fields.Datetime.to_string(
            datetime.combine(
                fields.Date.context_today(profile) - timedelta(days=1),
                datetime.min.time(),
            )
        )
        task = self.env["project.task"].sudo().create({
            "name": "Overdue datetime deadline",
            "date_deadline": yesterday,
        })
        status = profile._infer_item_status(task, "project.task", ["name"])
        self.assertEqual(status, "overdue")

    def test_kanban_and_list_preview_bytes_differ(self):
        """Kanban and list layouts must not produce identical PNG output."""
        list_profile = self._profile("list")
        list_profile._render_and_store_preview()
        kanban_profile = self._profile(
            "kanban",
            name="Kanban distinct",
            kanban_stage_field_id=self._country_field.id,
        )
        kanban_profile._render_and_store_preview()
        self.assertNotEqual(list_profile.preview_image, kanban_profile.preview_image)

    def test_kanban_profile_renders_column_layout(self):
        profile = self._profile(
            "kanban",
            kanban_stage_field_id=self._country_field.id,
        )
        records = profile._load_records("res.partner", ["name", "country_id"])
        columns = profile._prepare_kanban_columns(
            records, "res.partner", ["name", "country_id"],
        )
        self.assertTrue(columns)
        self.assertTrue(all("name" in c and "items" in c for c in columns))

        profile._render_and_store_preview()
        px = _png_pixels(profile.preview_image)
        from odoo.addons.trmnl.trmnl_display_canvas import LIST_HEADER_PAD_TOP

        self.assertGreaterEqual(px[20, LIST_HEADER_PAD_TOP], 250)
        self.assertLess(px[20, LIST_HEADER_PAD_TOP + 8], 40)
