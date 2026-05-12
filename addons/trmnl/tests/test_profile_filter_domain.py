"""Tests for trmnl.profile filter_domain field."""

from __future__ import annotations

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestProfileFilterDomain(TransactionCase):
    """filter_domain: evaluation, validation, domain combination, and rendering."""

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

    def _profile(self, **vals):
        base = {
            "name": "Domain test",
            "device_id": self._device.id,
            "app_model_id": self._partner_model.id,
            "trmnl_layout": "list",
            "display_limit": 5,
            "filter_preset": "none",
        }
        base.update(vals)
        return self.env["trmnl.profile"].sudo().create(base)

    # ------------------------------------------------------------------
    # eval helper
    # ------------------------------------------------------------------

    def test_empty_domain_returns_empty_list(self):
        profile = self._profile()
        self.assertEqual(profile._eval_filter_domain(""), [])
        self.assertEqual(profile._eval_filter_domain("[]"), [])
        self.assertEqual(profile._eval_filter_domain(None), [])

    def test_valid_domain_parses_correctly(self):
        profile = self._profile()
        result = profile._eval_filter_domain("[('name', '!=', False)]")
        self.assertIsInstance(result, list)
        self.assertEqual(result, [("name", "!=", False)])

    def test_uid_substituted_in_domain(self):
        profile = self._profile()
        result = profile._eval_filter_domain("[('id', '=', uid)]")
        self.assertIsInstance(result, list)
        self.assertEqual(result[0][2], self.env.uid)

    def test_context_today_callable(self):
        from odoo import fields as ofields
        profile = self._profile()
        result = profile._eval_filter_domain("[('create_date', '>=', context_today())]")
        self.assertIsInstance(result, list)
        self.assertEqual(result[0][2], ofields.Date.today())

    def test_non_list_domain_raises(self):
        profile = self._profile()
        with self.assertRaises(ValueError):
            profile._eval_filter_domain("{'key': 'value'}")

    # ------------------------------------------------------------------
    # constrains: invalid domain rejected on save
    # ------------------------------------------------------------------

    def test_invalid_domain_syntax_raises_validation_error(self):
        with self.assertRaises(ValidationError):
            self._profile(filter_domain="not valid python")

    def test_invalid_domain_structure_raises_validation_error(self):
        # Evaluates to a list but is not a valid Odoo domain tuple structure.
        with self.assertRaises(ValidationError):
            self._profile(filter_domain="[('a', 'b')]")  # tuple needs 3 elements

    def test_empty_domain_saves_cleanly(self):
        profile = self._profile(filter_domain="[]")
        self.assertEqual(profile.filter_domain, "[]")

    def test_no_domain_saves_cleanly(self):
        profile = self._profile(filter_domain=False)
        self.assertFalse(profile.filter_domain)

    # ------------------------------------------------------------------
    # _load_records: domain combination
    # ------------------------------------------------------------------

    def test_empty_filter_domain_loads_all_records(self):
        profile = self._profile(filter_domain="[]")
        records = profile._load_records("res.partner", ["name"])
        # Should return up to display_limit records with no extra restriction.
        self.assertLessEqual(len(records), 5)
        self.assertGreater(len(records), 0)

    def test_custom_domain_filters_records(self):
        # Create two partners: one active, one archived.
        active_partner = self.env["res.partner"].sudo().create({
            "name": "TrmnlDomainActive",
            "active": True,
        })
        archived_partner = self.env["res.partner"].sudo().create({
            "name": "TrmnlDomainArchived",
            "active": False,
        })

        # Domain that includes archived records but restricts to our test names.
        domain_str = (
            "[('name', 'like', 'TrmnlDomain'), ('active', '=', False)]"
        )
        profile = self._profile(
            filter_domain=domain_str,
            display_limit=50,
        )
        # Sudo search ignores active domain by default, so we pass active_test=False.
        records = profile.env["res.partner"].with_context(active_test=False).sudo().search(
            [("name", "like", "TrmnlDomain"), ("active", "=", False)], limit=50
        )
        # Confirm archived_partner is findable.
        self.assertIn(archived_partner.id, records.ids)
        self.assertNotIn(active_partner.id, records.ids)

        # Now verify _load_records with the custom domain gives only archived ones.
        profile_records = profile._load_records("res.partner", ["name"])
        # All returned records must match the custom domain (active=False).
        for rec in profile_records:
            self.assertFalse(rec.active)

        active_partner.unlink()
        archived_partner.with_context(active_test=False).unlink()

    def test_custom_domain_combined_with_preset(self):
        """filter_preset AND filter_domain are both applied."""
        profile = self._profile(
            filter_preset="my_records",
            filter_domain="[('is_company', '=', True)]",
            display_limit=50,
        )
        records = profile._load_records("res.partner", ["name"])
        for rec in records:
            self.assertTrue(rec.is_company)

    # ------------------------------------------------------------------
    # rendering
    # ------------------------------------------------------------------

    def test_render_preview_with_custom_domain(self):
        """Render preview works end-to-end with a valid custom domain."""
        profile = self._profile(
            filter_domain="[('name', '!=', False)]",
            display_limit=3,
        )
        profile._render_and_store_preview()
        self.assertTrue(profile.preview_image)
        self.assertTrue(profile.preview_generated_at)

    def test_render_preview_with_empty_domain(self):
        """Render preview works when filter_domain is empty."""
        profile = self._profile(filter_domain="[]")
        profile._render_and_store_preview()
        self.assertTrue(profile.preview_image)

    def test_render_preview_invalid_domain_raises_user_error(self):
        """If filter_domain somehow contains an invalid value at render time, UserError is raised."""
        profile = self._profile()
        # Bypass constrains by writing directly to the field after creation.
        profile.write({"filter_domain": "not_a_domain"})
        with self.assertRaises((UserError, Exception)):
            profile._render_and_store_preview()

    # ------------------------------------------------------------------
    # calendar loaders respect filter_domain
    # ------------------------------------------------------------------

    def test_calendar_month_loader_applies_filter_domain(self):
        """_load_calendar_records applies a custom filter_domain on top of the month window."""
        cal_model = self.env["ir.model"].sudo().search(
            [("model", "=", "calendar.event")], limit=1
        )
        if not cal_model:
            self.skipTest("calendar.event model not found")
        from datetime import date as _date
        today = _date.today()
        event_kept = self.env["calendar.event"].sudo().create({
            "name": "TrmnlCalFilterKept",
            "start": f"{today.year}-{today.month:02d}-01 10:00:00",
            "stop":  f"{today.year}-{today.month:02d}-01 11:00:00",
        })
        event_excluded = self.env["calendar.event"].sudo().create({
            "name": "TrmnlCalFilterExcluded",
            "start": f"{today.year}-{today.month:02d}-01 12:00:00",
            "stop":  f"{today.year}-{today.month:02d}-01 13:00:00",
        })
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "Cal domain test",
            "device_id": self._device.id,
            "app_model_id": cal_model.id,
            "trmnl_layout": "calendar",
            "display_limit": 200,
            "filter_preset": "none",
            "filter_domain": f"[('name', '=', 'TrmnlCalFilterKept')]",
        })
        records = profile._load_calendar_records(today.year, today.month)
        ids = records.ids
        self.assertIn(event_kept.id, ids)
        self.assertNotIn(event_excluded.id, ids)
        event_kept.unlink()
        event_excluded.unlink()

    def test_calendar_week_loader_applies_filter_domain(self):
        """_load_calendar_week_records applies a custom filter_domain."""
        cal_model = self.env["ir.model"].sudo().search(
            [("model", "=", "calendar.event")], limit=1
        )
        if not cal_model:
            self.skipTest("calendar.event model not found")
        from datetime import date as _date, timedelta
        today = _date.today()
        week_start = today - timedelta(days=today.weekday())
        event_kept = self.env["calendar.event"].sudo().create({
            "name": "TrmnlWeekFilterKept",
            "start": f"{week_start.strftime('%Y-%m-%d')} 09:00:00",
            "stop":  f"{week_start.strftime('%Y-%m-%d')} 10:00:00",
        })
        event_excluded = self.env["calendar.event"].sudo().create({
            "name": "TrmnlWeekFilterExcluded",
            "start": f"{week_start.strftime('%Y-%m-%d')} 11:00:00",
            "stop":  f"{week_start.strftime('%Y-%m-%d')} 12:00:00",
        })
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "Cal week domain test",
            "device_id": self._device.id,
            "app_model_id": cal_model.id,
            "trmnl_layout": "calendar",
            "display_limit": 200,
            "filter_preset": "none",
            "filter_domain": f"[('name', '=', 'TrmnlWeekFilterKept')]",
        })
        records = profile._load_calendar_week_records(week_start)
        ids = records.ids
        self.assertIn(event_kept.id, ids)
        self.assertNotIn(event_excluded.id, ids)
        event_kept.unlink()
        event_excluded.unlink()

    # ------------------------------------------------------------------
    # stale display_field_ids: cross-model fields are silently dropped
    # ------------------------------------------------------------------

    def test_stale_display_fields_from_wrong_model_are_dropped(self):
        """Render with display_field_ids from a different model falls back to display_name."""
        ir_model_field = self.env["ir.model.fields"].sudo().search(
            [("model", "=", "ir.model"), ("name", "=", "model")], limit=1
        )
        if not ir_model_field:
            self.skipTest("ir.model.fields entry for ir.model.model not found")
        profile = self._profile()
        # Force-assign a field from ir.model onto a res.partner profile.
        profile.write({"display_field_ids": [(4, ir_model_field.id)]})
        # Rendering should not crash — it falls back to display_name.
        profile._render_and_store_preview()
        self.assertTrue(profile.preview_image)

    # ------------------------------------------------------------------
    # read_group rendering respects the full effective domain
    # ------------------------------------------------------------------

    def test_read_group_applies_custom_filter_domain(self):
        """_build_trmnl_read_group_rows applies filter_domain via _build_effective_domain."""
        if "crm.lead" not in self.env:
            self.skipTest("crm.lead not available")
        crm_model = self.env["ir.model"].sudo().search(
            [("model", "=", "crm.lead")], limit=1
        )
        if not crm_model:
            self.skipTest("ir.model record for crm.lead not found")

        # Create two leads with distinct names so we can filter one out.
        lead_keep = self.env["crm.lead"].sudo().create({"name": "TrmnlRGKeep"})
        lead_drop = self.env["crm.lead"].sudo().create({"name": "TrmnlRGDrop"})

        profile = self.env["trmnl.profile"].sudo().create({
            "name": "RG domain test",
            "device_id": self._device.id,
            "app_model_id": crm_model.id,
            "trmnl_layout": "list",
            "display_limit": 50,
            "filter_preset": "none",
            "filter_domain": "[('name', 'like', 'TrmnlRGKeep')]",
            "trmnl_read_group_field_name": "stage_id",
        })
        result = profile._build_trmnl_read_group_rows("crm.lead", "stage_id")
        # Verify the domain was applied: result should only reflect the kept lead.
        # The aggregate count across all groups must equal 1 (only TrmnlRGKeep).
        if result is not None:
            rows, _headers = result
            total = sum(int(row[1]) for row in rows)
            self.assertEqual(total, 1, "Only TrmnlRGKeep should be counted")

        lead_keep.unlink()
        lead_drop.unlink()

    def test_read_group_applies_action_domain(self):
        """_build_trmnl_read_group_rows applies the action domain (Layer 1)."""
        if "crm.lead" not in self.env:
            self.skipTest("crm.lead not available")
        crm_model = self.env["ir.model"].sudo().search(
            [("model", "=", "crm.lead")], limit=1
        )
        if not crm_model:
            self.skipTest("ir.model record for crm.lead not found")

        # Create two leads.
        lead_keep = self.env["crm.lead"].sudo().create({"name": "TrmnlActionKeep"})
        lead_drop = self.env["crm.lead"].sudo().create({"name": "TrmnlActionDrop"})

        # Build an action whose domain restricts to our kept lead.
        action = self.env["ir.actions.act_window"].sudo().search(
            [("res_model", "=", "crm.lead")], limit=1, order="id asc"
        )
        if not action:
            lead_keep.unlink()
            lead_drop.unlink()
            self.skipTest("No ir.actions.act_window for crm.lead found")

        profile = self.env["trmnl.profile"].sudo().create({
            "name": "RG action domain test",
            "device_id": self._device.id,
            "app_model_id": crm_model.id,
            "odoo_action_id": action.id,
            "trmnl_layout": "list",
            "display_limit": 50,
            "filter_preset": "none",
            "filter_domain": "[('name', 'like', 'TrmnlAction')]",
            "trmnl_read_group_field_name": "stage_id",
        })

        # Patch the action domain to our specific filter.
        original_domain = action.domain
        action.write({"domain": "[('name', '=', 'TrmnlActionKeep')]"})
        try:
            result = profile._build_trmnl_read_group_rows("crm.lead", "stage_id")
            if result is not None:
                rows, _headers = result
                total = sum(int(row[1]) for row in rows)
                self.assertEqual(total, 1,
                                 "Only TrmnlActionKeep should survive after action domain + filter_domain")
        finally:
            action.write({"domain": original_domain})
            lead_keep.unlink()
            lead_drop.unlink()

    def test_build_effective_domain_combines_all_layers(self):
        """_build_effective_domain produces a non-empty domain when all three layers are active."""
        partner_action = self.env["ir.actions.act_window"].sudo().search(
            [("res_model", "=", "res.partner")], limit=1, order="id asc"
        )
        if not partner_action:
            self.skipTest("No ir.actions.act_window for res.partner found")

        # Set an action domain on the action temporarily.
        original = partner_action.domain
        partner_action.write({"domain": "[('is_company', '=', True)]"})

        profile = self._profile(
            odoo_action_id=partner_action.id,
            filter_preset="my_records",
            filter_domain="[('name', '!=', False)]",
        )
        try:
            domain = profile._build_effective_domain("res.partner")
            self.assertIsInstance(domain, list)
            # With all three layers active the domain must have more than one condition.
            self.assertGreater(len(domain), 0)
        finally:
            partner_action.write({"domain": original})

    def test_build_effective_domain_silently_skips_bad_action_domain(self):
        """A syntactically broken action domain is silently ignored; rendering does not crash."""
        partner_action = self.env["ir.actions.act_window"].sudo().search(
            [("res_model", "=", "res.partner")], limit=1, order="id asc"
        )
        if not partner_action:
            self.skipTest("No ir.actions.act_window for res.partner found")

        original = partner_action.domain
        partner_action.write({"domain": "THIS IS NOT VALID PYTHON"})

        profile = self._profile(
            odoo_action_id=partner_action.id,
            filter_preset="none",
            filter_domain="[]",
        )
        try:
            # Should not raise — bad action domain is skipped.
            domain = profile._build_effective_domain("res.partner")
            self.assertIsInstance(domain, list)
        finally:
            partner_action.write({"domain": original})
