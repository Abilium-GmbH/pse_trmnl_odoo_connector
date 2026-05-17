"""Device image URL / filename must change when preview bytes change."""

from __future__ import annotations

import base64

from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestDeviceImageSync(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._device = cls.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:22",
            "approval_state": "accepted",
            "registration_source": "setup",
        })
        cls._partner_model = cls.env["ir.model"].sudo().search(
            [("model", "=", "res.partner")], limit=1
        )
        cls.env["ir.config_parameter"].sudo().set_param(
            "web.base.url", "http://192.168.1.50:8069"
        )

    def _profile(self, png=b"\x89PNG\r\n\x1a\n"):
        return self.env["trmnl.profile"].sudo().create({
            "name": "sync test",
            "device_id": self._device.id,
            "app_model_id": self._partner_model.id,
            "trmnl_layout": "list",
            "preview_image": base64.b64encode(png),
            "preview_generated_at": "2026-05-11 12:00:00",
            "preview_renderer_version": "1.0.0",
        })

    def test_image_url_includes_png_digest_query(self):
        profile = self._profile()
        url = profile._get_display_image_url()
        digest = profile._preview_png_digest()
        self.assertIn(f"?v={digest}", url)

    def test_image_url_changes_when_png_changes(self):
        profile = self._profile(b"\x89PNG\x01")
        url_a = profile._get_display_image_url()
        profile.write({"preview_image": base64.b64encode(b"\x89PNG\x02")})
        url_b = profile._get_display_image_url()
        self.assertNotEqual(url_a, url_b)

    def test_should_render_when_renderer_version_stale(self):
        profile = self._profile()
        profile.write({"preview_renderer_version": "0.0.0"})
        self.assertTrue(profile._should_render_for_device())

    def test_filename_changes_when_preview_bytes_change(self):
        profile = self._profile(b"\x89PNG\x01")
        name_a = profile._get_display_filename()
        profile.write({"preview_image": base64.b64encode(b"\x89PNG\x02")})
        name_b = profile._get_display_filename()
        self.assertNotEqual(name_a, name_b)
