"""Tests for available_view_types computation and trmnl_layout selection."""

from __future__ import annotations

from unittest.mock import patch

from odoo.exceptions import UserError, ValidationError
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
        """list is available for res.partner, which has a tree view."""
        profile = self._make_profile(self._partner_model)
        self.assertIn("list", profile._get_available_view_types())

    def test_graph_included_for_model_with_graph_view(self):
        """graph is available for res.partner when the model exposes a graph layout."""
        from odoo.addons.trmnl.tests.test_common import model_has_graph_view

        if not model_has_graph_view(self.env):
            self.skipTest("res.partner has no graph layout in this database")
        profile = self._make_profile(self._partner_model)
        self.assertIn("graph", profile._get_available_view_types())

    def test_graph_not_included_for_calendar_model(self):
        """calendar.event has no graph view — graph must not appear in available types."""
        if not self._calendar_model:
            self.skipTest("calendar.event not installed")
        profile = self._make_profile(self._calendar_model)
        self.assertNotIn("graph", profile._get_available_view_types())

    def test_kanban_not_included_for_calendar_model(self):
        """calendar.event must not offer kanban when no kanban view is installed."""
        if not self._calendar_model:
            self.skipTest("calendar.event not installed")
        has_kanban = self.env["ir.ui.view"].sudo().search_count(
            [("model", "=", "calendar.event"), ("type", "=", "kanban")]
        )
        if has_kanban:
            self.skipTest("calendar.event has a kanban view in this installation")
        profile = self._make_profile(self._calendar_model)
        self.assertNotIn("kanban", profile._get_available_view_types())

    def test_calendar_model_defaults_to_calendar_layout_on_onchange(self):
        """Selecting calendar.event should prefer the calendar view type."""
        if not self._calendar_model:
            self.skipTest("calendar.event not installed")
        profile = self.env["trmnl.profile"].sudo().new({
            "name": "cal default",
            "device_id": self._device.id,
            "trmnl_layout": "list",
            "display_limit": 1,
            "filter_preset": "none",
        })
        profile.app_model_id = self._calendar_model
        profile._onchange_app_model_id()
        self.assertEqual(profile.trmnl_layout, "calendar")

    def test_calendar_week_mode_renders_png(self):
        """Week calendar view mode is selectable and produces preview bytes."""
        if not self._calendar_model:
            self.skipTest("calendar.event not installed")
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "cal week",
            "device_id": self._device.id,
            "app_model_id": self._calendar_model.id,
            "trmnl_layout": "calendar",
            "calendar_view_mode": "week",
            "filter_preset": "none",
        })
        profile._render_and_store_preview()
        self.assertTrue(profile.preview_image)

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
        """trmnl_layout offers list/kanban/calendar/graph — line is a graph subtype."""
        profile_class = self.env["trmnl.profile"].sudo()
        options = profile_class._get_layout_selection_options()
        selection_keys = [k for k, _ in options]
        self.assertEqual(sorted(selection_keys), sorted(["list", "kanban", "calendar", "graph"]))
        self.assertNotIn("line", selection_keys)


