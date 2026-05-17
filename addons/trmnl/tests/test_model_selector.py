"""Tests for app_model_id selector domain.

Verifies that the domain applied to app_model_id correctly hides technical,
abstract, and transient models while keeping business models visible.
"""
from __future__ import annotations

from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestModelSelectorDomain(TransactionCase):
    """_get_app_model_domain excludes technical / mixin / transient models."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        domain = cls.env["trmnl.profile"]._get_app_model_domain()
        all_visible = cls.env["ir.model"].sudo().search(domain)
        cls._visible_names = set(all_visible.mapped("model"))

    def _visible(self, model_name):
        return model_name in self._visible_names

    def _installed(self, model_name):
        return bool(
            self.env["ir.model"].sudo().search_count([("model", "=", model_name)])
        )

    # ── transient and abstract flags ─────────────────────────────────────────

    def test_no_transient_models_visible(self):
        """No TransientModel (wizard) appears in the selector."""
        transient = self.env["ir.model"].sudo().search(
            [("transient", "=", True), ("model", "in", list(self._visible_names))]
        )
        self.assertFalse(
            transient,
            msg=f"Transient models leaked into selector: {transient.mapped('model')}",
        )

    def test_no_abstract_models_visible(self):
        """No AbstractModel (mixin) appears in the selector."""
        abstract = self.env["ir.model"].sudo().search(
            [("abstract", "=", True), ("model", "in", list(self._visible_names))]
        )
        self.assertFalse(
            abstract,
            msg=f"Abstract models leaked into selector: {abstract.mapped('model')}",
        )

    # ── ir.* infrastructure ───────────────────────────────────────────────────

    def test_ir_model_hidden(self):
        """ir.model (Odoo infrastructure) is excluded."""
        self.assertFalse(self._visible("ir.model"))

    def test_ir_ui_view_hidden(self):
        """ir.ui.view (UI infrastructure) is excluded."""
        self.assertFalse(self._visible("ir.ui.view"))

    def test_ir_rule_hidden(self):
        """ir.rule (security infrastructure) is excluded."""
        self.assertFalse(self._visible("ir.rule"))

    def test_ir_model_fields_hidden(self):
        """ir.model.fields (schema infrastructure) is excluded."""
        self.assertFalse(self._visible("ir.model.fields"))

    # ── base.* utilities ──────────────────────────────────────────────────────

    def test_base_automation_hidden(self):
        """base.automation (internal trigger model) is excluded if installed."""
        if self._installed("base.automation"):
            self.assertFalse(self._visible("base.automation"))

    # ── bus.* framework ───────────────────────────────────────────────────────

    def test_bus_bus_hidden(self):
        """bus.bus (web-push bus) is excluded."""
        if self._installed("bus.bus"):
            self.assertFalse(self._visible("bus.bus"))

    # ── auth.* authentication ─────────────────────────────────────────────────

    def test_auth_totp_device_hidden(self):
        """auth.totp.device (2FA infrastructure) is excluded if installed."""
        if self._installed("auth.totp.device"):
            self.assertFalse(self._visible("auth.totp.device"))

    # ── resource.* scheduling infrastructure ─────────────────────────────────

    def test_resource_calendar_hidden(self):
        """resource.calendar (scheduling infrastructure) is excluded if installed."""
        if self._installed("resource.calendar"):
            self.assertFalse(self._visible("resource.calendar"))

    # ── abstract mixin models ─────────────────────────────────────────────────

    def test_mail_thread_hidden(self):
        """mail.thread (abstract messaging mixin) is excluded if installed."""
        if self._installed("mail.thread"):
            self.assertFalse(self._visible("mail.thread"))

    # ── business models must remain visible ───────────────────────────────────

    def test_res_partner_visible(self):
        """res.partner (Contacts) is always visible."""
        self.assertTrue(
            self._visible("res.partner"),
            msg="res.partner must be selectable but is not in the domain result",
        )

    def test_res_users_visible(self):
        """res.users (Users) is always visible."""
        self.assertTrue(self._visible("res.users"))

    def test_calendar_event_visible(self):
        """calendar.event (Calendar) is visible if the calendar module is installed."""
        if self._installed("calendar.event"):
            self.assertTrue(
                self._visible("calendar.event"),
                msg="calendar.event must be selectable but is excluded by the domain",
            )

    def test_project_task_visible(self):
        """project.task (Tasks) is visible if the project module is installed."""
        if self._installed("project.task"):
            self.assertTrue(self._visible("project.task"))

    def test_crm_lead_visible(self):
        """crm.lead (CRM Leads) is visible if CRM is installed."""
        if self._installed("crm.lead"):
            self.assertTrue(self._visible("crm.lead"))

    # ── domain structure ──────────────────────────────────────────────────────

    def test_domain_is_list(self):
        """_get_app_model_domain returns a plain list (not a generator or tuple)."""
        domain = self.env["trmnl.profile"]._get_app_model_domain()
        self.assertIsInstance(domain, list)

    def test_domain_excludes_transient_condition(self):
        """Domain contains an explicit transient=False condition."""
        domain = self.env["trmnl.profile"]._get_app_model_domain()
        self.assertIn(("transient", "=", False), domain)

    def test_domain_excludes_abstract_condition(self):
        """Domain contains an explicit abstract=False condition."""
        domain = self.env["trmnl.profile"]._get_app_model_domain()
        self.assertIn(("abstract", "=", False), domain)

    def test_domain_has_ir_prefix_exclusion(self):
        """Domain contains a prefix exclusion for 'ir.' models."""
        domain = self.env["trmnl.profile"]._get_app_model_domain()
        exclusions = [cond for cond in domain if isinstance(cond, (list, tuple)) and len(cond) == 3 and cond[1] == "not ilike"]
        prefixes_excluded = [cond[2] for cond in exclusions]
        self.assertIn("ir.", prefixes_excluded)
