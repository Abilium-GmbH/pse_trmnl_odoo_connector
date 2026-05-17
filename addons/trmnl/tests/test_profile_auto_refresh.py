"""Tests for profile render-interval behaviour during /api/display polling."""

import base64
import datetime as dt
import hashlib
from unittest.mock import patch

from odoo.tests import HttpCase, TransactionCase, tagged

from .test_api_common import DISPLAY_POLICY_ERROR, TrmnlApiHttpCaseMixin

_FAKE_PNG = base64.b64encode(b"fakepng").decode()


# ---------------------------------------------------------------------------
# Unit tests — _is_auto_refresh_due logic (no HTTP server needed)
# ---------------------------------------------------------------------------

@tagged("-at_install", "post_install")
class TestIsAutoRefreshDue(TransactionCase):
    """Unit tests for TrmnlProfile._is_auto_refresh_due().

    auto_refresh_enabled has been removed; refresh is always active.
    The method only checks preview_generated_at against the interval.
    """

    def setUp(self):
        super().setUp()
        self.device = self.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:01",
            "approval_state": "accepted",
            "registration_source": "setup",
        })

    def _profile(self, **kwargs):
        vals = {
            "name": "Test Profile",
            "device_id": self.device.id,
            "auto_refresh_interval_minutes": 10,
        }
        vals.update(kwargs)
        return self.env["trmnl.profile"].sudo().create(vals)

    def test_no_generated_at_returns_true(self):
        """No previous render → always due."""
        profile = self._profile(preview_generated_at=False)
        self.assertTrue(profile._is_auto_refresh_due())

    def test_fresh_preview_returns_false(self):
        """Preview rendered 5 min ago with 10-min interval → not due."""
        now = dt.datetime(2026, 5, 11, 12, 0, 0)
        profile = self._profile(
            auto_refresh_interval_minutes=10,
            preview_generated_at=now - dt.timedelta(minutes=5),
        )
        with patch("odoo.fields.Datetime.now", return_value=now):
            self.assertFalse(profile._is_auto_refresh_due())

    def test_stale_preview_returns_true(self):
        """Preview rendered 15 min ago with 10-min interval → due."""
        now = dt.datetime(2026, 5, 11, 12, 0, 0)
        profile = self._profile(
            auto_refresh_interval_minutes=10,
            preview_generated_at=now - dt.timedelta(minutes=15),
        )
        with patch("odoo.fields.Datetime.now", return_value=now):
            self.assertTrue(profile._is_auto_refresh_due())

    def test_exactly_at_threshold_returns_true(self):
        """Preview exactly at the interval boundary is considered due."""
        now = dt.datetime(2026, 5, 11, 12, 0, 0)
        profile = self._profile(
            auto_refresh_interval_minutes=10,
            preview_generated_at=now - dt.timedelta(minutes=10),
        )
        with patch("odoo.fields.Datetime.now", return_value=now):
            self.assertTrue(profile._is_auto_refresh_due())

    def test_zero_interval_defaults_to_ten_minutes_fresh(self):
        """Zero interval falls back to 10 min — fresh preview not due."""
        now = dt.datetime(2026, 5, 11, 12, 0, 0)
        profile = self._profile(
            auto_refresh_interval_minutes=0,
            preview_generated_at=now - dt.timedelta(minutes=5),
        )
        with patch("odoo.fields.Datetime.now", return_value=now):
            self.assertFalse(profile._is_auto_refresh_due())

    def test_zero_interval_defaults_to_ten_minutes_stale(self):
        """Zero interval falls back to 10 min — stale preview is due."""
        now = dt.datetime(2026, 5, 11, 12, 0, 0)
        profile = self._profile(
            auto_refresh_interval_minutes=0,
            preview_generated_at=now - dt.timedelta(minutes=15),
        )
        with patch("odoo.fields.Datetime.now", return_value=now):
            self.assertTrue(profile._is_auto_refresh_due())

    def test_negative_interval_defaults_to_ten_minutes(self):
        """Negative interval falls back to 10 min — fresh preview not due."""
        now = dt.datetime(2026, 5, 11, 12, 0, 0)
        profile = self._profile(
            auto_refresh_interval_minutes=-5,
            preview_generated_at=now - dt.timedelta(minutes=5),
        )
        with patch("odoo.fields.Datetime.now", return_value=now):
            self.assertFalse(profile._is_auto_refresh_due())

    def test_multiple_active_profiles_prefers_lowest_sequence(self):
        """Display polling uses one deterministic profile when several are active."""
        self._profile(name="Later", sequence=100)
        lo = self._profile(name="First", sequence=5)
        found = self.env["trmnl.profile"].sudo().search(
            [("device_id", "=", self.device.id), ("active", "=", True)],
            limit=1,
            order="sequence asc, id asc",
        )
        self.assertEqual(found.id, lo.id)

    def test_display_filename_suffix_matches_png_hash(self):
        """Filenames include a hash so two renders in the same second still differ if PNG differs."""
        ts = dt.datetime(2026, 5, 11, 12, 0, 0)
        profile = self._profile(
            preview_image=_FAKE_PNG,
            preview_generated_at=ts,
        )
        fn = profile._get_display_filename()
        raw = base64.b64decode(_FAKE_PNG)
        expected_digest = hashlib.sha256(raw).hexdigest()[:12]
        self.assertIn(expected_digest, fn)
        self.assertTrue(fn.startswith(f"profile_{profile.id}_"))

    def test_refresh_always_active_no_field_to_disable(self):
        """auto_refresh_enabled field no longer exists; refresh cannot be disabled."""
        profile = self._profile(preview_generated_at=False)
        self.assertFalse(hasattr(profile, "auto_refresh_enabled"),
                         "auto_refresh_enabled was removed; it should not exist as a field")
        # A profile with no prior render is always due.
        self.assertTrue(profile._is_auto_refresh_due())