@tagged("-at_install", "post_install")
class TestLayoutFieldFiltering(TransactionCase):
    """_onchange_trmnl_layout drops display fields outside _LAYOUT_ALLOWED_TTYPES."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._device = cls.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:77",
            "approval_state": "accepted",
        })
        cls._partner_model = cls.env["ir.model"].sudo().search(
            [("model", "=", "res.partner")], limit=1
        )

    def test_onchange_layout_removes_binary_display_field(self):
        name_field = self.env["ir.model.fields"].sudo().search(
            [("model", "=", "res.partner"), ("name", "=", "name")], limit=1
        )
        image_field = self.env["ir.model.fields"].sudo().search(
            [("model", "=", "res.partner"), ("name", "=", "image_1920")], limit=1
        )
        if not name_field or not image_field:
            self.skipTest("res.partner name/image_1920 fields not found")
        profile = self.env["trmnl.profile"].sudo().new({
            "name": "layout filter",
            "device_id": self._device.id,
            "app_model_id": self._partner_model.id,
            "trmnl_layout": "list",
            "display_field_ids": [(6, 0, [name_field.id, image_field.id])],
        })
        profile._onchange_trmnl_layout()
        kept_ids = set(profile.display_field_ids.ids)
        self.assertIn(name_field.id, kept_ids)
        self.assertNotIn(image_field.id, kept_ids)


@tagged("-at_install", "post_install")
class TestDynamicLayoutSelection(TransactionCase):
    """Dynamic trmnl_layout: options, constrains, onchange, and render-time guard."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._device = cls.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:33",
            "approval_state": "accepted",
        })
        cls._partner_model = cls.env["ir.model"].sudo().search(
            [("model", "=", "res.partner")], limit=1
        )
        cls._calendar_model = cls.env["ir.model"].sudo().search(
            [("model", "=", "calendar.event")], limit=1
        )

    def test_calendar_model_exposes_calendar_option(self):
        """_get_layout_selection_options includes calendar for calendar.event."""
        if not self._calendar_model:
            self.skipTest("calendar.event not installed")
        profile = self.env["trmnl.profile"].sudo().new({
            "name": "cal options test",
            "device_id": self._device.id,
            "app_model_id": self._calendar_model.id,
            "trmnl_layout": "list",
        })
        keys = [k for k, _ in profile._get_layout_selection_options()]
        self.assertIn("calendar", keys)

    def test_kanban_model_exposes_kanban_option(self):
        """_get_layout_selection_options includes kanban for a model with a kanban view."""
        kanban_view = self.env["ir.ui.view"].sudo().search(
            [("model", "=", "res.partner"), ("type", "=", "kanban")], limit=1
        )
        if not kanban_view:
            self.skipTest("res.partner has no kanban view in this installation")
        profile = self.env["trmnl.profile"].sudo().new({
            "name": "kanban options test",
            "device_id": self._device.id,
            "app_model_id": self._partner_model.id,
            "trmnl_layout": "list",
        })
        keys = [k for k, _ in profile._get_layout_selection_options()]
        self.assertIn("kanban", keys)

    def test_non_calendar_model_rejects_calendar_layout_on_save(self):
        """Saving calendar layout for a model without calendar views raises ValidationError."""
        has_calendar = self.env["ir.ui.view"].sudo().search_count(
            [("model", "=", "res.partner"), ("type", "=", "calendar")]
        )
        if has_calendar:
            self.skipTest("res.partner has a calendar view in this installation")
        with self.assertRaises(ValidationError):
            self.env["trmnl.profile"].sudo().create({
                "name": "bad layout",
                "device_id": self._device.id,
                "app_model_id": self._partner_model.id,
                "trmnl_layout": "calendar",
                "display_limit": 1,
                "filter_preset": "none",
            })

    def test_onchange_model_resets_calendar_layout_for_non_calendar_model(self):
        """_onchange_app_model_id resets layout when the model has no calendar view."""
        has_calendar = self.env["ir.ui.view"].sudo().search_count(
            [("model", "=", "res.partner"), ("type", "=", "calendar")]
        )
        if has_calendar:
            self.skipTest("res.partner has a calendar view in this installation")
        profile = self.env["trmnl.profile"].sudo().new({
            "name": "onchange test",
            "device_id": self._device.id,
            "trmnl_layout": "calendar",
            "display_limit": 1,
            "filter_preset": "none",
        })
        profile.app_model_id = self._partner_model
        profile._onchange_app_model_id()
        self.assertNotEqual(profile.trmnl_layout, "calendar")

    def test_render_raises_user_error_for_invalid_layout(self):
        """_render_and_store_preview raises UserError if layout is unavailable for the model."""
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "render guard test",
            "device_id": self._device.id,
            "app_model_id": self._partner_model.id,
            "trmnl_layout": "list",
            "display_limit": 1,
            "filter_preset": "none",
        })
        patch_path = "odoo.addons.trmnl.models.trmnl_profile.TrmnlProfile._get_available_view_types"
        with patch(patch_path, return_value=["kanban"]):
            with self.assertRaises(UserError):
                profile._render_and_store_preview()
