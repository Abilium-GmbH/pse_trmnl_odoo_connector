"""Tests for line chart (graph_type='line'): validation, data loading, and renderer.

Since the 'line' chart is now a subtype of the 'graph' layout (selected via
graph_type='line'), all profiles use trmnl_layout='graph'.
"""

from __future__ import annotations

import io
from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


# ---------------------------------------------------------------------------
# Shared setup helpers
# ---------------------------------------------------------------------------

def _make_device(env, mac):
    return env["trmnl.device"].sudo().create({
        "mac_address": mac,
        "approval_state": "accepted",
        "registration_source": "setup",
    })


def _partner_model(env):
    return env["ir.model"].sudo().search([("model", "=", "res.partner")], limit=1)


def _field(env, model, name):
    return env["ir.model.fields"].sudo().search(
        [("model", "=", model), ("name", "=", name)], limit=1
    )


# ---------------------------------------------------------------------------
# graph_type selection — line is a graph subtype, not a View Type
# ---------------------------------------------------------------------------

@tagged("-at_install", "post_install")
class TestLineAsGraphSubtype(TransactionCase):
    """line is a graph_type value, not a trmnl_layout value."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._device = _make_device(cls.env, "AA:BB:CC:DD:EF:01")
        cls._partner_model = _partner_model(cls.env)
        cls._date_field = _field(cls.env, "res.partner", "create_date")

    def _profile(self, **vals):
        base = {
            "name": "Line subtype test",
            "device_id": self._device.id,
            "app_model_id": self._partner_model.id,
            "trmnl_layout": "graph",
            "graph_type": "line",
            "filter_preset": "none",
            "line_date_field_id": self._date_field.id,
        }
        base.update(vals)
        return self.env["trmnl.profile"].sudo().create(base)

    def test_line_is_not_a_layout_value(self):
        """'line' must not appear as a trmnl_layout selection option."""
        profile = self._profile()
        options = profile._get_layout_selection_options()
        keys = [k for k, _ in options]
        self.assertNotIn("line", keys)

    def test_graph_is_available_for_any_model(self):
        """graph layout (which covers line chart) is always available."""
        profile = self._profile()
        self.assertIn("graph", profile._get_available_view_types())

    def test_line_profile_has_graph_layout(self):
        """A line chart profile uses trmnl_layout='graph', graph_type='line'."""
        profile = self._profile()
        self.assertEqual(profile.trmnl_layout, "graph")
        self.assertEqual(profile.graph_type, "line")

    def test_model_has_date_field_still_works(self):
        """_model_has_date_field returns True for res.partner (has create_date)."""
        profile = self._profile()
        self.assertTrue(profile._model_has_date_field("res.partner"))

    def test_model_has_date_field_false_for_nonexistent(self):
        profile = self._profile()
        self.assertFalse(profile._model_has_date_field("__nonexistent__.model"))


# ---------------------------------------------------------------------------
# Constraint validation
# ---------------------------------------------------------------------------

@tagged("-at_install", "post_install")
class TestLineValidation(TransactionCase):
    """_check_graph_config constraint for graph_type='line'."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._device = _make_device(cls.env, "AA:BB:CC:DD:EF:02")
        cls._partner_model = _partner_model(cls.env)
        cls._date_field = _field(cls.env, "res.partner", "create_date")
        cls._char_field = _field(cls.env, "res.partner", "name")

    def test_line_without_date_field_raises(self):
        """graph/line without line_date_field_id must raise ValidationError."""
        with self.assertRaises(ValidationError):
            self.env["trmnl.profile"].sudo().create({
                "name": "Missing date field",
                "device_id": self._device.id,
                "app_model_id": self._partner_model.id,
                "trmnl_layout": "graph",
                "graph_type": "line",
                "filter_preset": "none",
            })

    def test_line_with_non_date_field_raises(self):
        """line_date_field_id pointing to a char field must raise ValidationError."""
        if not self._char_field:
            self.skipTest("res.partner.name not found")
        with self.assertRaises(ValidationError):
            self.env["trmnl.profile"].sudo().create({
                "name": "Wrong field type",
                "device_id": self._device.id,
                "app_model_id": self._partner_model.id,
                "trmnl_layout": "graph",
                "graph_type": "line",
                "filter_preset": "none",
                "line_date_field_id": self._char_field.id,
            })

    def test_line_with_valid_date_field_saves(self):
        """Line profile with a valid date/datetime field saves without error."""
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "Valid line",
            "device_id": self._device.id,
            "app_model_id": self._partner_model.id,
            "trmnl_layout": "graph",
            "graph_type": "line",
            "filter_preset": "none",
            "line_date_field_id": self._date_field.id,
        })
        self.assertEqual(profile.trmnl_layout, "graph")
        self.assertEqual(profile.graph_type, "line")
        self.assertTrue(profile.line_date_field_id)

    def test_bar_without_groupby_still_raises(self):
        """graph/bar without graph_groupby_field_id still raises ValidationError."""
        with self.assertRaises(ValidationError):
            self.env["trmnl.profile"].sudo().create({
                "name": "Bar no groupby",
                "device_id": self._device.id,
                "app_model_id": self._partner_model.id,
                "trmnl_layout": "graph",
                "graph_type": "bar",
                "filter_preset": "none",
            })


