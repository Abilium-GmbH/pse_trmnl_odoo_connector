"""Tests for display footer (poll metadata) on rendered preview images."""

import datetime as dt
import io
from unittest.mock import patch

from odoo.addons.trmnl.lib.display_canvas import (
    CONTENT_HEIGHT,
    DISPLAY_HEIGHT,
    DISPLAY_WIDTH,
    FOOTER_BAND_FILL,
    FOOTER_BODY_TOP,
    FOOTER_SEPARATOR_GRAY,
    SEPARATOR_Y,
)
from odoo.tests import HttpCase, TransactionCase, tagged

from .test_api_common import DISPLAY_POLICY_ERROR, TrmnlApiHttpCaseMixin


def _content_sized_white_png():
    """Minimal valid grayscale PNG matching layout renderer output size."""
    from PIL import Image

    img = Image.new("L", (DISPLAY_WIDTH, CONTENT_HEIGHT), color=255)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@tagged("-at_install", "post_install")
class TestFormatLastUpdateTimestamp(TransactionCase):
    """Unit tests for TrmnlProfile._format_last_update_timestamp()."""

    def _get_profile(self):
        return self.env["trmnl.profile"].sudo()

    def test_winter_utc_plus_one(self):
        """January → UTC+1, so 14:00 UTC becomes 15:00 in Zurich tz."""
        self.env.user.tz = "Europe/Zurich"
        poll_at = dt.datetime(2026, 1, 15, 14, 0, 0)
        result = self._get_profile()._format_last_update_timestamp("Dev", poll_at)
        self.assertIn("15.01.2026, 15:00", result)

    def test_summer_utc_plus_two(self):
        """July → UTC+2, so 12:00 UTC becomes 14:00 in Zurich tz."""
        self.env.user.tz = "Europe/Zurich"
        poll_at = dt.datetime(2026, 7, 10, 12, 0, 0)
        result = self._get_profile()._format_last_update_timestamp("Dev", poll_at)
        self.assertIn("10.07.2026, 14:00", result)

    def test_uses_user_timezone(self):
        """A different user tz (New York, UTC-4 in May) shifts the time."""
        self.env.user.tz = "America/New_York"
        poll_at = dt.datetime(2026, 5, 11, 16, 0, 0)
        result = self._get_profile()._format_last_update_timestamp("Dev", poll_at)
        self.assertIn("11.05.2026, 12:00", result)

    def test_falls_back_to_utc_without_user_tz(self):
        """No configured user tz → render in UTC unchanged."""
        self.env.user.tz = False
        poll_at = dt.datetime(2026, 5, 11, 16, 42, 0)
        result = self._get_profile()._format_last_update_timestamp("Dev", poll_at)
        self.assertIn("11.05.2026, 16:42", result)

    def test_label_included(self):
        """Device label appears before the timestamp."""
        poll_at = dt.datetime(2026, 5, 11, 10, 0, 0)
        result = self._get_profile()._format_last_update_timestamp("Lobby Display", poll_at)
        self.assertTrue(result.startswith("Lobby Display · Last update:"))

    def test_format_structure(self):
        """Full format: '<label> · Last update: DD.MM.YYYY, HH:MM'."""
        poll_at = dt.datetime(2026, 5, 11, 16, 42, 0)
        result = self._get_profile()._format_last_update_timestamp("X", poll_at)
        self.assertRegex(result, r"^.+ · Last update: \d{2}\.\d{2}\.\d{4}, \d{2}:\d{2}$")

    def test_format_accepts_mac_as_label(self):
        """Arbitrary label string (e.g. MAC) is embedded verbatim."""
        mac = "AA:BB:CC:DD:EE:02"
        poll_at = dt.datetime(2026, 5, 11, 10, 0, 0)
        result = self._get_profile()._format_last_update_timestamp(mac, poll_at)
        self.assertIn(mac, result)
        self.assertIn("Last update:", result)

    def test_uses_profile_creator_timezone_when_current_user_has_none(self):
        """Device renders as a tz-less public user → fall back to creator's tz."""
        owner = self.env["res.users"].create({
            "name": "Zurich Owner", "login": "tz_owner", "tz": "Europe/Zurich",
        })
        device = self.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:09", "approval_state": "accepted",
        })
        profile = self.env["trmnl.profile"].with_user(owner).sudo().create({
            "name": "P", "device_id": device.id,
        })
        self.env.user.tz = False  # simulate the public/device render context
        result = profile._format_last_update_timestamp("Dev", dt.datetime(2026, 7, 10, 12, 0, 0))
        self.assertIn("10.07.2026, 14:00", result)  # UTC+2 in July


