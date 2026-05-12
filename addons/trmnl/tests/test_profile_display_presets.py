"""Tests for TRMNL profile model-first display presets and rendering."""

from __future__ import annotations

from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestModelFirstProfile(TransactionCase):
    """Profile configured via app_model_id — no app_module_id required."""

    def _device(self):
        return self.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:77",
            "approval_state": "accepted",
            "registration_source": "setup",
        })

    def _ir_model(self, model_name):
        return self.env["ir.model"].sudo().search([("model", "=", model_name)], limit=1)

    def _profile(self, model_name, **extra):
        ir_model = self._ir_model(model_name)
        self.assertTrue(ir_model, f"ir.model record for {model_name!r} must exist")
        vals = {
            "name": f"Test – {model_name}",
            "device_id": self._device().id,
            "app_model_id": ir_model.id,
            "trmnl_layout": "list",
            "display_limit": 3,
            "filter_preset": "none",
        }
        vals.update(extra)
        return self.env["trmnl.profile"].sudo().create(vals)

    # ------------------------------------------------------------------
    # Rendering without app_module_id
    # ------------------------------------------------------------------

    def test_render_without_app_module(self):
        """Profile with app_model_id but no app_module_id renders successfully."""
        profile = self._profile("res.partner")
        self.assertFalse(profile.app_module_id if hasattr(profile, "app_module_id") else False)
        profile._render_and_store_preview()
        self.assertTrue(profile.preview_image)
        self.assertTrue(profile.preview_generated_at)

    def test_render_raises_without_model(self):
        """Rendering without app_model_id raises UserError."""
        from odoo.exceptions import UserError
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "No model",
            "device_id": self._device().id,
            "trmnl_layout": "list",
        })
        self.assertFalse(profile.app_model_id)
        with self.assertRaises(UserError):
            profile._render_and_store_preview()

    def test_app_module_id_field_removed_or_not_required(self):
        """app_module_id no longer exists on the model, or is irrelevant to rendering."""
        profile = self._profile("res.partner")
        # Rendering must succeed regardless of whether app_module_id is set.
        profile._render_and_store_preview()
        self.assertTrue(profile.preview_image)

    # ------------------------------------------------------------------
    # Model preset application via _apply_model_preset
    # ------------------------------------------------------------------

    def test_model_preset_applies_for_calendar_event(self):
        """_apply_model_preset sets calendar layout for calendar.event."""
        ir_model = self._ir_model("calendar.event")
        if not ir_model:
            self.skipTest("calendar.event not available")
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "Calendar preset test",
            "device_id": self._device().id,
        })
        profile.app_model_id = ir_model
        profile._onchange_app_model_id()
        self.assertEqual(profile.trmnl_layout, "calendar")
        self.assertEqual(profile.calendar_view_mode, "month")

    def test_model_preset_applies_for_crm_lead(self):
        """_apply_model_preset sets read_group field for crm.lead."""
        if "crm.lead" not in self.env:
            self.skipTest("crm.lead not available")
        ir_model = self._ir_model("crm.lead")
        if not ir_model:
            self.skipTest("ir.model record for crm.lead not found")
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "CRM preset test",
            "device_id": self._device().id,
        })
        profile.app_model_id = ir_model
        profile._onchange_app_model_id()
        self.assertEqual(profile.trmnl_read_group_field_name, "stage_id")

    def test_model_preset_applies_pos_display_mode(self):
        """_apply_model_preset sets pos_display_mode=pos_dashboard for pos.order."""
        if "pos.order" not in self.env:
            self.skipTest("pos.order not available")
        ir_model = self._ir_model("pos.order")
        if not ir_model:
            self.skipTest("ir.model record for pos.order not found")
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "POS preset test",
            "device_id": self._device().id,
        })
        profile.app_model_id = ir_model
        profile._onchange_app_model_id()
        self.assertEqual(profile.pos_display_mode, "pos_dashboard")

    def test_preset_fields_validated_against_installed_model(self):
        """Fields in _MODEL_DISPLAY_PRESETS that do not exist on the model are silently skipped."""
        if "crm.lead" not in self.env:
            self.skipTest("crm.lead not available")
        profile = self._profile("crm.lead")
        for field_rec in profile.display_field_ids:
            self.assertEqual(field_rec.model, "crm.lead",
                             f"Field {field_rec.name!r} belongs to {field_rec.model!r}, not crm.lead")

    def test_unknown_model_no_preset_uses_defaults(self):
        """A model not in _MODEL_DISPLAY_PRESETS gets sensible field defaults."""
        profile = self._profile("res.users")
        # No preset for res.users → display_field_ids is empty (set by _apply_model_preset=False).
        # Rendering must still work, falling back to display_name.
        profile._render_and_store_preview()
        self.assertTrue(profile.preview_image)

    # ------------------------------------------------------------------
    # model is source of truth over action
    # ------------------------------------------------------------------

    def test_model_is_source_of_truth_over_action(self):
        """app_model_id.model is used for rendering even when odoo_action_id is absent."""
        profile = self._profile("res.partner", display_limit=1)
        self.assertFalse(profile.odoo_action_id)
        profile._render_and_store_preview()
        self.assertTrue(profile.preview_image)

    # ------------------------------------------------------------------
    # Onchange clears pos_display_mode when model changes
    # ------------------------------------------------------------------

    def test_onchange_clears_pos_display_mode_on_model_change(self):
        """Switching from pos.order to another model clears pos_display_mode."""
        if "pos.order" not in self.env:
            self.skipTest("pos.order not available")
        pos_model = self._ir_model("pos.order")
        partner_model = self._ir_model("res.partner")
        if not pos_model or not partner_model:
            self.skipTest("Required ir.model records not found")
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "Mode clear test",
            "device_id": self._device().id,
            "app_model_id": pos_model.id,
            "pos_display_mode": "pos_dashboard",
        })
        # Simulate switching to res.partner.
        profile.app_model_id = partner_model
        profile._onchange_app_model_id()
        self.assertFalse(profile.pos_display_mode)

    # ------------------------------------------------------------------
    # CRM calendar renders without crm_display_mode
    # ------------------------------------------------------------------

    def test_crm_calendar_renders_without_crm_display_mode(self):
        """Calendar layout for crm.lead works in model-first flow."""
        if "crm.lead" not in self.env:
            self.skipTest("crm.lead not available")
        crm_model = self._ir_model("crm.lead")
        if not crm_model:
            self.skipTest("ir.model record for crm.lead not found")
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "CRM calendar model-first",
            "device_id": self._device().id,
            "app_model_id": crm_model.id,
            "trmnl_layout": "calendar",
            "display_limit": 50,
            "filter_preset": "this_month",
            "calendar_view_mode": "month",
            "calendar_reference_mode": "today",
        })
        self.assertFalse(getattr(profile, "crm_display_mode", None))
        profile._render_and_store_preview()
        self.assertTrue(profile.preview_image)

    # ------------------------------------------------------------------
    # POS dashboard still works
    # ------------------------------------------------------------------

    def test_pos_dashboard_renders(self):
        """POS dashboard KPI renderer works when pos_display_mode=pos_dashboard."""
        if "pos.order" not in self.env:
            self.skipTest("pos.order not available")
        pos_model = self._ir_model("pos.order")
        if not pos_model:
            self.skipTest("ir.model record for pos.order not found")
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "POS dashboard test",
            "device_id": self._device().id,
            "app_model_id": pos_model.id,
            "trmnl_layout": "list",
            "pos_display_mode": "pos_dashboard",
            "filter_preset": "none",
            "display_limit": 10,
        })
        profile._render_and_store_preview()
        self.assertTrue(profile.preview_image)