# ---------------------------------------------------------------------------
# Data loading — static helpers
# ---------------------------------------------------------------------------

@tagged("-at_install", "post_install")
class TestLineDateHelpers(TransactionCase):
    """Static methods: bucket generation, label formatting, domain extraction."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from odoo.addons.trmnl.models.trmnl_profile_render import TrmnlProfileRenderMixin
        cls._mixin = TrmnlProfileRenderMixin

    def test_generate_buckets_month(self):
        buckets = list(self._mixin._generate_line_date_buckets(
            date(2024, 1, 1), date(2024, 3, 1), "month"
        ))
        self.assertEqual(buckets, [date(2024, 1, 1), date(2024, 2, 1), date(2024, 3, 1)])

    def test_generate_buckets_week(self):
        buckets = list(self._mixin._generate_line_date_buckets(
            date(2024, 1, 1), date(2024, 1, 15), "week"
        ))
        self.assertEqual(buckets, [date(2024, 1, 1), date(2024, 1, 8), date(2024, 1, 15)])

    def test_generate_buckets_day(self):
        buckets = list(self._mixin._generate_line_date_buckets(
            date(2024, 1, 1), date(2024, 1, 3), "day"
        ))
        self.assertEqual(buckets, [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)])

    def test_generate_buckets_single_date(self):
        buckets = list(self._mixin._generate_line_date_buckets(
            date(2024, 6, 1), date(2024, 6, 1), "month"
        ))
        self.assertEqual(buckets, [date(2024, 6, 1)])

    def test_generate_buckets_year_boundary(self):
        """Month bucket generation crosses December → January correctly."""
        buckets = list(self._mixin._generate_line_date_buckets(
            date(2023, 12, 1), date(2024, 2, 1), "month"
        ))
        self.assertEqual(buckets, [date(2023, 12, 1), date(2024, 1, 1), date(2024, 2, 1)])

    def test_format_label_month_single_year(self):
        label = self._mixin._format_line_date_label(date(2024, 5, 1), "month", multi_year=False)
        self.assertEqual(label, "May")

    def test_format_label_month_multi_year(self):
        label = self._mixin._format_line_date_label(date(2024, 5, 1), "month", multi_year=True)
        self.assertIn("24", label)

    def test_format_label_week_single_year(self):
        label = self._mixin._format_line_date_label(date(2024, 1, 1), "week", multi_year=False)
        self.assertRegex(label, r"^W\d{2}$")

    def test_format_label_week_multi_year(self):
        label = self._mixin._format_line_date_label(date(2024, 1, 1), "week", multi_year=True)
        self.assertRegex(label, r"^W\d{2}'\d{2}$")

    def test_format_label_day_single_year(self):
        label = self._mixin._format_line_date_label(date(2024, 5, 15), "day", multi_year=False)
        self.assertIn("15", label)
        self.assertIn("May", label)

    def test_extract_group_start_date_datetime_str(self):
        domain = [("create_date", ">=", "2024-05-01 00:00:00"), ("create_date", "<", "2024-06-01 00:00:00")]
        result = self._mixin._extract_group_start_date(domain, "create_date")
        self.assertEqual(result, date(2024, 5, 1))

    def test_extract_group_start_date_date_obj(self):
        domain = [("date", ">=", date(2024, 3, 1))]
        result = self._mixin._extract_group_start_date(domain, "date")
        self.assertEqual(result, date(2024, 3, 1))

    def test_extract_group_start_date_no_match(self):
        domain = [("other_field", ">=", "2024-01-01 00:00:00")]
        result = self._mixin._extract_group_start_date(domain, "create_date")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Data loading — ORM integration
# ---------------------------------------------------------------------------

@tagged("-at_install", "post_install")
class TestLineDataLoading(TransactionCase):
    """_load_line_data: aggregation, gap filling, capping, filtering."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._device = _make_device(cls.env, "AA:BB:CC:DD:EF:03")
        cls._partner_model = _partner_model(cls.env)
        cls._date_field = _field(cls.env, "res.partner", "create_date")

    def _profile(self, **vals):
        base = {
            "name": "Line data test",
            "device_id": self._device.id,
            "app_model_id": self._partner_model.id,
            "trmnl_layout": "graph",
            "graph_type": "line",
            "filter_preset": "none",
            "line_date_field_id": self._date_field.id,
            "line_date_groupby": "month",
            "line_max_points": 12,
        }
        base.update(vals)
        return self.env["trmnl.profile"].sudo().create(base)

    def test_returns_list_of_dicts(self):
        profile = self._profile()
        points = profile._load_line_data("res.partner")
        self.assertIsInstance(points, list)
        for p in points:
            self.assertIn("label", p)
            self.assertIn("value", p)
            self.assertIsInstance(p["label"], str)
            self.assertIsInstance(p["value"], float)

    def test_count_mode_values_non_negative(self):
        profile = self._profile()
        points = profile._load_line_data("res.partner")
        for p in points:
            self.assertGreaterEqual(p["value"], 0.0)

    def test_empty_domain_returns_empty_list(self):
        profile = self._profile(filter_domain="[('id', '<', 0)]")
        points = profile._load_line_data("res.partner")
        self.assertEqual(points, [])

    def test_max_points_caps_output(self):
        profile = self._profile(line_max_points=1)
        points = profile._load_line_data("res.partner")
        self.assertLessEqual(len(points), 1)

    def test_max_points_capped_at_52(self):
        profile = self._profile(line_max_points=999)
        points = profile._load_line_data("res.partner")
        self.assertLessEqual(len(points), 52)

    def test_domain_filter_applied(self):
        profile_all = self._profile()
        profile_none = self._profile(filter_domain="[('id', '<', 0)]")
        all_sum = sum(p["value"] for p in profile_all._load_line_data("res.partner"))
        none_sum = sum(p["value"] for p in profile_none._load_line_data("res.partner"))
        self.assertGreaterEqual(all_sum, none_sum)

    def test_groupby_month_label_format(self):
        profile = self._profile(line_date_groupby="month")
        points = profile._load_line_data("res.partner")
        if not points:
            self.skipTest("No res.partner records with create_date")
        for p in points:
            self.assertTrue(p["label"])

    def test_groupby_week(self):
        profile = self._profile(line_date_groupby="week", line_max_points=52)
        points = profile._load_line_data("res.partner")
        self.assertIsInstance(points, list)

    def test_groupby_day(self):
        profile = self._profile(line_date_groupby="day", line_max_points=30)
        points = profile._load_line_data("res.partner")
        self.assertIsInstance(points, list)

    def test_sum_mode_with_numeric_measure(self):
        measure_field = self.env["ir.model.fields"].sudo().search(
            [("model", "=", "res.partner"), ("ttype", "in", ["integer", "float", "monetary"]), ("store", "=", True)],
            limit=1,
        )
        if not measure_field:
            self.skipTest("No stored numeric field found on res.partner")
        profile = self._profile(line_measure_field_id=measure_field.id)
        points = profile._load_line_data("res.partner")
        for p in points:
            self.assertIsInstance(p["value"], float)

    def test_measure_label_count(self):
        profile = self._profile()
        self.assertEqual(profile._line_measure_label(), "Count")

    def test_measure_label_field_description(self):
        measure_field = self.env["ir.model.fields"].sudo().search(
            [("model", "=", "res.partner"), ("ttype", "in", ["integer", "float", "monetary"]), ("store", "=", True)],
            limit=1,
        )
        if not measure_field:
            self.skipTest("No stored numeric field found on res.partner")
        profile = self._profile(line_measure_field_id=measure_field.id)
        label = profile._line_measure_label()
        self.assertEqual(label, measure_field.field_description or measure_field.name)

    def test_gap_filling_via_bucket_generation(self):
        from odoo.addons.trmnl.models.trmnl_profile_render import TrmnlProfileRenderMixin
        buckets = list(TrmnlProfileRenderMixin._generate_line_date_buckets(
            date(2024, 1, 1), date(2024, 4, 1), "month"
        ))
        self.assertEqual(len(buckets), 4)
        self.assertEqual(buckets[0], date(2024, 1, 1))
        self.assertEqual(buckets[-1], date(2024, 4, 1))


