"""Calendar month: stored preview bytes must match the device image HTTP endpoint."""

from __future__ import annotations

import base64
import io

from odoo.tests import HttpCase, tagged

from odoo.addons.trmnl.tests.test_api_common import (
    DISPLAY_POLICY_ERROR,
    TrmnlApiHttpCaseMixin,
)


@tagged("-at_install", "post_install")
class TestCalendarMonthDeviceImageBytes(HttpCase, TrmnlApiHttpCaseMixin):
    """Preview PNG in DB is exactly what /api/profile/image serves to TRMNL."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._cal_model = cls.env["ir.model"].sudo().search(
            [("model", "=", "calendar.event")], limit=1
        )

    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param(
            "web.base.url", "http://127.0.0.1:8069"
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "trmnl.public_base_url", "http://192.168.1.127:8069"
        )

    def _calendar_profile(self, device):
        if not self._cal_model:
            self.skipTest("calendar.event not installed")
        return self.env["trmnl.profile"].sudo().create({
            "name": "Calendar month sync",
            "device_id": device.id,
            "app_model_id": self._cal_model.id,
            "trmnl_layout": "calendar",
            "calendar_view_mode": "month",
            "filter_preset": "none",
        })

    def test_profile_image_endpoint_returns_stored_preview_bytes(self):
        self._set_display_policy(DISPLAY_POLICY_ERROR)
        ctx = self._register_device_through_setup()
        profile = self._calendar_profile(ctx["device"])
        profile._render_and_store_preview()

        stored = base64.b64decode(profile.preview_image)
        self.assertTrue(stored.startswith(b"\x89PNG"))

        digest = profile._preview_png_digest()
        url = self._profile_image_path(profile.id, ctx["api_token"], version=digest)
        resp = self.url_open(url)
        self.assertEqual(self._response_status(resp), 200)
        served = resp.content if hasattr(resp, "content") else resp.read()
        self.assertEqual(served, stored)

    def test_kanban_profile_form_preview_uses_same_api_bytes(self):
        """Kanban layout: form preview URL and device download share one PNG."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)
        ctx = self._register_device_through_setup()
        partner_model = self.env["ir.model"].sudo().search(
            [("model", "=", "res.partner")], limit=1,
        )
        country_field = self.env["ir.model.fields"].sudo().search(
            [("model", "=", "res.partner"), ("name", "=", "country_id")], limit=1,
        )
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "Kanban sync",
            "device_id": ctx["device"].id,
            "app_model_id": partner_model.id,
            "trmnl_layout": "kanban",
            "kanban_stage_field_id": country_field.id,
            "filter_preset": "none",
        })
        profile._render_and_store_preview()
        stored = base64.b64decode(profile.preview_image)
        digest = profile._preview_png_digest()
        html = profile.preview_image_html or ""
        self.assertIn(f"/api/profile/image/{profile.id}", html)
        self.assertIn(digest, html)
        resp = self.url_open(
            self._profile_image_path(profile.id, ctx["api_token"], version=digest)
        )
        served = resp.content if hasattr(resp, "content") else resp.read()
        self.assertEqual(served, stored)
        payload = self._response_json(
            self.url_open(
                "/api/display",
                headers=self._display_headers(ctx["api_token"], ctx["device"].mac_address),
            )
        )
        image_url = payload.get("image_url") or ""
        self.assertIn(f"/api/profile/image/{profile.id}", image_url)
        self.assertIn("access_token=", image_url)

    def test_list_profile_form_preview_uses_same_api_bytes(self):
        """List layout: form preview URL and device download share one PNG."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)
        ctx = self._register_device_through_setup()
        partner_model = self.env["ir.model"].sudo().search(
            [("model", "=", "res.partner")], limit=1,
        )
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "List sync",
            "device_id": ctx["device"].id,
            "app_model_id": partner_model.id,
            "trmnl_layout": "list",
            "filter_preset": "none",
        })
        profile._render_and_store_preview()
        stored = base64.b64decode(profile.preview_image)
        digest = profile._preview_png_digest()
        html = profile.preview_image_html or ""
        self.assertIn(f"/api/profile/image/{profile.id}", html)
        self.assertIn(digest, html)
        resp = self.url_open(
            self._profile_image_path(profile.id, ctx["api_token"], version=digest)
        )
        served = resp.content if hasattr(resp, "content") else resp.read()
        self.assertEqual(served, stored)

    def test_filename_and_url_change_when_preview_image_changes(self):
        self._set_display_policy(DISPLAY_POLICY_ERROR)
        ctx = self._register_device_through_setup()
        profile = self._calendar_profile(ctx["device"])
        profile._render_and_store_preview()

        url_a = profile._get_display_image_url()
        name_a = profile._get_display_filename()

        raw = bytearray(base64.b64decode(profile.preview_image))
        raw[-2] ^= 0xFF
        profile.write({"preview_image": base64.b64encode(bytes(raw))})
        profile.invalidate_recordset()

        url_b = profile._get_display_image_url()
        name_b = profile._get_display_filename()
        self.assertNotEqual(url_a, url_b)
        self.assertNotEqual(name_a, name_b)

    def test_display_poll_points_device_at_profile_image_url(self):
        """Device must not keep a fallback URL when profile image is reachable."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)
        ctx = self._register_device_through_setup()
        profile = self._calendar_profile(ctx["device"])
        profile._render_and_store_preview()

        resp = self.url_open(
            "/api/display",
            headers=self._display_headers(ctx["api_token"], ctx["device"].mac_address),
        )
        payload = self._response_json(resp)
        self.assertEqual(payload.get("status"), 0)
        image_url = payload.get("image_url") or ""
        self.assertIn(f"/api/profile/image/{profile.id}", image_url)
        self.assertIn("?v=", image_url)
        ctx["device"].invalidate_recordset()
        self.assertIn(f"/api/profile/image/{profile.id}", ctx["device"].image_url or "")

    def test_may_padding_cells_darker_than_in_month_after_full_pipeline(self):
        """End-to-end calendar month keeps grey padding cells in the stored PNG."""
        from PIL import Image

        from odoo.addons.trmnl.trmnl_display_canvas import CALENDAR_COL_W as COL_W, CALENDAR_GRID_TOP as GRID_TOP

        self._set_display_policy(DISPLAY_POLICY_ERROR)
        ctx = self._register_device_through_setup()
        profile = self._calendar_profile(ctx["device"])
        profile.write({
            "calendar_reference_mode": "custom",
            "calendar_reference_date": "2026-05-15",
        })
        profile._render_and_store_preview()

        img = Image.open(io.BytesIO(base64.b64decode(profile.preview_image)))
        # Full frame includes footer; month grid is in the content strip at the top.
        content_h = img.height - 26
        px = img.load()
        row_h = (content_h - GRID_TOP) // 5
        pad_avg = sum(
            px[x, y]
            for x in range(10, COL_W - 10)
            for y in range(GRID_TOP + 10, GRID_TOP + row_h - 10)
        ) / ((COL_W - 20) * (row_h - 20))
        in_month = px[4 * COL_W + 30, GRID_TOP + row_h // 2]
        self.assertLess(pad_avg, 245.0)
        self.assertGreaterEqual(in_month, 250)
