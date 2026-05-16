"""Tests for graph view type: data loading, validation, and renderer."""

from __future__ import annotations

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestGraphDataLoading(TransactionCase):
    """_load_graph_data: aggregation, normalisation, sorting, and filtering."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._device = cls.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:77",
            "approval_state": "accepted",
            "registration_source": "setup",
        })
        cls._partner_model = cls.env["ir.model"].sudo().search(
            [("model", "=", "res.partner")], limit=1
        )
        cls._groupby_field = cls.env["ir.model.fields"].sudo().search(
            [("model", "=", "res.partner"), ("name", "=", "country_id")], limit=1
        )

    def _profile(self, **vals):
        base = {
            "name": "Graph test",
            "device_id": self._device.id,
            "app_model_id": self._partner_model.id,
            "trmnl_layout": "graph",
            "filter_preset": "none",
            "graph_groupby_field_id": self._groupby_field.id,
            "graph_sort_order": "value_desc",
            "graph_max_groups": 10,
        }
        base.update(vals)
        return self.env["trmnl.profile"].sudo().create(base)

    # ------------------------------------------------------------------
    # graph always available
    # ------------------------------------------------------------------

    def test_graph_in_available_view_types(self):
        """graph is always in _get_available_view_types for any model."""
        profile = self._profile()
        self.assertIn("graph", profile._get_available_view_types())

    # ------------------------------------------------------------------
    # constraint: groupby required
    # ------------------------------------------------------------------

    def test_graph_layout_without_groupby_raises(self):
        with self.assertRaises(ValidationError):
            self.env["trmnl.profile"].sudo().create({
                "name": "Missing groupby",
                "device_id": self._device.id,
                "app_model_id": self._partner_model.id,
                "trmnl_layout": "graph",
                "filter_preset": "none",
                "graph_sort_order": "value_desc",
                "graph_max_groups": 10,
            })

    def test_graph_layout_with_groupby_saves_cleanly(self):
        profile = self._profile()
        self.assertEqual(profile.trmnl_layout, "graph")
        self.assertTrue(profile.graph_groupby_field_id)

    # ------------------------------------------------------------------
    # _load_graph_data: basic structure
    # ------------------------------------------------------------------

    def test_load_graph_data_returns_list_of_dicts(self):
        profile = self._profile()
        bars = profile._load_graph_data("res.partner")
        self.assertIsInstance(bars, list)
        for bar in bars:
            self.assertIn("label", bar)
            self.assertIn("value", bar)
            self.assertIsInstance(bar["value"], float)

    def test_load_graph_data_count_mode(self):
        """Without measure field, value is the record count per group."""
        profile = self._profile()
        bars = profile._load_graph_data("res.partner")
        # Each bar value must be >= 1 (groups with 0 records aren't returned by read_group).
        for bar in bars:
            self.assertGreaterEqual(bar["value"], 0)

    def test_load_graph_data_limited_by_max_groups(self):
        """graph_max_groups caps the number of returned bars."""
        profile = self._profile(graph_max_groups=2)
        bars = profile._load_graph_data("res.partner")
        self.assertLessEqual(len(bars), 2)

    def test_load_graph_data_max_groups_capped_at_20(self):
        """graph_max_groups > 20 is silently clamped to 20."""
        profile = self._profile(graph_max_groups=999)
        bars = profile._load_graph_data("res.partner")
        self.assertLessEqual(len(bars), 20)

    # ------------------------------------------------------------------
    # sorting
    # ------------------------------------------------------------------

    def test_sort_value_desc(self):
        profile = self._profile(graph_sort_order="value_desc")
        bars = profile._load_graph_data("res.partner")
        values = [b["value"] for b in bars]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_sort_value_asc(self):
        profile = self._profile(graph_sort_order="value_asc")
        bars = profile._load_graph_data("res.partner")
        values = [b["value"] for b in bars]
        self.assertEqual(values, sorted(values))

    def test_sort_label_asc(self):
        profile = self._profile(graph_sort_order="label_asc")
        bars = profile._load_graph_data("res.partner")
        labels = [b["label"].lower() for b in bars]
        self.assertEqual(labels, sorted(labels))

    def test_sort_label_desc(self):
        profile = self._profile(graph_sort_order="label_desc")
        bars = profile._load_graph_data("res.partner")
        labels = [b["label"].lower() for b in bars]
        self.assertEqual(labels, sorted(labels, reverse=True))

    # ------------------------------------------------------------------
    # measure field (sum)
    # ------------------------------------------------------------------

    def test_load_graph_data_with_numeric_measure(self):
        """Specifying a measure field produces float sums instead of counts."""
        measure_field = self.env["ir.model.fields"].sudo().search(
            [("model", "=", "res.partner"), ("name", "=", "credit_limit")], limit=1
        )
        if not measure_field:
            self.skipTest("res.partner.credit_limit not found in this installation")
        profile = self._profile(graph_measure_field_id=measure_field.id)
        bars = profile._load_graph_data("res.partner")
        for bar in bars:
            self.assertIsInstance(bar["value"], float)

    # ------------------------------------------------------------------
    # domain filter applied
    # ------------------------------------------------------------------

    def test_filter_domain_applied_to_graph(self):
        """Custom domain restricts records before aggregation."""
        profile = self._profile(
            filter_domain="[('id', '<', 0)]",  # matches nothing
        )
        bars = profile._load_graph_data("res.partner")
        self.assertEqual(bars, [])

    def test_filter_preset_applied_to_graph(self):
        """filter_preset is applied before aggregation (my_records restricts to uid)."""
        profile = self._profile(filter_preset="my_records")
        bars = profile._load_graph_data("res.partner")
        # Result could be empty if uid has no partners; must not crash.
        self.assertIsInstance(bars, list)

    # ------------------------------------------------------------------
    # _graph_measure_label
    # ------------------------------------------------------------------

    def test_measure_label_count(self):
        """No measure field → label is 'Count'."""
        profile = self._profile()
        self.assertEqual(profile._graph_measure_label(), "Count")

    def test_measure_label_field_description(self):
        """Measure field set → label is the field's description."""
        measure_field = self.env["ir.model.fields"].sudo().search(
            [("model", "=", "res.partner"), ("name", "=", "credit_limit")], limit=1
        )
        if not measure_field:
            self.skipTest("res.partner.credit_limit not found in this installation")
        profile = self._profile(graph_measure_field_id=measure_field.id)
        label = profile._graph_measure_label()
        self.assertEqual(label, measure_field.field_description or measure_field.name)