# ---------------------------------------------------------------------------
# Integration tests — display polling triggers / skips render
# ---------------------------------------------------------------------------

@tagged("-at_install", "post_install")
class TestAutoRefreshOnDisplayPoll(HttpCase, TrmnlApiHttpCaseMixin):
    """Verify that /api/display triggers re-render only when appropriate."""

    def _make_profile(self, device, **kwargs):
        """Create a profile with a stored preview image."""
        vals = {
            "name": "Test Profile",
            "device_id": device.id,
            "preview_image": _FAKE_PNG,
            "preview_generated_at": dt.datetime(2026, 5, 11, 10, 0, 0),
            "auto_refresh_interval_minutes": 10,
        }
        vals.update(kwargs)
        return self.env["trmnl.profile"].sudo().create(vals)

    def test_no_preview_image_triggers_render_on_poll(self):
        """Profile with no preview image renders on first poll."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)
        ctx = self._register_device_through_setup()

        self.env["trmnl.profile"].sudo().create({
            "name": "Test",
            "device_id": ctx["device"].id,
            "auto_refresh_interval_minutes": 10,
        })

        with patch(
            "odoo.addons.trmnl.models.trmnl_profile_render.TrmnlProfileRenderMixin._render_and_store_preview"
        ) as mock_render:
            self.url_open(
                "/api/display",
                headers=self._display_headers(ctx["api_token"], ctx["device"].mac_address),
            )

        mock_render.assert_called_once()

    def test_fresh_preview_does_not_trigger_render(self):
        """A fresh preview is served as-is without re-rendering."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)
        ctx = self._register_device_through_setup()

        now = dt.datetime(2026, 5, 11, 12, 0, 0)
        profile = self._make_profile(
            ctx["device"],
            preview_generated_at=now - dt.timedelta(minutes=5),
        )
        profile.write({
            "preview_renderer_version": profile._get_installed_trmnl_version(),
        })

        with patch("odoo.fields.Datetime.now", return_value=now), \
             patch(
                 "odoo.addons.trmnl.models.trmnl_profile_render.TrmnlProfileRenderMixin._render_and_store_preview"
             ) as mock_render:
            self.url_open(
                "/api/display",
                headers=self._display_headers(ctx["api_token"], ctx["device"].mac_address),
            )

        mock_render.assert_not_called()

    def test_stale_renderer_version_triggers_render_on_poll(self):
        """After a module upgrade, the next poll re-renders even if the interval is fresh."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)
        ctx = self._register_device_through_setup()

        now = dt.datetime(2026, 5, 11, 12, 0, 0)
        profile = self._make_profile(
            ctx["device"],
            preview_generated_at=now - dt.timedelta(minutes=1),
            preview_renderer_version="0.0.0",
        )

        with patch("odoo.fields.Datetime.now", return_value=now), \
             patch(
                 "odoo.addons.trmnl.models.trmnl_profile_render.TrmnlProfileRenderMixin._render_and_store_preview"
             ) as mock_render:
            self.url_open(
                "/api/display",
                headers=self._display_headers(ctx["api_token"], ctx["device"].mac_address),
            )

        mock_render.assert_called_once()

    def test_stale_preview_triggers_render_on_poll(self):
        """A preview older than the interval is re-rendered on the next poll."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)
        ctx = self._register_device_through_setup()

        now = dt.datetime(2026, 5, 11, 12, 0, 0)
        self._make_profile(
            ctx["device"],
            preview_generated_at=now - dt.timedelta(minutes=15),
        )

        with patch("odoo.fields.Datetime.now", return_value=now), \
             patch(
                 "odoo.addons.trmnl.models.trmnl_profile_render.TrmnlProfileRenderMixin._render_and_store_preview"
             ) as mock_render:
            self.url_open(
                "/api/display",
                headers=self._display_headers(ctx["api_token"], ctx["device"].mac_address),
            )

        mock_render.assert_called_once()

    def test_filename_changes_after_render(self):
        """Re-rendering updates preview_generated_at so the filename changes."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)
        ctx = self._register_device_through_setup()

        old_ts = dt.datetime(2026, 5, 11, 10, 0, 0)
        profile = self._make_profile(ctx["device"], preview_generated_at=old_ts)
        old_filename = profile._get_display_filename()

        new_ts = dt.datetime(2026, 5, 11, 10, 30, 0)
        profile.write({"preview_generated_at": new_ts})

        new_filename = profile._get_display_filename()
        self.assertNotEqual(old_filename, new_filename)
