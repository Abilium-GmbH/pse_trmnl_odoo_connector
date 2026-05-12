"""Backward-compatibility tests for TRMNL profiles after the model-first refactor.

Scenarios covered:
- Old-style profile (app_module_id + odoo_action_id, no app_model_id) renders correctly.
- _backfill_model_id() writes app_model_id from odoo_action_id.res_model.
- _backfill_model_id() is idempotent when app_model_id is already set.
- _backfill_model_id() returns False gracefully when neither field is available.
- post_init_hook logic (via backfill_profiles) migrates old records in bulk.
"""

from __future__ import annotations

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestProfileBackwardCompat(TransactionCase):
    """Old-style profiles (no app_model_id) survive the model-first refactor."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._device = cls.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:44",
            "approval_state": "accepted",
            "registration_source": "setup",
        })
        # Pick any action whose res_model is definitely installed.
        cls._partner_action = cls.env["ir.actions.act_window"].sudo().search(
            [("res_model", "=", "res.partner")], limit=1, order="id asc"
        )

    def _old_style_profile(self, **extra):
        """Create a profile with odoo_action_id but no app_model_id — simulates pre-refactor data."""
        vals = {
            "name": "Old-style profile",
            "device_id": self._device.id,
            "trmnl_layout": "list",
            "display_limit": 3,
            "filter_preset": "none",
        }
        vals.update(extra)
        profile = self.env["trmnl.profile"].sudo().create(vals)
        # Bypass the onchange so app_model_id is NOT set (real old-style state).
        profile.write({"app_model_id": False})
        return profile

    # ------------------------------------------------------------------
    # _backfill_model_id
    # ------------------------------------------------------------------

    def test_backfill_sets_app_model_id_from_action(self):
        """_backfill_model_id populates app_model_id from odoo_action_id.res_model."""
        if not self._partner_action:
            self.skipTest("No ir.actions.act_window for res.partner found")
        profile = self._old_style_profile(odoo_action_id=self._partner_action.id)
        self.assertFalse(profile.app_model_id)

        result = profile._backfill_model_id()

        self.assertTrue(result)
        self.assertEqual(profile.app_model_id.model, "res.partner")

    def test_backfill_is_idempotent_when_model_already_set(self):
        """_backfill_model_id returns True and does not re-write when app_model_id is set."""
        ir_model = self.env["ir.model"].sudo().search(
            [("model", "=", "res.partner")], limit=1
        )
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "Already migrated",
            "device_id": self._device.id,
            "app_model_id": ir_model.id,
            "trmnl_layout": "list",
        })
        original_id = profile.app_model_id.id
        result = profile._backfill_model_id()
        self.assertTrue(result)
        self.assertEqual(profile.app_model_id.id, original_id)

    def test_backfill_returns_false_when_no_action(self):
        """_backfill_model_id returns False when neither app_model_id nor odoo_action_id is set."""
        profile = self._old_style_profile()
        self.assertFalse(profile.app_model_id)
        self.assertFalse(profile.odoo_action_id)
        result = profile._backfill_model_id()
        self.assertFalse(result)
        self.assertFalse(profile.app_model_id)

    # ------------------------------------------------------------------
    # rendering
    # ------------------------------------------------------------------

    def test_old_style_profile_renders_via_action_render_preview(self):
        """action_render_preview migrates and renders an old-style profile without error."""
        if not self._partner_action:
            self.skipTest("No ir.actions.act_window for res.partner found")
        profile = self._old_style_profile(odoo_action_id=self._partner_action.id)
        self.assertFalse(profile.app_model_id)

        profile.action_render_preview()

        # app_model_id must have been backfilled.
        self.assertEqual(profile.app_model_id.model, "res.partner")
        # Preview image must have been generated.
        self.assertTrue(profile.preview_image)
        self.assertTrue(profile.preview_generated_at)

    def test_old_style_profile_renders_via_render_and_store(self):
        """_render_and_store_preview migrates and renders an old-style profile."""
        if not self._partner_action:
            self.skipTest("No ir.actions.act_window for res.partner found")
        profile = self._old_style_profile(odoo_action_id=self._partner_action.id)
        self.assertFalse(profile.app_model_id)

        profile._render_and_store_preview()

        self.assertEqual(profile.app_model_id.model, "res.partner")
        self.assertTrue(profile.preview_image)

    def test_render_raises_user_error_when_no_model_and_no_action(self):
        """A fully unconfigured profile (no model, no action) raises UserError."""
        profile = self._old_style_profile()
        with self.assertRaises(UserError):
            profile._render_and_store_preview()

    # ------------------------------------------------------------------
    # post_init_hook logic
    # ------------------------------------------------------------------

    def test_post_init_hook_backfills_profiles_in_bulk(self):
        """The post_init_hook logic migrates multiple old-style profiles in one pass."""
        if not self._partner_action:
            self.skipTest("No ir.actions.act_window for res.partner found")

        profiles = []
        for i in range(3):
            p = self._old_style_profile(
                name=f"Hook migration test {i}",
                odoo_action_id=self._partner_action.id,
            )
            self.assertFalse(p.app_model_id)
            profiles.append(p)

        # Run the same logic the hook uses.
        from odoo.addons.trmnl.hooks import post_init_hook
        post_init_hook(self.env)

        for p in profiles:
            p.invalidate_recordset()
            self.assertEqual(
                p.app_model_id.model,
                "res.partner",
                f"Profile id={p.id} was not migrated by post_init_hook",
            )

    def test_post_init_hook_skips_already_migrated_profiles(self):
        """post_init_hook does not touch profiles that already have app_model_id."""
        ir_model = self.env["ir.model"].sudo().search(
            [("model", "=", "res.partner")], limit=1
        )
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "Already migrated hook test",
            "device_id": self._device.id,
            "app_model_id": ir_model.id,
            "trmnl_layout": "list",
        })
        original_model_id = profile.app_model_id.id

        from odoo.addons.trmnl.hooks import post_init_hook
        post_init_hook(self.env)

        profile.invalidate_recordset()
        self.assertEqual(profile.app_model_id.id, original_model_id)