@tagged("-at_install", "post_install")
class TestGetFooterDeviceLabel(TransactionCase):
    """Footer device label: device_name → MAC."""

    def _profile(self, device):
        return self.env["trmnl.profile"].sudo().create({
            "name": "P",
            "device_id": device.id,
        })

    def test_prefers_device_name(self):
        device = self.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:A1",
            "approval_state": "accepted",
        })
        device.write({"device_name": "  Lobby Unit  "})
        self.assertEqual(self._profile(device)._get_footer_device_label(), "Lobby Unit")

@tagged("-at_install", "post_install")
class TestFinalizeDisplayImage(TransactionCase):
    """Unit tests for TrmnlProfile._finalize_display_image()."""

    def setUp(self):
        super().setUp()
        self.device = self.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:02",
            "approval_state": "accepted",
        })

    def _profile(self, **kwargs):
        vals = {
            "name": "Test Profile",
            "device_id": self.device.id,
        }
        vals.update(kwargs)
        return self.env["trmnl.profile"].sudo().create(vals)

    def test_no_poll_at_still_outputs_full_frame(self):
        """Without last_poll_at, footer band is reserved but no text is drawn."""
        profile = self._profile()
        png = _content_sized_white_png()
        result = profile._finalize_display_image(png)
        from PIL import Image

        img = Image.open(io.BytesIO(result))
        self.assertEqual(img.size, (DISPLAY_WIDTH, DISPLAY_HEIGHT))
        px = img.load()
        # Footer separator is drawn as solid gray (no error-diffusion dither).
        self.assertTrue(
            any(px[x, SEPARATOR_Y] < 250 for x in range(DISPLAY_WIDTH)),
            "separator row should be visible",
        )

    def test_with_poll_at_returns_800x480_png(self):
        """When device has last_poll_at, result is a valid full-size PNG."""
        from PIL import Image

        self.device.write({"last_poll_at": dt.datetime(2026, 5, 11, 14, 42, 0)})
        profile = self._profile()
        png = _content_sized_white_png()
        result = profile._finalize_display_image(png)
        img = Image.open(io.BytesIO(result))
        self.assertEqual(img.format, "PNG")
        self.assertEqual(img.size, (DISPLAY_WIDTH, DISPLAY_HEIGHT))

    def test_footer_draws_timestamp_ink(self):
        """Footer text uses dark pixels in the bottom band."""
        from PIL import Image

        self.device.write({
            "last_poll_at": dt.datetime(2026, 5, 11, 14, 42, 0),
            "device_name": "Unit A",
        })
        profile = self._profile()
        result = profile._finalize_display_image(_content_sized_white_png())
        img = Image.open(io.BytesIO(result))
        px = img.load()
        found = any(
            px[x, y] < 160
            for y in range(FOOTER_BODY_TOP, DISPLAY_HEIGHT)
            for x in range(0, DISPLAY_WIDTH)
        )
        self.assertTrue(found, "expected footer text pixels darker than background")

    def test_content_area_not_overpainted_above_separator(self):
        """Main content (white) remains visible just above the separator."""
        from PIL import Image

        self.device.write({"last_poll_at": dt.datetime(2026, 5, 11, 12, 0, 0)})
        profile = self._profile()
        result = profile._finalize_display_image(_content_sized_white_png())
        img = Image.open(io.BytesIO(result))
        px = img.load()
        self.assertGreater(px[400, SEPARATOR_Y - 5], 250)

    def test_corrupt_input_returns_original(self):
        """If PIL fails (corrupt bytes), original bytes are returned without raising."""
        self.device.write({"last_poll_at": dt.datetime(2026, 5, 11, 14, 0, 0)})
        profile = self._profile()
        bad_bytes = b"not a png"
        result = profile._finalize_display_image(bad_bytes)
        self.assertEqual(result, bad_bytes)

    def test_legacy_full_height_content_is_cropped(self):
        """An accidental 800×480 content image is cropped to the content strip."""
        from PIL import Image

        self.device.write({"last_poll_at": dt.datetime(2026, 5, 11, 10, 0, 0)})
        big = Image.new("L", (DISPLAY_WIDTH, DISPLAY_HEIGHT), color=255)
        buf = io.BytesIO()
        big.save(buf, format="PNG")
        profile = self._profile()
        result = profile._finalize_display_image(buf.getvalue())
        out = Image.open(io.BytesIO(result))
        self.assertEqual(out.size, (DISPLAY_WIDTH, DISPLAY_HEIGHT))