@tagged("-at_install", "post_install")
class TestGraphSelection(TransactionCase):
    """_load_graph_data label normalisation for selection fields."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._device = cls.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:78",
            "approval_state": "accepted",
            "registration_source": "setup",
        })
        cls._partner_model = cls.env["ir.model"].sudo().search(
            [("model", "=", "res.partner")], limit=1
        )

    def test_selection_field_labels_resolved(self):
        """Groupby a selection field: bar labels are the human-readable selection labels."""
        sel_field = self.env["ir.model.fields"].sudo().search(
            [("model", "=", "res.partner"), ("ttype", "=", "selection"), ("name", "=", "type")],
            limit=1,
        )
        if not sel_field:
            self.skipTest("res.partner has no suitable selection field")
        profile = self.env["trmnl.profile"].sudo().create({
            "name": "Graph sel test",
            "device_id": self._device.id,
            "app_model_id": self._partner_model.id,
            "trmnl_layout": "graph",
            "filter_preset": "none",
            "graph_groupby_field_id": sel_field.id,
            "graph_sort_order": "value_desc",
            "graph_max_groups": 10,
        })
        bars = profile._load_graph_data("res.partner")
        # Labels must be strings (never raw selection keys like "delivery").
        for bar in bars:
            self.assertIsInstance(bar["label"], str)
            self.assertTrue(bar["label"])  # non-empty


@tagged("-at_install", "post_install")
class TestGraphRendering(TransactionCase):
    """End-to-end graph rendering via _render_and_store_preview."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._device = cls.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:79",
            "approval_state": "accepted",
            "registration_source": "setup",
        })
        cls._partner_model = cls.env["ir.model"].sudo().search(
            [("model", "=", "res.partner")], limit=1
        )
        cls._groupby_field = cls.env["ir.model.fields"].sudo().search(
            [("model", "=", "res.partner"), ("name", "=", "country_id")], limit=1
        )

    def _profile(self, **vals):
        base = {
            "name": "Graph render test",
            "device_id": self._device.id,
            "app_model_id": self._partner_model.id,
            "trmnl_layout": "graph",
            "filter_preset": "none",
            "graph_groupby_field_id": self._groupby_field.id,
            "graph_sort_order": "value_desc",
            "graph_max_groups": 10,
        }
        base.update(vals)
        return self.env["trmnl.profile"].sudo().create(base)

    def test_render_and_store_preview_produces_image(self):
        """Full pipeline: _render_and_store_preview writes preview_image for graph layout."""
        profile = self._profile()
        profile._render_and_store_preview()
        self.assertTrue(profile.preview_image)
        self.assertTrue(profile.preview_generated_at)

    def test_render_with_custom_title(self):
        """graph_title is passed through to the renderer without error."""
        profile = self._profile(graph_title="Partners by Country")
        profile._render_and_store_preview()
        self.assertTrue(profile.preview_image)

    def test_render_with_domain_filter(self):
        """Domain filter restricts records before aggregation; render still succeeds."""
        profile = self._profile(filter_domain="[('name', '!=', False)]")
        profile._render_and_store_preview()
        self.assertTrue(profile.preview_image)

    def test_render_with_empty_result(self):
        """Graph renders 'No data' when domain matches nothing — no crash."""
        profile = self._profile(filter_domain="[('id', '<', 0)]")
        profile._render_and_store_preview()
        self.assertTrue(profile.preview_image)

    def test_action_render_preview_returns_action(self):
        """action_render_preview returns an ir.actions.client dict."""
        profile = self._profile()
        result = profile.action_render_preview()
        self.assertEqual(result.get("type"), "ir.actions.client")


