"""Tests for available_view_types computation and trmnl_layout selection."""

from __future__ import annotations

from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestAvailableViewTypes(TransactionCase):
    """_get_available_view_types always returns supported types present in ir.ui.view."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Profile = cls.env["trmnl.profile"]
        cls._device = cls.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:22",
            "approval_state": "accepted",
            "registration_source": "setup",
        })
        cls._partner_model = cls.env["ir.model"].sudo().search(
            [("model", "=", "res.partner")], limit=1
        )
        cls._calendar_model = cls.env["ir.model"].sudo().search(
            [("model", "=", "calendar.event")], limit=1
        )

    def _make_profile(self, model_id):
        return self.env["trmnl.profile"].sudo().create({
            "name": "view type test",
            "device_id": self._device.id,
            "app_model_id": model_id.id,
            "trmnl_layout": "list",
            "display_limit": 1,
            "filter_preset": "none",
        })

    def test_list_always_included(self):
        """list is always available regardless of model."""
        profile = self._make_profile(self._partner_model)
        self.assertIn("list", profile._get_available_view_types())

    def test_no_model_returns_all_supported(self):
        """Without a model set, all SUPPORTED_VIEW_TYPES are returned."""
        from odoo.addons.trmnl.models.trmnl_profile import SUPPORTED_VIEW_TYPES
        profile = self.env["trmnl.profile"].sudo().new({
            "name": "no model",
            "device_id": self._device.id,
            "trmnl_layout": "list",
            "display_limit": 1,
            "filter_preset": "none",
        })
        result = profile._get_available_view_types()
        for vtype in SUPPORTED_VIEW_TYPES:
            self.assertIn(vtype, result)

    def test_calendar_model_includes_calendar(self):
        """calendar.event model exposes calendar view type."""
        if not self._calendar_model:
            self.skipTest("calendar.event not installed")
        profile = self._make_profile(self._calendar_model)
        self.assertIn("calendar", profile._get_available_view_types())

    def test_result_only_contains_supported_types(self):
        """_get_available_view_types never returns unsupported types."""
        from odoo.addons.trmnl.models.trmnl_profile import SUPPORTED_VIEW_TYPES
        profile = self._make_profile(self._partner_model)
        for vtype in profile._get_available_view_types():
            self.assertIn(vtype, SUPPORTED_VIEW_TYPES)

    def test_compute_available_view_types_field(self):
        """available_view_types computed field is a comma-separated string."""
        profile = self._make_profile(self._partner_model)
        self.assertIsInstance(profile.available_view_types, str)
        self.assertIn("list", profile.available_view_types)

    def test_trmnl_layout_selection_values(self):
        """trmnl_layout only offers list, kanban, calendar."""
        field = self.env["trmnl.profile"]._fields["trmnl_layout"]
        selection_keys = [k for k, _ in field.selection]
        self.assertEqual(sorted(selection_keys), sorted(["list", "kanban", "calendar"]))
