"""Tests for the Render Preview button (single-click, cache busting)."""

from __future__ import annotations

import base64
import hashlib

from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestProfileRenderPreviewButton(TransactionCase):
    """Render Preview must reflect saved form values in one click."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Profile = cls.env["trmnl.profile"]
        cls._device = cls.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:99",
            "approval_state": "accepted",
            "registration_source": "setup",
        })
        cls._partner_model = cls.env["ir.model"].sudo().search(
            [("model", "=", "res.partner")], limit=1
        )
        cls._groupby_field = cls.env["ir.model.fields"].sudo().search(
            [("model", "=", "res.partner"), ("name", "=", "country_id")], limit=1
        )

    def _profile(self, **extra):
        values = {
            "name": "render preview test",
            "device_id": self._device.id,
            "app_model_id": self._partner_model.id,
            "trmnl_layout": "graph",
            "graph_type": "bar",
            "graph_groupby_field_id": self._groupby_field.id,
            "graph_sort_order": "value_desc",
            "graph_max_groups": 10,
            "filter_preset": "none",
        }
        values.update(extra)
        return self.Profile.sudo().create(values)

    def test_preview_image_html_cache_bust_includes_png_hash(self):
        """Cache-bust query param must include a digest of the PNG bytes."""
        profile = self._profile()
        profile._render_and_store_preview()
        digest = hashlib.sha256(base64.b64decode(profile.preview_image)).hexdigest()[:12]
        self.assertIn(digest, profile.preview_image_html or "")

    def test_preview_image_html_changes_when_png_changes(self):
        """HTML img URL must change when the stored PNG bytes change."""
        profile = self._profile(filter_domain="[('name', '!=', False)]")
        profile._render_and_store_preview()
        html_before = profile.preview_image_html

        profile.write({"filter_domain": "[('id', '<', 0)]"})
        profile._render_and_store_preview()
        profile.invalidate_recordset(["preview_image_html", "preview_image"])

        html_after = profile.preview_image_html
        self.assertTrue(html_before)
        self.assertTrue(html_after)
        self.assertNotEqual(html_before, html_after)

    def test_action_render_preview_returns_form_reload_action(self):
        """Client action must re-open the form (not rely on tag:reload alone)."""
        profile = self._profile()
        result = profile.action_render_preview()
        self.assertEqual(result.get("type"), "ir.actions.client")
        self.assertEqual(result.get("tag"), "display_notification")
        next_action = result["params"]["next"]
        self.assertEqual(next_action.get("type"), "ir.actions.act_window")
        self.assertEqual(next_action.get("res_model"), "trmnl.profile")
        self.assertEqual(next_action.get("res_id"), profile.id)
        self.assertEqual(next_action.get("view_mode"), "form")

    def test_action_render_preview_uses_persisted_field_values(self):
        """After a field change is written, one render call must update preview bytes."""
        profile = self._profile(filter_domain="[('name', '!=', False)]")
        profile._render_and_store_preview()
        png_first = profile.preview_image

        profile.write({"filter_domain": "[('id', '<', 0)]"})
        profile.browse(profile.id).action_render_preview()
        profile.invalidate_recordset(["preview_image", "preview_generated_at"])

        self.assertTrue(profile.preview_image)
        self.assertNotEqual(png_first, profile.preview_image)

    def test_action_render_preview_sets_preview_on_first_call(self):
        profile = self._profile()
        profile.write({"preview_image": False, "preview_generated_at": False})
        profile.action_render_preview()
        self.assertTrue(profile.preview_image)
        self.assertTrue(base64.b64decode(profile.preview_image or b"").startswith(b"\x89PNG"))