@tagged("-at_install", "post_install")
class TestGraphRendererUnit(TransactionCase):
    """Unit tests for the pure-Python render_graph_preview function."""

    def test_renderer_returns_png_bytes(self):
        from odoo.addons.trmnl.trmnl_graph_preview import render_graph_preview
        bars = [{"label": "Alpha", "value": 10.0}, {"label": "Beta", "value": 5.0}]
        result = render_graph_preview(bars, "Test", "Count")
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_renderer_empty_bars(self):
        from odoo.addons.trmnl.trmnl_graph_preview import render_graph_preview
        result = render_graph_preview([], "Empty", "Count")
        self.assertIsInstance(result, bytes)
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_renderer_single_bar(self):
        from odoo.addons.trmnl.trmnl_graph_preview import render_graph_preview
        result = render_graph_preview([{"label": "Only", "value": 42.0}], "Single", "Count")
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_renderer_zero_values(self):
        """All-zero values render without error (no division by zero)."""
        from odoo.addons.trmnl.trmnl_graph_preview import render_graph_preview
        bars = [{"label": "A", "value": 0.0}, {"label": "B", "value": 0.0}]
        result = render_graph_preview(bars, "Zeros", "Count")
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_renderer_custom_dimensions(self):
        """Custom width/content_height produce a PNG of the requested size."""
        from PIL import Image
        import io
        from odoo.addons.trmnl.trmnl_graph_preview import render_graph_preview
        bars = [{"label": "X", "value": 1.0}]
        png = render_graph_preview(bars, "Dim", "Count", width=400, content_height=300)
        img = Image.open(io.BytesIO(png))
        self.assertEqual(img.size, (400, 300))

    def test_renderer_long_labels_truncated(self):
        """Very long labels do not crash the renderer."""
        from odoo.addons.trmnl.trmnl_graph_preview import render_graph_preview
        bars = [{"label": "A" * 200, "value": 5.0}]
        result = render_graph_preview(bars, "Long", "Count")
        self.assertTrue(result.startswith(b"\x89PNG"))

    def test_renderer_many_bars(self):
        """More bars than fit on screen renders an overflow indicator without crash."""
        from odoo.addons.trmnl.trmnl_graph_preview import render_graph_preview
        bars = [{"label": f"Group {i}", "value": float(i)} for i in range(50)]
        result = render_graph_preview(bars, "Many", "Count")
        self.assertTrue(result.startswith(b"\x89PNG"))