# ---------------------------------------------------------------------------
# Full pipeline rendering
# ---------------------------------------------------------------------------

@tagged("-at_install", "post_install")
class TestLineRendering(TransactionCase):
    """End-to-end line chart rendering via _render_and_store_preview."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._device = _make_device(cls.env, "AA:BB:CC:DD:EF:04")
        cls._partner_model = _partner_model(cls.env)
        cls._date_field = _field(cls.env, "res.partner", "create_date")

    def _profile(self, **vals):
        base = {
            "name": "Line render test",
            "device_id": self._device.id,
            "app_model_id": self._partner_model.id,
            "trmnl_layout": "graph",
            "graph_type": "line",
            "filter_preset": "none",
            "line_date_field_id": self._date_field.id,
            "line_date_groupby": "month",
            "line_max_points": 12,
        }
        base.update(vals)
        return self.env["trmnl.profile"].sudo().create(base)

    def test_render_and_store_produces_image(self):
        profile = self._profile()
        profile._render_and_store_preview()
        self.assertTrue(profile.preview_image)
        self.assertTrue(profile.preview_generated_at)

    def test_render_with_custom_title(self):
        profile = self._profile(graph_title="Revenue Growth")
        profile._render_and_store_preview()
        self.assertTrue(profile.preview_image)

    def test_render_with_empty_result(self):
        """Empty domain still produces a valid 'No data' PNG."""
        profile = self._profile(filter_domain="[('id', '<', 0)]")
        profile._render_and_store_preview()
        self.assertTrue(profile.preview_image)

    def test_render_with_domain_filter(self):
        profile = self._profile(filter_domain="[('name', '!=', False)]")
        profile._render_and_store_preview()
        self.assertTrue(profile.preview_image)

    def test_action_render_preview_returns_action(self):
        """action_render_preview notifies then re-opens the profile form."""
        profile = self._profile()
        result = profile.action_render_preview()
        self.assertEqual(result.get("type"), "ir.actions.client")
        self.assertEqual(result.get("tag"), "display_notification")
        next_action = result["params"]["next"]
        self.assertEqual(next_action.get("type"), "ir.actions.act_window")
        self.assertEqual(next_action.get("res_model"), "trmnl.profile")
        self.assertEqual(next_action.get("res_id"), profile.id)

    def test_action_render_preview_sets_preview_image_on_first_call(self):
        """A single call to action_render_preview is enough to populate preview_image."""
        profile = self._profile()
        profile.write({"preview_image": False, "preview_generated_at": False})
        profile.action_render_preview()
        self.assertTrue(profile.preview_image, "preview_image must be set after a single call")


# ---------------------------------------------------------------------------
# Pure-Python renderer unit tests
# ---------------------------------------------------------------------------

@tagged("-at_install", "post_install")
class TestLineRendererUnit(TransactionCase):
    """Unit tests for render_line_chart (pure Python, no ORM)."""

    def test_renderer_returns_png_bytes(self):
        from odoo.addons.trmnl.trmnl_chart_preview import render_line_chart
        points = [{"label": "Jan", "value": 100.0}, {"label": "Feb", "value": 200.0}]
        result = render_line_chart(points, "Revenue", "Count")
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_renderer_empty_points(self):
        from odoo.addons.trmnl.trmnl_chart_preview import render_line_chart
        result = render_line_chart([], "Empty", "Count")
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_renderer_single_point(self):
        from odoo.addons.trmnl.trmnl_chart_preview import render_line_chart
        result = render_line_chart([{"label": "Jan", "value": 42.0}], "Single", "Count")
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_renderer_all_zero_values(self):
        from odoo.addons.trmnl.trmnl_chart_preview import render_line_chart
        points = [{"label": "A", "value": 0.0}, {"label": "B", "value": 0.0}]
        result = render_line_chart(points, "Zeros", "Count")
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_renderer_custom_dimensions(self):
        from PIL import Image
        from odoo.addons.trmnl.trmnl_chart_preview import render_line_chart
        points = [{"label": "X", "value": 5.0}, {"label": "Y", "value": 10.0}]
        png = render_line_chart(points, "Dim", "Count", width=400, content_height=300)
        img = Image.open(io.BytesIO(png))
        self.assertEqual(img.size, (400, 300))

    def test_renderer_long_labels(self):
        from odoo.addons.trmnl.trmnl_chart_preview import render_line_chart
        points = [{"label": "A" * 100, "value": 5.0}, {"label": "B" * 100, "value": 10.0}]
        result = render_line_chart(points, "Long", "Count")
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_renderer_many_points(self):
        from odoo.addons.trmnl.trmnl_chart_preview import render_line_chart
        points = [{"label": f"W{i:02d}", "value": float(i)} for i in range(52)]
        result = render_line_chart(points, "Many", "Count")
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_renderer_large_values(self):
        from odoo.addons.trmnl.trmnl_chart_preview import render_line_chart
        points = [
            {"label": "Jan", "value": 1_500_000.0},
            {"label": "Feb", "value": 2_300_000.0},
        ]
        result = render_line_chart(points, "Revenue M", "Revenue")
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_renderer_no_title(self):
        from odoo.addons.trmnl.trmnl_chart_preview import render_line_chart
        result = render_line_chart([{"label": "Jan", "value": 1.0}], "", "Count")
        self.assertTrue(result.startswith(b"\x89PNG"))