@tagged("-at_install", "post_install")
class TestListRendererContentSize(TransactionCase):
    """List/table renderer must match the shared content strip height."""

    def test_list_preview_matches_content_height(self):
        from PIL import Image

        profile = self.env["trmnl.profile"]
        png = profile._render_list_png([{"primary": "cell", "meta": "", "status": ""}])
        img = Image.open(io.BytesIO(png))
        self.assertEqual(img.size, (DISPLAY_WIDTH, CONTENT_HEIGHT))


@tagged("-at_install", "post_install")
class TestPollAtUpdatedOnDisplayPoll(HttpCase, TrmnlApiHttpCaseMixin):
    """Verify that /api/display updates last_poll_at on the device."""

    def test_last_poll_at_set_after_display_poll(self):
        """last_poll_at is populated on the device after a successful poll."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)
        ctx = self._register_device_through_setup()
        device = ctx["device"]

        self.assertFalse(device.last_poll_at)

        with patch(
            "odoo.addons.trmnl.models.trmnl_profile_render.TrmnlProfileRenderMixin._render_and_store_preview"
        ):
            self.url_open(
                "/api/display",
                headers=self._display_headers(ctx["api_token"], device.mac_address),
            )

        device.invalidate_recordset()
        self.assertTrue(device.last_poll_at)

    def test_last_poll_at_updated_on_subsequent_poll(self):
        """last_poll_at advances on every poll."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)
        ctx = self._register_device_through_setup()
        device = ctx["device"]

        fixed_first = dt.datetime(2026, 5, 11, 10, 0, 0)
        fixed_second = dt.datetime(2026, 5, 11, 10, 30, 0)

        with patch("odoo.fields.Datetime.now", return_value=fixed_first), \
             patch(
                 "odoo.addons.trmnl.models.trmnl_profile_render.TrmnlProfileRenderMixin._render_and_store_preview"
             ):
            self.url_open(
                "/api/display",
                headers=self._display_headers(ctx["api_token"], device.mac_address),
            )

        device.invalidate_recordset()
        self.assertEqual(device.last_poll_at, fixed_first)

        with patch("odoo.fields.Datetime.now", return_value=fixed_second), \
             patch(
                 "odoo.addons.trmnl.models.trmnl_profile_render.TrmnlProfileRenderMixin._render_and_store_preview"
             ):
            self.url_open(
                "/api/display",
                headers=self._display_headers(ctx["api_token"], device.mac_address),
            )

        device.invalidate_recordset()
        self.assertEqual(device.last_poll_at, fixed_second)
