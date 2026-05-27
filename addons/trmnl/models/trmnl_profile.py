"""TRMNL profile — Odoo model: fields, domain building, and data access.

Rendering orchestration (render timing, calendar data loading, renderer
dispatch, footer compositing, PNG persistence) lives in the companion mixin
``trmnl_profile_render.TrmnlProfileRenderMixin`` (``_inherit = "trmnl.profile"``).

See ``trmnl_profile_render.py`` for the two-layer architecture overview.
"""
from __future__ import annotations

import base64
import hashlib
import logging
from calendar import monthrange
from datetime import date, timedelta
from urllib.parse import urlparse

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain
from odoo.tools.safe_eval import safe_eval

from .trmnl_device import client_can_reach_host, is_device_reachable_base_url

_logger = logging.getLogger(__name__)

_DOMAIN_BOOL_OPS = frozenset(("&", "|", "!"))

# Technical model namespace prefixes that should never appear in the TRMNL
# model selector.  Only clear infrastructure namespaces are listed here;
# transient (wizard) and abstract (mixin) models are excluded via field flags
# rather than by name.  "not ilike" produces NOT ILIKE '%prefix%' in SQL,
# which is safe because no business model has these strings as substrings.
_TECHNICAL_MODEL_PREFIXES = (
    "ir.",        # Odoo infrastructure: ir.model, ir.ui.view, ir.rule, …
    "base.",      # Internal base utilities: base.automation, base.import.*, …
    "bus.",       # Web-push bus framework
    "web.",       # Web-client technical models
    "auth.",      # Authentication / TOTP / passkey models
    "resource.",  # Scheduling-resource infrastructure (resource.calendar, …)
)

# Domain applied to the app_model_id Many2one field.  Excludes transient and
# abstract models by flag, then excludes known technical namespaces by prefix.
_APP_MODEL_DOMAIN = (
    [("transient", "=", False), ("abstract", "=", False)]
    + [("model", "not ilike", p) for p in _TECHNICAL_MODEL_PREFIXES]
)

# Priority-ordered list of date/datetime fields used by filter_preset.
# create_date is the guaranteed fallback — it exists on every Odoo model.
_FILTER_DATE_FIELDS = ["date_deadline", "date_order", "start", "date", "create_date"]

# Maps Odoo technical view type names to supported profile view type values.
_ODOO_VIEW_TYPE_MAP = {"tree": "list", "list": "list", "kanban": "kanban", "calendar": "calendar", "graph": "graph"}

# Supported view types for the trmnl_layout selection.
# "graph" covers all chart subtypes (bar, line, …) via the graph_type field.
SUPPORTED_VIEW_TYPES = ("list", "kanban", "calendar", "graph")

# Human-readable labels for each supported view type (validation messages, UI).
_LAYOUT_LABELS = {"list": "List", "kanban": "Kanban", "calendar": "Calendar", "graph": "Graph"}

# Allowed field types per layout — drives display_field_ids picker filtering.
# Calendar uses no display_field_ids (picker is hidden via view visibility).
_LAYOUT_ALLOWED_TTYPES = {
    "list":   frozenset({"char", "text", "selection", "many2one", "boolean", "date", "datetime", "integer", "float", "monetary"}),
    "kanban": frozenset({"char", "text", "selection", "many2one", "boolean", "date", "datetime", "integer", "float", "monetary"}),
}


