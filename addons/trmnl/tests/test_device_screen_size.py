"""Device-reported Width/Height headers drive stored size and PNG dimensions."""

from __future__ import annotations

import base64
import io

from odoo.tests import HttpCase, TransactionCase, tagged

from odoo.addons.trmnl.tests.test_api_common import (
    DISPLAY_POLICY_ERROR,
    TrmnlApiHttpCaseMixin,
)

from .test_common import make_trmnl_device, partner_ir_model


@tagged("-at_install", "post_install")
class TestDeviceScreenSizeTelemetry(HttpCase, TrmnlApiHttpCaseMixin):
    """``/api/display`` must persist Width/Height from device headers."""

    def test_display_poll_stores_reported_dimensions(self):
        self._set_display_policy(DISPLAY_POLICY_ERROR)
        ctx = self._register_device_through_setup()
        headers = self._display_headers(ctx["api_token"], ctx["device"].mac_address)
        headers["Width"] = "1024"
        headers["Height"] = "600"

        self.url_open("/api/display", headers=headers)

        device = self.env["trmnl.device"].sudo().browse(ctx["device"].id)
        self.assertEqual(device.display_width, 1024)
        self.assertEqual(device.display_height, 600)


@tagged("-at_install", "post_install")
class TestRenderUsesDeviceDimensions(TransactionCase):
    """Preview PNG size follows device.display_width/height, not hardcoded defaults."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._device = make_trmnl_device(
            cls.env,
            "AA:BB:CC:DD:EE:44",
            display_width=640,
            display_height=400,
        )
        cls._partner_model = partner_ir_model(cls.env)

    def test_list_preview_matches_device_dimensions(self):
        from PIL import Image

        profile = self.env["trmnl.profile"].sudo().create({
            "name": "size test",
            "device_id": self._device.id,
            "app_model_id": self._partner_model.id,
            "trmnl_layout": "list",
            "filter_preset": "none",
        })
        profile._render_and_store_preview()
        img = Image.open(io.BytesIO(base64.b64decode(profile.preview_image)))
        self.assertEqual(img.size, (640, 400))
