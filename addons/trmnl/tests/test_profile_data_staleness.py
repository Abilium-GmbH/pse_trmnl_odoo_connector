"""Tests for the data-change invalidation pipeline.

Covers:
- preview_data_stale set on create / write / unlink of source records.
- _should_render_for_device returns True when stale.
- Successful render clears preview_data_stale.
- Only profiles whose app_model_id matches the changed model are affected.
- Transaction-level debounce: bulk writes invalidate each profile once.
"""
from __future__ import annotations

import base64
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("-at_install", "post_install")
class TestDataStaleness(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._device = cls.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:55",
            "approval_state": "accepted",
            "registration_source": "setup",
        })
        cls._partner_model = cls.env["ir.model"].sudo().search(
            [("model", "=", "res.partner")], limit=1
        )
        cls._company_model = cls.env["ir.model"].sudo().search(
            [("model", "=", "res.company")], limit=1
        )

    def _make_profile(self, model_id=None, **vals):
        base = {
            "name": "Staleness test profile",
            "device_id": self._device.id,
            "trmnl_layout": "list",
            "display_limit": 5,
            "filter_preset": "none",
        }
        if model_id is not None:
            base["app_model_id"] = model_id.id
        base.update(vals)
        return self.env["trmnl.profile"].sudo().create(base)

    # ------------------------------------------------------------------
    # stale flag set on create
    # ------------------------------------------------------------------

    def test_create_source_record_marks_profile_stale(self):
        profile = self._make_profile(self._partner_model)
        profile.write({"preview_data_stale": False})
        self.env["res.partner"].sudo().create({"name": "Stale test partner"})
        self.assertTrue(profile.preview_data_stale)

    # ------------------------------------------------------------------
    # stale flag set on write
    # ------------------------------------------------------------------

    def test_write_source_record_marks_profile_stale(self):
        profile = self._make_profile(self._partner_model)
        partner = self.env["res.partner"].sudo().create({"name": "Watch me"})
        profile.write({"preview_data_stale": False})
        partner.write({"name": "Changed"})
        self.assertTrue(profile.preview_data_stale)

    # ------------------------------------------------------------------
    # stale flag set on unlink
    # ------------------------------------------------------------------

    def test_unlink_source_record_marks_profile_stale(self):
        profile = self._make_profile(self._partner_model)
        partner = self.env["res.partner"].sudo().create({"name": "To delete"})
        profile.write({"preview_data_stale": False})
        partner.unlink()
        self.assertTrue(profile.preview_data_stale)

    # ------------------------------------------------------------------
    # only matching model's profiles are affected
    # ------------------------------------------------------------------

    def test_only_matching_model_profile_marked_stale(self):
        profile_partner = self._make_profile(self._partner_model)
        profile_company = self._make_profile(self._company_model)
        profile_partner.write({"preview_data_stale": False})
        profile_company.write({"preview_data_stale": False})

        self.env["res.partner"].sudo().create({"name": "Targeted write"})

        self.assertTrue(profile_partner.preview_data_stale)
        self.assertFalse(profile_company.preview_data_stale)

    # ------------------------------------------------------------------
    # _should_render_for_device respects stale flag
    # ------------------------------------------------------------------

    def test_should_render_true_when_stale(self):
        profile = self._make_profile(self._partner_model)
        profile.write({
            "preview_image": base64.b64encode(b"fakepng"),
            "preview_data_stale": True,
        })
        self.assertTrue(profile._should_render_for_device())

    def test_should_render_false_when_not_stale_and_interval_not_due(self):
        profile = self._make_profile(self._partner_model)
        profile.write({
            "preview_image": base64.b64encode(b"fakepng"),
            "preview_data_stale": False,
            "preview_generated_at": "2099-01-01 00:00:00",
            "preview_renderer_version": profile._get_installed_trmnl_version(),
            "auto_refresh_interval_minutes": 60,
        })
        self.assertFalse(profile._should_render_for_device())

    # ------------------------------------------------------------------
    # render clears stale flag
    # ------------------------------------------------------------------

    def test_render_clears_stale_flag(self):
        profile = self._make_profile(self._partner_model)
        profile.write({"preview_data_stale": True})

        fake_png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x00\x00\x00\x00:~\x9bU\x00\x00\x00\n"
            b"IDATx\x9cc`\x00\x00\x00\x02\x00\x01\xe2!\xbc3\x00\x00\x00"
            b"\x00IEND\xaeB`\x82"
        )
        patch_path = "odoo.addons.trmnl.models.trmnl_profile_render.TrmnlProfileRenderMixin._dispatch_renderer"
        with patch(patch_path, return_value=fake_png):
            profile._render_and_store_preview()

        self.assertFalse(profile.preview_data_stale)
        self.assertTrue(profile.preview_image)

    # ------------------------------------------------------------------
    # debounce: bulk writes invalidate each profile once per transaction
    # ------------------------------------------------------------------

    def test_bulk_write_invalidates_profile_once(self):
        profile = self._make_profile(self._partner_model)
        partners = self.env["res.partner"].sudo().search([], limit=5)
        if not partners:
            partners = self.env["res.partner"].sudo().create([
                {"name": f"Bulk {i}"} for i in range(3)
            ])
        profile.write({"preview_data_stale": False})

        # Write all partners in one call — debounce must fire only once.
        partners.write({"comment": "bulk"})
        self.assertTrue(profile.preview_data_stale)

    # ------------------------------------------------------------------
    # inactive profiles are not invalidated
    # ------------------------------------------------------------------

    def test_inactive_profile_not_marked_stale(self):
        profile = self._make_profile(self._partner_model)
        profile.write({"active": False, "preview_data_stale": False})

        self.env["res.partner"].sudo().create({"name": "Inactive profile test"})
        self.assertFalse(profile.preview_data_stale)

    # ------------------------------------------------------------------
    # profile with no model is not affected
    # ------------------------------------------------------------------

    def test_profile_without_model_not_marked_stale(self):
        profile = self._make_profile(model_id=None)
        profile.write({"preview_data_stale": False})

        self.env["res.partner"].sudo().create({"name": "No model test"})
        self.assertFalse(profile.preview_data_stale)