class TrmnlProfile(models.Model):
    _name = "trmnl.profile"
    _description = "TRMNL Profile"
    _order = "sequence, name"

    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)

    device_id = fields.Many2one(
        "trmnl.device",
        string="Device",
        required=True,
        ondelete="cascade",
    )

    app_model_id = fields.Many2one(
        "ir.model",
        string="Odoo Model",
        domain=_APP_MODEL_DOMAIN,
    )

    app_model_name = fields.Char(
        related="app_model_id.model",
        string="Model Technical Name",
        store=False,
        readonly=True,
    )

    trmnl_layout = fields.Selection(
        selection="_get_layout_selection_options",
        string="View Type",
        default="list",
        required=True,
    )

    available_view_types = fields.Char(
        compute="_compute_available_view_types",
        store=False,
    )

    user_ids = fields.Many2many(
        "res.users",
        "trmnl_profile_res_users_rel",
        "profile_id",
        "user_id",
        string="Users",
        help=(
            "Records for this profile are fetched as these users. "
            "Affects the 'Assigned to Me' filter and the uid variable in custom domains. "
            "Leave empty to use the active user at render time."
        ),
    )

    display_field_ids = fields.Many2many(
        "ir.model.fields",
        "trmnl_profile_ir_model_fields_rel",
        "profile_id",
        "field_id",
        string="Display Fields",
    )

    kanban_stage_field_id = fields.Many2one(
        "ir.model.fields",
        string="Stage Field",
        domain="[('model_id', '=', app_model_id), ('ttype', 'in', ['many2one', 'selection'])]",
        help=(
            "Field used to group items into kanban sections (e.g. stage_id, state). "
            "When empty, the renderer picks a sensible default on the model."
        ),
    )

    display_limit = fields.Integer(default=20)
    display_order = fields.Char(default="id desc")

    filter_preset = fields.Selection([
        ("none",       "No Filter"),
        ("my_records", "Assigned to Me"),
        ("today",      "Today"),
        ("this_week",  "This Week"),
        ("this_month", "This Month"),
        ("overdue",    "Overdue"),
    ], string="Filter", default="none", required=True)

    filter_domain = fields.Char(
        string="Custom Domain",
        default="[]",
        help=(
            "Extra Odoo domain applied on top of the Filter preset. "
            "Example: [('priority', '=', '1')] \n"
            "Supports: uid, context_today(), True, False."
        ),
    )

    include_archived = fields.Boolean(
        string="Include Archived",
        default=False,
        help="When enabled, archived records (active=False) are included in results.",
    )

    # ── Graph fields (shared by all graph subtypes) ───────────────────────────
    graph_type = fields.Selection([
        ("bar",  "Bar"),
        ("line", "Line"),
    ], string="Graph Type", default="bar", required=True)

    graph_groupby_field_id = fields.Many2one(
        "ir.model.fields",
        string="Group By",
        domain="[('model_id', '=', app_model_id), ('ttype', 'in', ['char', 'text', 'selection', 'many2one', 'date', 'datetime', 'boolean', 'integer'])]",
        help="Field to group records by. Each distinct value becomes one bar.",
    )
    graph_measure_field_id = fields.Many2one(
        "ir.model.fields",
        string="Measure",
        domain="[('model_id', '=', app_model_id), ('ttype', 'in', ['integer', 'float', 'monetary']), ('store', '=', True)]",
        help="Numeric field to sum per group. Leave empty to count records.",
    )
    graph_sort_order = fields.Selection([
        ("value_desc",  "Value — High to Low"),
        ("value_asc",   "Value — Low to High"),
        ("label_asc",   "Label — A to Z"),
        ("label_desc",  "Label — Z to A"),
    ], string="Sort", default="value_desc", required=True)
    graph_max_groups = fields.Integer(
        string="Max Bars",
        default=10,
        help="Maximum number of bars to display (capped at 20).",
    )
    graph_title = fields.Char(
        string="Chart Title",
        help="Optional chart title. Defaults to the Group By field name.",
    )

    # ── Line chart fields ─────────────────────────────────────────────────────
    line_date_field_id = fields.Many2one(
        "ir.model.fields",
        string="Date Field",
        domain="[('model_id', '=', app_model_id), ('ttype', 'in', ['date', 'datetime'])]",
        help="Date or datetime field used as the x-axis. Required for Line layout.",
    )
    line_measure_field_id = fields.Many2one(
        "ir.model.fields",
        string="Measure (blank = Count)",
        domain="[('model_id', '=', app_model_id), ('ttype', 'in', ['integer', 'float', 'monetary']), ('store', '=', True)]",
        help="Numeric field to sum per time bucket. Leave empty to count records.",
    )
    line_date_groupby = fields.Selection([
        ("day",   "Day"),
        ("week",  "Week"),
        ("month", "Month"),
    ], string="Group By", default="month", required=True)
    line_max_points = fields.Integer(
        string="Max Points",
        default=12,
        help="Maximum number of data points on the x-axis (capped at 52).",
    )

    calendar_view_mode = fields.Selection([
        ("month", "Month"),
        ("week",  "Week"),
    ], string="Calendar View", default="month", required=True)

    calendar_week_mode = fields.Selection([
        ("work_week", "Work Week (Mon–Fri)"),
        ("full_week", "Full Week (Mon–Sun)"),
    ], string="Week Mode", default="work_week", required=True)

    calendar_reference_mode = fields.Selection([
        ("today",  "Current"),
        ("custom", "Custom Date"),
    ], string="Reference", default="today", required=True)

    calendar_reference_date = fields.Date(string="Reference Date")

    preview_image = fields.Binary(string="Preview", readonly=True)
    preview_generated_at = fields.Datetime(string="Preview Generated At", readonly=True)
    preview_data_stale = fields.Boolean(
        default=False,
        help="Set by the data-change watcher when source records are created, "
             "modified, or deleted. Cleared after each successful render. "
             "Causes _should_render_for_device to return True on the next poll.",
    )
    preview_renderer_version = fields.Char(
        string="Preview Renderer Version",
        readonly=True,
        help="Odoo module version used for the last render; stale values trigger re-render on device poll.",
    )
    preview_image_html = fields.Html(
        string="Preview",
        compute="_compute_preview_image_html",
        sanitize=False,
        readonly=True,
    )

    auto_refresh_interval_minutes = fields.Integer(
        string="Render Interval (min)",
        default=10,
        help=(
            "How often Odoo re-renders the preview image during device polls. "
            "Zero or negative falls back to 10 minutes. "
            "The device poll frequency is controlled separately by Refresh Rate on the device."
        ),
    )

    device_last_polled_at = fields.Datetime(
        string="Device Last Polled",
        related="device_id.last_display_at",
        readonly=True,
    )
    device_refresh_rate = fields.Integer(
        string="Current Refresh Rate (s)",
        related="device_id.desired_refresh_rate",
        readonly=True,
    )
    device_next_expected_poll_at = fields.Datetime(
        string="Next Expected Poll",
        compute="_compute_device_next_expected_poll_at",
        readonly=True,
    )
    display_image_url = fields.Char(
        string="Image URL",
        compute="_compute_display_image_url",
        readonly=True,
    )
    url_warning = fields.Char(
        string="URL Warning",
        compute="_compute_url_warning",
        readonly=True,
    )
    layout_warning = fields.Char(
        string="Layout Warning",
        compute="_compute_layout_warning",
        store=False,
    )

    # ------------------------------------------------------------------
    # onchange
    # ------------------------------------------------------------------

    @api.onchange("app_model_id")
    def _onchange_app_model_id(self):
        """Model changed: reset display fields and pick best default layout."""
        self.display_field_ids = False
        available = self._get_available_view_types()
        if "calendar" in available:
            self.trmnl_layout = "calendar"
        elif available:
            self.trmnl_layout = available[0]

    @api.onchange("trmnl_layout")
    def _onchange_trmnl_layout(self):
        """Drop display_field_ids that are not allowed by the newly selected layout."""
        layout = self.trmnl_layout or "list"
        allowed = _LAYOUT_ALLOWED_TTYPES.get(layout)
        if allowed is not None and self.display_field_ids:
            self.display_field_ids = self.display_field_ids.filtered(
                lambda f: f.ttype in allowed
            )

    # ------------------------------------------------------------------
    # domain / filter helpers
    # ------------------------------------------------------------------

    def _eval_filter_domain(self, domain_str):
        """Evaluate a domain string using safe_eval with a restricted Odoo context.

        Returns a plain list suitable for use in ``search()``.
        Raises ``ValueError`` on syntax/type errors so callers can wrap it in
        whatever exception type is appropriate for their context.
        """
        if not domain_str or domain_str.strip() in ("", "[]"):
            return []
        profile_user = self.user_ids[:1] or self.env.user
        eval_ctx = {
            "uid": profile_user.id,
            "user": profile_user,
            "context_today": lambda: fields.Date.today(),
            "current_date": str(fields.Date.today()),
            "True": True,
            "False": False,
            "None": None,
        }
        result = safe_eval(domain_str, eval_ctx)
        if not isinstance(result, list):
            raise ValueError(_("Domain must evaluate to a list, got %s.") % type(result).__name__)
        return result

    def _validate_custom_domain_fields(self, domain, model_name):
        """Raise UserError if any domain leaf references a field absent from model_name.

        This is the render-time semantic complement to _validate_domain_leaves()
        (which is the save-time structural check). Structural validity is checked at
        save time; model-field existence is only knowable at render time once we have
        a concrete model_name.

        Only the first segment of dotted paths is checked (e.g. 'partner_id' of
        'partner_id.name'), since ORM traversal handles the rest.
        """
        if model_name not in self.env:
            return
        model_fields = self.env[model_name]._fields
        for token in domain:
            # Must test str before "token in _DOMAIN_BOOL_OPS" — list leaves are unhashable.
            if isinstance(token, str) and token in _DOMAIN_BOOL_OPS:
                continue
            if not isinstance(token, (list, tuple)) or len(token) != 3:
                continue
            field_path = token[0]
            if not isinstance(field_path, str):
                continue
            first_field = field_path.split(".")[0]
            if first_field not in model_fields:
                raise UserError(
                    _("Custom Domain references unknown field '%s' on model '%s'. "
                      "Please correct or clear the Custom Filter.")
                    % (first_field, model_name)
                )

    def _build_effective_domain(self, model_name):
        """Combine all active domain sources into a single ORM domain list.

        Sources applied with AND in this order:
        1. Filter preset  — from _build_filter_domain(); always silent.
        2. Custom domain  — from filter_domain; raises UserError on eval/field error.
        """
        domains = []

        # 1. Filter preset domain
        preset_domain = self._build_filter_domain(model_name)
        if preset_domain:
            domains.append(preset_domain)

        # 2. Custom filter_domain — eval errors and unknown fields both raise UserError.
        raw_custom = (self.filter_domain or "").strip()
        if raw_custom and raw_custom != "[]":
            try:
                custom_domain = self._eval_filter_domain(raw_custom)
                if custom_domain:
                    custom_domain = self._normalize_domain_m2o_values(custom_domain)
                    self._validate_custom_domain_fields(custom_domain, model_name)
                    domains.append(custom_domain)
            except UserError:
                raise
            except Exception as exc:
                raise UserError(
                    _("Custom Domain is invalid and could not be applied: %s") % exc
                ) from exc

        return list(Domain.AND(domains)) if domains else []

    @staticmethod
    def _normalize_domain_m2o_values(domain):
        """Replace [id, "display_name"] many2one pairs in domain values with plain id.

        Odoo's domain widget serialises many2one equality values as a 2-element
        list [id, label].  That representation is accepted by our validator but
        rejected by the ORM's search() which expects a bare integer.  Walk every
        leaf and flatten any such pair so the domain is ORM-safe.
        """
        normalized = []
        for token in domain:
            if isinstance(token, str) and token in _DOMAIN_BOOL_OPS:
                normalized.append(token)
            elif isinstance(token, (list, tuple)) and len(token) == 3:
                field_path, op, value = token
                if (
                    isinstance(value, (list, tuple))
                    and len(value) == 2
                    and isinstance(value[0], int)
                    and isinstance(value[1], str)
                ):
                    value = value[0]
                normalized.append((field_path, op, value))
            else:
                normalized.append(token)
        return normalized

    @staticmethod
    def _validate_domain_leaves(domain):
        """Raise ValueError if any leaf is not a valid 3-element (field, op, value) tuple.

        Domain.AND() in Odoo 19 validates structure but this method also catches
        inputs like [('a', 'b')] (2-tuple) at save time rather than producing a
        cryptic database error at render/search time.
        """
        for token in domain:
            if isinstance(token, str) and token in _DOMAIN_BOOL_OPS:
                continue
            if not isinstance(token, (list, tuple)):
                raise ValueError(
                    "Domain leaf must be a tuple, got %s: %r" % (type(token).__name__, token)
                )
            if len(token) != 3:
                raise ValueError(
                    "Domain leaf must have exactly 3 elements (field, operator, value), "
                    "got %d: %r" % (len(token), tuple(token))
                )
            field_name, op, _value = token
            if not isinstance(field_name, str) or not field_name:
                raise ValueError(
                    "Domain leaf field name must be a non-empty string, got: %r" % (field_name,)
                )
            if not isinstance(op, str) or not op:
                raise ValueError(
                    "Domain leaf operator must be a non-empty string, got: %r" % (op,)
                )

    @api.constrains("filter_domain")
    def _check_filter_domain(self):
        for rec in self:
            raw = (rec.filter_domain or "").strip()
            if not raw or raw == "[]":
                continue
            try:
                domain = rec._eval_filter_domain(raw)
                Domain.AND([domain])
                self._validate_domain_leaves(domain)
            except Exception as exc:
                raise ValidationError(
                    _("Custom Domain is not a valid Odoo domain: %s") % exc
                ) from exc

    @api.constrains("trmnl_layout", "app_model_id")
    def _check_layout_valid_for_model(self):
        for rec in self:
            if not rec.app_model_id or not rec.trmnl_layout:
                continue
            available = rec._get_available_view_types()
            if available and rec.trmnl_layout not in available:
                label = _LAYOUT_LABELS.get(rec.trmnl_layout, rec.trmnl_layout)
                raise ValidationError(
                    _("View Type '%s' is not available for the selected model '%s'. "
                      "Available types: %s.")
                    % (label, rec.app_model_id.name, ", ".join(available))
                )

    @api.constrains("trmnl_layout", "graph_type", "graph_groupby_field_id", "line_date_field_id")
    def _check_graph_config(self):
        for rec in self:
            if rec.trmnl_layout != "graph":
                continue
            if rec.graph_type == "bar":
                if not rec.graph_groupby_field_id:
                    raise ValidationError(
                        _("Bar chart requires a 'Group By' field to be set.")
                    )
            elif rec.graph_type == "line":
                if not rec.line_date_field_id:
                    raise ValidationError(
                        _("Line chart requires a 'Date Field' to be set.")
                    )
                if rec.line_date_field_id.ttype not in ("date", "datetime"):
                    raise ValidationError(
                        _("Line chart 'Date Field' must be a date or datetime field (got '%s').")
                        % rec.line_date_field_id.ttype
                    )

    def _build_filter_domain(self, model_name):
        """Return an ORM domain list for the active filter_preset.

        Always silent: if the required field is absent the filter is skipped
        and an empty domain (no restriction) is returned. This ensures the
        device display path never crashes due to a misconfigured filter.
        """
        if self.filter_preset == "none":
            return []

        existing = set(
            self.env["ir.model.fields"].sudo().search([
                ("model", "=", model_name),
                ("name", "in", _FILTER_DATE_FIELDS + ["user_id"]),
            ]).mapped("name")
        )

        if self.filter_preset == "my_records":
            if "user_id" not in existing:
                return []
            if self.user_ids:
                return [("user_id", "in", self.user_ids.ids)]
            return [("user_id", "=", self.env.uid)]

        date_field = next((f for f in _FILTER_DATE_FIELDS if f in existing), None)
        if not date_field:
            return []

        today = fields.Date.today()

        if self.filter_preset == "today":
            return [(date_field, ">=", today), (date_field, "<", today + timedelta(days=1))]

        if self.filter_preset == "this_week":
            week_start = today - timedelta(days=today.weekday())
            return [(date_field, ">=", week_start), (date_field, "<", week_start + timedelta(days=7))]

        if self.filter_preset == "this_month":
            _, last_day = monthrange(today.year, today.month)
            return [(date_field, ">=", today.replace(day=1)), (date_field, "<=", today.replace(day=last_day))]

        if self.filter_preset == "overdue":
            return [(date_field, "<", today)]

        return []

    # ------------------------------------------------------------------
    # available view types
    # ------------------------------------------------------------------

    def _get_available_view_types(self):
        """Return sorted list of supported view type values for app_model_id.

        Queries ir.ui.view for views of the model and maps Odoo technical type
        names to profile view type values via _ODOO_VIEW_TYPE_MAP.
        Returns only types that actually exist in ir.ui.view for the model.
        """
        self.ensure_one()
        if not self.app_model_id:
            return list(SUPPORTED_VIEW_TYPES)
        model_name = self.app_model_id.model
        view_types = self.env["ir.ui.view"].sudo().search_read(
            [("model", "=", model_name), ("type", "in", list(_ODOO_VIEW_TYPE_MAP.keys()))],
            fields=["type"],
        )
        found = set()
        for v in view_types:
            mapped = _ODOO_VIEW_TYPE_MAP.get(v["type"])
            if mapped and mapped in SUPPORTED_VIEW_TYPES:
                found.add(mapped)
        return sorted(found, key=lambda t: SUPPORTED_VIEW_TYPES.index(t))

    @staticmethod
    def _get_app_model_domain():
        """Return the domain used to filter app_model_id in the UI.

        Exposed as a staticmethod so tests can call it without a profile
        instance and verify the exact set of selectable models.
        Excludes transient (wizard) and abstract (mixin) models by ORM flag,
        then excludes known technical namespaces by prefix.
        """
        return list(_APP_MODEL_DOMAIN)

    def _model_has_date_field(self, model_name: str) -> bool:
        """Return True if model_name has at least one date or datetime field."""
        return bool(
            self.env["ir.model.fields"].sudo().search_count([
                ("model", "=", model_name),
                ("ttype", "in", ["date", "datetime"]),
            ])
        )

    @api.depends("app_model_id")
    def _compute_available_view_types(self):
        for rec in self:
            rec.available_view_types = ",".join(rec._get_available_view_types())

    def _get_layout_selection_options(self):
        """Return trmnl_layout selection options filtered by the model's available view types.

        Odoo calls this on every empty recordset (fields_get, convert_to_cache),
        where app_model_id is always False — returning all three options keeps all
        stored values valid and prevents ORM rejection of existing records.
        Per-record filtering only affects the form dropdown when a model is selected.
        """
        if not self.app_model_id:
            return list(_LAYOUT_LABELS.items())
        available = self._get_available_view_types()
        options = [(t, _LAYOUT_LABELS[t]) for t in available if t in _LAYOUT_LABELS]
        return options if options else list(_LAYOUT_LABELS.items())

    @api.depends("trmnl_layout", "app_model_id")
    def _compute_layout_warning(self):
        for rec in self:
            if not rec.app_model_id or not rec.trmnl_layout:
                rec.layout_warning = ""
                continue
            available = rec._get_available_view_types()
            if rec.trmnl_layout not in available:
                label = _LAYOUT_LABELS.get(rec.trmnl_layout, rec.trmnl_layout)
                rec.layout_warning = (
                    f"View Type '{label}' is not available for the selected model. "
                    f"Please choose one of: {', '.join(available)}."
                )
            else:
                rec.layout_warning = ""

    # ------------------------------------------------------------------
    # computed delivery-status fields
    # ------------------------------------------------------------------

    @staticmethod
    def _is_device_reachable_base_url(url):
        """Return True if url's host is reachable by a physical LAN device."""
        return is_device_reachable_base_url(url)

    @api.depends("device_id.last_display_at", "device_id.desired_refresh_rate")
    def _compute_device_next_expected_poll_at(self):
        for rec in self:
            last = rec.device_id.last_display_at
            rate = rec.device_id.desired_refresh_rate
            if last and rate:
                rec.device_next_expected_poll_at = last + timedelta(seconds=rate)
            else:
                rec.device_next_expected_poll_at = False

    @api.depends("preview_image", "preview_generated_at")
    def _compute_preview_image_html(self):
        """Form preview using a cache-busted image URL.

        The URL version token combines ``preview_generated_at`` (always updated
        on every render) with a short hash of the PNG bytes.  The timestamp
        component ensures the URL changes after every render even when the image
        bytes are identical, which forces OWL to update the DOM <img> src and
        triggers a fresh browser fetch.
        """
        for rec in self:
            if not rec.preview_image or not rec.id:
                rec.preview_image_html = False
                continue
            try:
                raw = base64.b64decode(rec.preview_image)
                digest = hashlib.sha256(raw).hexdigest()[:12]
            except Exception:
                digest = "unknown"
            # Include preview_generated_at so the URL always changes after every
            # render, even when image bytes are identical. Without this, OWL's
            # virtual-DOM diff sees the same <img src> string and skips the DOM
            # update — the browser never re-fetches the updated image.
            ts = (
                rec.preview_generated_at.strftime("%Y%m%d%H%M%S")
                if rec.preview_generated_at
                else ""
            )
            version = f"{ts}-{digest}" if ts and digest else digest or ts
            cache_qs = f"?v={version}" if version else ""
            # Same endpoint the device downloads — avoids /web/image processing
            # or cache differences vs /api/profile/image/<id>.
            url = f"/api/profile/image/{rec.id}{cache_qs}"
            rec.preview_image_html = (
                f'<img src="{url}" alt="Preview" '
                f'style="max-width:100%;height:auto;display:block;"/>'
            )

    @api.depends("preview_image", "preview_generated_at")
    def _compute_display_image_url(self):
        for rec in self:
            rec.display_image_url = rec._get_display_image_url() or ""

    @api.depends("preview_image", "preview_generated_at")
    def _compute_url_warning(self):
        for rec in self:
            if not rec.preview_image:
                rec.url_warning = ""
                continue
            params = rec.env["ir.config_parameter"].sudo()
            if params.get_param("trmnl.public_base_url", "").strip():
                rec.url_warning = ""
                continue
            web_url = params.get_param("web.base.url", "").strip()
            if not rec._is_device_reachable_base_url(web_url):
                rec.url_warning = (
                    f"Image URL cannot be generated: web.base.url ({web_url}) is a "
                    f"loopback/internal address that physical devices cannot reach. "
                    f"This resolves automatically when the device polls — the server "
                    f"uses the poll Host header and corrects stale URLs on the device LAN."
                )
            else:
                rec.url_warning = ""

    # ------------------------------------------------------------------
    # image URL and data access helpers
    # ------------------------------------------------------------------

    def _preview_png_digest(self) -> str | None:
        """Short hash of stored preview bytes (cache-bust URL + filename)."""
        if not self.preview_image:
            return None
        try:
            raw = base64.b64decode(self.preview_image)
            return hashlib.sha256(raw).hexdigest()[:12]
        except Exception:
            return None

    @api.model
    def _get_installed_trmnl_version(self):
        """Installed ``trmnl`` module version (changes on ``-u trmnl``)."""
        mod = self.env["ir.module.module"].sudo().search([("name", "=", "trmnl")], limit=1)
        return (mod.installed_version or "") if mod else ""

    def _is_preview_renderer_stale(self) -> bool:
        """True when the stored PNG was rendered with an older module version."""
        self.ensure_one()
        if not self.preview_image:
            return False
        current = self._get_installed_trmnl_version()
        if not current:
            return False
        return (self.preview_renderer_version or "") != current

    @api.model
    def _resolve_device_base_url(self):
        """Pick a base URL that the polling TRMNL can actually reach.

        When ``trmnl_poll_base_url`` / ``trmnl_client_ip`` are in the env context
        (set by ``/api/display``), the poll Host and the device Wi‑Fi subnet are
        used to skip stale ``trmnl.public_base_url`` values (e.g. 10.x while the
        device is on 192.168.x).

        Without poll context (form preview, manual render), falls back to
        ``trmnl.public_base_url`` then ``web.base.url``.
        """
        poll_url = (self.env.context.get("trmnl_poll_base_url") or "").strip().rstrip("/")
        client_ip = (self.env.context.get("trmnl_client_ip") or "").strip()

        params = self.env["ir.config_parameter"].sudo()
        public_url = params.get_param("trmnl.public_base_url", "").strip().rstrip("/")
        web_url = params.get_param("web.base.url", "").strip().rstrip("/")

        candidates = []
        if poll_url:
            candidates.append(("poll", poll_url))
        if public_url:
            candidates.append(("trmnl.public_base_url", public_url))
        if web_url:
            candidates.append(("web.base.url", web_url))

        for source, base in candidates:
            if not self._is_device_reachable_base_url(base):
                continue
            host = urlparse(base).hostname or ""
            if client_ip and host and not client_can_reach_host(client_ip, host):
                _logger.debug(
                    "TRMNL skip %s=%r for client %s (different LAN than host %s)",
                    source,
                    base,
                    client_ip,
                    host,
                )
                continue
            return base, source

        # No client context (unit tests, cron): first reachable configured URL.
        if not client_ip:
            for source, base in candidates:
                if self._is_device_reachable_base_url(base):
                    return base, source

        return False, None

    def _get_display_image_url(self):
        """Return a device-reachable URL for this profile's preview PNG, or False.

        Base URL resolution is delegated to :meth:`_resolve_device_base_url`.
        The URL includes a ``?v=<png-hash>`` query so TRMNL firmware that caches
        by URL (not only by filename) still re-downloads after a re-render.
        """
        if not self.preview_image:
            return False

        digest = self._preview_png_digest()
        cache_qs = f"?v={digest}" if digest else ""

        base, source = self._resolve_device_base_url()
        if base:
            url = f"{base}/api/profile/image/{self.id}{cache_qs}"
            _logger.debug("TRMNL profile id=%s image_url (%s): %s", self.id, source, url)
            return url

        web_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").strip()
        _logger.warning(
            "TRMNL profile id=%s: cannot generate a device-reachable image URL — "
            "web.base.url=%r and trmnl.public_base_url are missing or not reachable "
            "from the device network. They are set automatically on the first "
            "successful /api/display poll when the Host header matches the device LAN.",
            self.id,
            web_url,
        )
        return False

    def _get_display_filename(self):
        """Return a filename that changes whenever the preview is regenerated.

        Includes a short hash of the PNG bytes so the name changes even when two
        renders fall in the same wall-clock second (TRMNL uses filename equality to
        decide whether to re-download the image).
        """
        if not self.preview_image or not self.preview_generated_at:
            return False
        ts = self.preview_generated_at.strftime("%Y%m%dT%H%M%S")
        digest = self._preview_png_digest() or "unknown"
        return f"profile_{self.id}_{ts}_{digest}"

    def _load_records(self, model_name, field_names):
        """Search the target model with the full effective domain.

        Domain: filter preset AND custom filter_domain (via _build_effective_domain).
        Sort: display_order; falls back to no order on invalid SQL clause.

        UserError from _build_effective_domain (invalid custom filter_domain) is
        always re-raised. ORM/database errors during search are also converted to
        UserError when a custom filter_domain is active.
        """
        model_env = self.env[model_name].sudo()
        if self.include_archived:
            model_env = model_env.with_context(active_test=False)
        limit = self.display_limit or 20

        domain = self._build_effective_domain(model_name)
        order = self.display_order or False

        # First attempt: with sort order.
        try:
            return model_env.search(domain, limit=limit, order=order)
        except UserError:
            raise
        except Exception:
            pass

        # Second attempt: without sort order (catches bad ORDER BY clauses).
        try:
            return model_env.search(domain, limit=limit)
        except UserError:
            raise
        except Exception as exc:
            raw_custom = (self.filter_domain or "").strip()
            if raw_custom and raw_custom != "[]":
                raise UserError(
                    _("Custom Domain could not be applied: %s\nDomain: %s") % (exc, raw_custom)
                ) from exc
            raise

    _LIST_MAX_COLS = 3

    def _list_total_count(self, model_name):
        """Count records matching the profile domain (for list overflow subtitle)."""
        model_env = self.env[model_name].sudo()
        if self.include_archived:
            model_env = model_env.with_context(active_test=False)
        try:
            domain = self._build_effective_domain(model_name)
        except UserError:
            raise
        except Exception:
            return None
        try:
            return model_env.search_count(domain)
        except Exception:
            return None

    def _list_model_label(self, model_name):
        rec = self.env["ir.model"].sudo().search([("model", "=", model_name)], limit=1)
        return rec.name if rec else model_name

    def _empty_state_message(self, model_name: str) -> str:
        """Context-aware empty copy for dashboard layouts."""
        self.ensure_one()
        label = self._list_model_label(model_name)
        layout = self.trmnl_layout or "list"
        if layout == "kanban":
            return _("No items match current filters")
        if layout == "calendar":
            if self.calendar_view_mode == "week":
                return _("No meetings scheduled this week")
            return _("No events scheduled this month")
        if layout == "graph":
            if self.graph_type == "line":
                return _("No data for the selected period")
            return _("No %(model)s data for selected filters") % {"model": label}
        return _("No %(model)s match current filters") % {"model": label}

    @staticmethod
    def _format_compact_number(value: float) -> str:
        v = float(value or 0)
        if abs(v) >= 1_000_000:
            return f"{v / 1_000_000:.1f}M"
        if abs(v) >= 10_000:
            return f"{v / 1_000:.1f}k"
        if abs(v) >= 1_000:
            return f"{v / 1_000:.2f}k".rstrip("0").rstrip(".") + "k"
        if v == int(v):
            return str(int(v))
        return f"{v:.1f}"

    @staticmethod
    def _deadline_as_date(val):
        """Normalize date/datetime ORM values for comparison with ``context_today``."""
        if not val:
            return None
        if hasattr(val, "date") and callable(val.date):
            return val.date()
        return val

    def _infer_item_status(self, record, model_name, field_names) -> str:
        """Map record state to list accent: overdue, progress, done, or default."""
        Model = self.env[model_name]
        for fname in field_names:
            field_def = Model._fields.get(fname)
            if not field_def or field_def.type != "selection":
                continue
            label = (self._extract_field_value(record, fname) or "").lower()
            if any(k in label for k in ("done", "closed", "won", "complete", "cancel", "archived")):
                return "done"
            if any(k in label for k in ("progress", "doing", "running", "pending", "open")):
                return "progress"
        today = fields.Date.context_today(self)
        for fname in ("date_deadline", "activity_date_deadline"):
            if fname not in Model._fields:
                continue
            deadline = self._deadline_as_date(record[fname])
            if deadline and deadline < today:
                return "overdue"
        if self.filter_preset == "overdue":
            return "overdue"
        return ""

    def _prepare_list_items(self, records, field_names, model_name) -> list[dict]:
        """Shape ORM rows into dashboard list items for Layer 2."""
        names = field_names or ["display_name"]
        primary_f = names[0]
        meta_fs = names[1:3]
        items = []
        for rec in records:
            primary = self._extract_field_value(rec, primary_f) or "—"
            meta_parts = [self._extract_field_value(rec, f) for f in meta_fs]
            meta = " · ".join(p for p in meta_parts if p)
            items.append({
                "primary": primary,
                "meta": meta,
                "status": self._infer_item_status(rec, model_name, names),
            })
        return items

    def _resolve_kanban_stage_field(self, model_name) -> str | None:
        """Return the field name used to group kanban sections."""
        self.ensure_one()
        if self.kanban_stage_field_id and self.kanban_stage_field_id.model == model_name:
            return self.kanban_stage_field_id.name
        Model = self.env[model_name]
        for guess in ("stage_id", "state", "kanban_state", "status"):
            if guess in Model._fields and Model._fields[guess].type in ("many2one", "selection"):
                return guess
        for field_rec in self.display_field_ids.filtered(lambda f: f.model == model_name):
            if field_rec.ttype in ("many2one", "selection"):
                return field_rec.name
        return None

    def _kanban_stage_order(self, model_name, stage_field: str, stages: list[str]) -> list[str]:
        """Preserve selection order when available; else alphabetical."""
        Model = self.env[model_name]
        field_def = Model._fields.get(stage_field)
        if field_def and field_def.type == "selection":
            try:
                sel = field_def.selection
                if callable(sel):
                    sel = sel(Model)
                order = [label for _key, label in sel]
                ranked = sorted(stages, key=lambda s: order.index(s) if s in order else 999)
                return ranked + [s for s in stages if s not in ranked]
            except Exception:
                pass
        return sorted(stages, key=lambda s: s.lower())

    def _prepare_kanban_columns(self, records, model_name, field_names) -> list[dict]:
        """Group records into horizontal stage columns for the kanban renderer."""
        stage_field = self._resolve_kanban_stage_field(model_name)
        title_f = (field_names or ["display_name"])[0]
        meta_f = (field_names or [])[1:2]
        grouped: dict[str, list[str]] = {}
        for rec in records:
            stage = (
                self._extract_field_value(rec, stage_field)
                if stage_field
                else _("Unassigned")
            ) or _("Unassigned")
            title = self._extract_field_value(rec, title_f) or "—"
            meta_parts = [self._extract_field_value(rec, f) for f in meta_f]
            meta = " · ".join(p for p in meta_parts if p)
            line = f"{title} — {meta}" if meta else title
            grouped.setdefault(stage, []).append(line)
        stages = self._kanban_stage_order(model_name, stage_field or "", list(grouped.keys()))
        columns = []
        for stage in stages:
            lines = grouped[stage]
            columns.append({
                "name": stage,
                "count": len(lines),
                "items": lines,
                "hidden": 0,
            })
        return columns

    def _bar_chart_summary_lines(self, bars: list[dict], measure_label: str) -> list[str]:
        if not bars:
            return []
        lines = []
        if measure_label:
            lines.append(measure_label)
        total = sum(float(b.get("value") or 0) for b in bars)
        lines.append(_("Total: %s") % self._format_compact_number(total))
        top = max(bars, key=lambda b: float(b.get("value") or 0))
        if top.get("label"):
            lines.append(
                _("Top: %(name)s (%(val)s)") % {
                    "name": top["label"],
                    "val": self._format_compact_number(top.get("value") or 0),
                }
            )
        return lines[:3]

    def _extract_field_value(self, record, field_name):
        """Return a safe display string for one field value on any Odoo record."""
        try:
            value = record[field_name]
        except (KeyError, AttributeError):
            return ""

        if value is False or value is None:
            return ""

        field_def = record._fields.get(field_name)
        if field_def is None:
            return str(value)

        ttype = field_def.type

        if ttype == "many2one":
            return value.display_name if value else ""

        if ttype == "boolean":
            return _("Yes") if value else _("No")

        if ttype == "date":
            return value.strftime("%Y-%m-%d")

        if ttype == "datetime":
            return value.strftime("%Y-%m-%d %H:%M")

        if ttype in ("float", "monetary"):
            return f"{value:.2f}"

        if ttype == "selection":
            try:
                sel = field_def.selection
                if callable(sel):
                    sel = sel(record)
                return dict(sel).get(value, str(value)) or str(value)
            except Exception:
                return str(value)

        return str(value)
