"""Ensure finalized PNGs match device output (list B/W, kanban grayscale)."""

from __future__ import annotations

import base64
import io

from odoo.addons.trmnl.trmnl_display_canvas import CONTENT_HEIGHT, DISPLAY_WIDTH
from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestDisplayImageQuality(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param(
            "web.base.url", "http://192.168.1.127:8069"
        )
        cls.device = cls.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:77",
            "approval_state": "accepted",
            "registration_source": "setup",
        })
        cls.profile = cls.env["trmnl.profile"].sudo().create({
            "name": "Quality test",
            "device_id": cls.device.id,
            "trmnl_layout": "list",
        })

    def test_finalize_list_uses_pure_black_white(self):
        """List frames are threshold-binarized for e-ink parity."""
        from PIL import Image

        items = [
            {
                "primary": "SO0042 · Acme Corp",
                "meta": "1,240 · Sale · 15 May",
                "status": "progress",
            },
        ]
        content = self.profile._render_list_png(items, title="My Sales Orders")
        result = self.profile._finalize_display_image(content)
        img = Image.open(io.BytesIO(result))
        px = img.load()
        vals = {px[x, y] for y in range(30, 120) for x in range(20, 400)}
        self.assertTrue(vals.issubset({0, 255}), f"expected only 0/255, got {vals}")

    def test_finalize_kanban_keeps_grayscale(self):
        """Kanban is not binarized — column rules and soft text stay visible."""
        from PIL import Image

        kanban_profile = self.env["trmnl.profile"].sudo().create({
            "name": "Kanban quality",
            "device_id": self.device.id,
            "trmnl_layout": "kanban",
        })
        cols = [
            {"name": "Todo", "count": 1, "items": ["Task A"], "hidden": 0},
            {"name": "Done", "count": 1, "items": ["Task B"], "hidden": 0},
        ]
        content = kanban_profile._render_kanban_png(cols, title="Board")
        result = kanban_profile._finalize_display_image(content)
        img = Image.open(io.BytesIO(result))
        px = img.load()
        grays = {
            px[x, y]
            for y in range(40, 120)
            for x in range(20, 750)
            if 10 < px[x, y] < 245
        }
        self.assertGreater(len(grays), 5, "kanban should retain anti-aliased / rule grays")

    def test_form_preview_html_uses_device_api_url(self):
        partner_model = self.env["ir.model"].sudo().search(
            [("model", "=", "res.partner")], limit=1,
        )
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "URL test",
            "device_id": self.device.id,
            "app_model_id": partner_model.id,
            "trmnl_layout": "list",
        })
        profile._render_and_store_preview()
        digest = profile._preview_png_digest()
        html = profile.preview_image_html or ""
        self.assertIn(f"/api/profile/image/{profile.id}", html)
        self.assertIn(digest, html)
        self.assertNotIn("/web/image/", profile.preview_image_html or "")

    def test_render_updates_device_image_url(self):
        partner_model = self.env["ir.model"].sudo().search(
            [("model", "=", "res.partner")], limit=1,
        )
        country_field = self.env["ir.model.fields"].sudo().search(
            [("model", "=", "res.partner"), ("name", "=", "country_id")], limit=1,
        )
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "Kanban sync",
            "device_id": self.device.id,
            "app_model_id": partner_model.id,
            "trmnl_layout": "kanban",
            "kanban_stage_field_id": country_field.id,
            "filter_preset": "none",
        })
        profile._render_and_store_preview()
        self.assertIn(f"/api/profile/image/{profile.id}", self.device.image_url or "")
        self.assertIn("?v=", self.device.image_url or "")
