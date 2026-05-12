"""Tests for app-specific TRMNL profile display presets (trmnl.profile)."""

from __future__ import annotations

from odoo.tests import TransactionCase, tagged


def _installed_module(env, name):
    return env["ir.module.module"].sudo().search(
        [("name", "=", name), ("state", "=", "installed")],
        limit=1,
    )


@tagged("-at_install", "post_install")
class TestProfileDisplayPresets(TransactionCase):
    """Apply ``_APP_DISPLAY_PRESETS`` for known Odoo apps."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._has_project = "project.task" in cls.env and bool(_installed_module(cls.env, "project"))
        cls._has_crm = "crm.lead" in cls.env and bool(_installed_module(cls.env, "crm"))
        cls._has_pos = "pos.order" in cls.env and bool(_installed_module(cls.env, "point_of_sale"))

    def _device(self):
        return self.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:99",
            "approval_state": "accepted",
            "registration_source": "setup",
        })

    def _profile(self, **vals):
        base = {
            "name": "Preset test",
            "device_id": self._device().id,
        }
        base.update(vals)
        return self.env["trmnl.profile"].sudo().create(base)

    def test_project_tasks_detail_preset(self):
        if not self._has_project:
            self.skipTest("project module not installed")
        mod = _installed_module(self.env, "project")
        profile = self._profile(app_module_id=mod.id)
        profile.project_display_mode = "project_tasks_detail"
        profile._apply_app_display_preset_from_mode()
        self.assertEqual(profile.odoo_action_id.res_model, "project.task")
        names = profile.display_field_ids.mapped("name")
        self.assertIn("name", names)
        self.assertIn("project_id", names)
        self.assertIn("stage_id", names)

    def test_project_projects_overview_preset(self):
        if not self._has_project:
            self.skipTest("project module not installed")
        mod = _installed_module(self.env, "project")
        profile = self._profile(app_module_id=mod.id)
        profile.project_display_mode = "project_projects_overview"
        profile._apply_app_display_preset_from_mode()
        self.assertEqual(profile.odoo_action_id.res_model, "project.project")
        names = profile.display_field_ids.mapped("name")
        self.assertIn("name", names)

    def test_crm_pipeline_read_group_field(self):
        if not self._has_crm:
            self.skipTest("crm module not installed")
        mod = _installed_module(self.env, "crm")
        profile = self._profile(app_module_id=mod.id)
        profile.crm_display_mode = "crm_pipeline"
        profile._apply_app_display_preset_from_mode()
        self.assertEqual(profile.odoo_action_id.res_model, "crm.lead")
        self.assertEqual(profile.trmnl_read_group_field_name, "stage_id")

    def test_pos_orders_preset(self):
        if not self._has_pos:
            self.skipTest("point_of_sale module not installed")
        mod = _installed_module(self.env, "point_of_sale")
        profile = self._profile(app_module_id=mod.id)
        profile.pos_display_mode = "pos_orders"
        profile._apply_app_display_preset_from_mode()
        self.assertEqual(profile.odoo_action_id.res_model, "pos.order")
        names = profile.display_field_ids.mapped("name")
        self.assertIn("name", names)
        self.assertIn("amount_total", names)

    def test_unknown_app_no_display_mode_branch(self):
        """Apps without preset keys keep generic behaviour (no forced display mode)."""
        mail = _installed_module(self.env, "mail")
        if not mail:
            self.skipTest("mail module not installed")
        profile = self._profile(app_module_id=mail.id)
        self.assertFalse(profile.project_display_mode)
        self.assertFalse(profile._active_display_preset_key())

    def test_optional_fields_skipped_silently(self):
        """Preset fields missing on the model are omitted from display_field_ids."""
        if not self._has_project:
            self.skipTest("project module not installed")
        mod = _installed_module(self.env, "project")
        profile = self._profile(app_module_id=mod.id)
        profile.project_display_mode = "project_projects_overview"
        profile._apply_app_display_preset_from_mode()
        for field in profile.display_field_ids:
            self.assertEqual(field.model, "project.project")