@tagged("-at_install", "post_install")
class TestLayoutAwareFieldPicker(TransactionCase):
    """display_field_ids is filtered by layout — type blacklist and preset validation."""

    def _device(self):
        return self.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:88",
            "approval_state": "accepted",
            "registration_source": "setup",
        })

    def _ir_model(self, model_name):
        return self.env["ir.model"].sudo().search([("model", "=", model_name)], limit=1)

    def _profile(self, layout="list", **extra):
        ir_model = self._ir_model("res.partner")
        vals = {
            "name": f"Layout picker test ({layout})",
            "device_id": self._device().id,
            "app_model_id": ir_model.id,
            "trmnl_layout": layout,
            "display_limit": 5,
            "filter_preset": "none",
        }
        vals.update(extra)
        return self.env["trmnl.profile"].sudo().create(vals)

    # ------------------------------------------------------------------
    # Layout allowed-type constants
    # ------------------------------------------------------------------

    def test_layout_allowed_ttypes_constant_exists(self):
        """_LAYOUT_ALLOWED_TTYPES covers list, table, kanban, kpi layouts."""
        from odoo.addons.trmnl.models.trmnl_profile import _LAYOUT_ALLOWED_TTYPES
        for layout in ("list", "table", "kanban", "kpi"):
            self.assertIn(layout, _LAYOUT_ALLOWED_TTYPES,
                          f"Layout {layout!r} must be in _LAYOUT_ALLOWED_TTYPES")

    def test_list_allows_char_and_excludes_nothing_scalar(self):
        """list/table/kanban layouts allow broad scalar types including char and date."""
        from odoo.addons.trmnl.models.trmnl_profile import _LAYOUT_ALLOWED_TTYPES
        list_allowed = _LAYOUT_ALLOWED_TTYPES["list"]
        for t in ("char", "integer", "float", "date", "datetime", "boolean"):
            self.assertIn(t, list_allowed, f"{t!r} must be allowed for list layout")

    def test_kpi_restricts_to_numeric_types(self):
        """kpi layout only allows integer, float, monetary, selection, many2one, boolean."""
        from odoo.addons.trmnl.models.trmnl_profile import _LAYOUT_ALLOWED_TTYPES
        kpi_allowed = _LAYOUT_ALLOWED_TTYPES["kpi"]
        for t in ("char", "text", "date", "datetime"):
            self.assertNotIn(t, kpi_allowed, f"{t!r} must NOT be allowed for kpi layout")
        for t in ("integer", "float", "monetary", "boolean"):
            self.assertIn(t, kpi_allowed, f"{t!r} must be allowed for kpi layout")

    # ------------------------------------------------------------------
    # Onchange drops stale fields when layout changes
    # ------------------------------------------------------------------

    def test_onchange_layout_to_kpi_drops_char_fields(self):
        """Switching to kpi layout removes char/text/date fields from display_field_ids."""
        partner_model = self._ir_model("res.partner")
        # Find a char field and an integer field on res.partner.
        char_field = self.env["ir.model.fields"].sudo().search([
            ("model", "=", "res.partner"),
            ("ttype", "=", "char"),
            ("name", "not in", ["display_name"]),
        ], limit=1)
        int_field = self.env["ir.model.fields"].sudo().search([
            ("model", "=", "res.partner"),
            ("ttype", "in", ["integer", "float", "monetary"]),
        ], limit=1)
        if not char_field or not int_field:
            self.skipTest("Required ir.model.fields entries not found")

        profile = self._profile(layout="list")
        profile.write({"display_field_ids": [(6, 0, [char_field.id, int_field.id])]})
        self.assertIn(char_field.id, profile.display_field_ids.ids)

        # Simulate onchange to kpi.
        profile.trmnl_layout = "kpi"
        profile._onchange_trmnl_layout()

        self.assertNotIn(char_field.id, profile.display_field_ids.ids,
                         "char field should be dropped when switching to kpi layout")
        self.assertIn(int_field.id, profile.display_field_ids.ids,
                      "integer/float field should survive kpi layout switch")

    def test_onchange_layout_to_list_keeps_all_base_allowed_types(self):
        """Switching from kpi to list does not drop additional fields (onchange is not additive)."""
        profile = self._profile(layout="kpi")
        # Switching to list: no fields were set, so nothing to drop.
        profile.trmnl_layout = "list"
        profile._onchange_trmnl_layout()
        # Should not crash and display_field_ids remains empty.
        self.assertFalse(profile.display_field_ids)

    # ------------------------------------------------------------------
    # Preset respects layout-allowed types
    # ------------------------------------------------------------------

    def test_preset_fields_respect_layout_allowed_types(self):
        """_apply_model_preset silently drops fields not allowed by the preset's layout."""
        if "crm.lead" not in self.env:
            self.skipTest("crm.lead not available")
        ir_model = self._ir_model("crm.lead")
        if not ir_model:
            self.skipTest("ir.model record for crm.lead not found")

        profile = self.env["trmnl.profile"].sudo().create({
            "name": "CRM layout preset test",
            "device_id": self._device().id,
            "app_model_id": ir_model.id,
            "trmnl_layout": "list",
            "display_limit": 10,
            "filter_preset": "none",
        })
        # crm.lead preset layout is "list"; all preset fields should be list-compatible.
        from odoo.addons.trmnl.models.trmnl_profile import _LAYOUT_ALLOWED_TTYPES
        allowed = _LAYOUT_ALLOWED_TTYPES.get("list", set())
        for field_rec in profile.display_field_ids:
            self.assertIn(
                field_rec.ttype, allowed,
                f"Field {field_rec.name!r} (ttype={field_rec.ttype!r}) is not allowed for list layout",
            )

    # ------------------------------------------------------------------
    # Calendar: display_field_ids not populated by preset
    # ------------------------------------------------------------------

    def test_calendar_preset_does_not_set_display_field_ids(self):
        """calendar.event preset uses calendar layout — display_field_ids picker is irrelevant."""
        cal_model = self._ir_model("calendar.event")
        if not cal_model:
            self.skipTest("calendar.event not available")
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "Calendar layout picker test",
            "device_id": self._device().id,
            "app_model_id": cal_model.id,
            "trmnl_layout": "list",
            "display_limit": 10,
            "filter_preset": "none",
        })
        profile.app_model_id = cal_model
        profile._onchange_app_model_id()
        self.assertEqual(profile.trmnl_layout, "calendar",
                         "calendar.event preset must set layout to calendar")
        # Calendar layout has no allowed types in _LAYOUT_ALLOWED_TTYPES
        # (or the picker is hidden). Either way, rendering still works.
        profile._render_and_store_preview()
        self.assertTrue(profile.preview_image)
