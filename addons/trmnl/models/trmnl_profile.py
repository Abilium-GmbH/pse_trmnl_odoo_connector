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
from datetime import timedelta
from urllib.parse import urlencode, urlparse

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.addons.trmnl.lib.net import (
    INTERNAL_HOST_RE as _INTERNAL_HOST_RE,
    client_can_reach_host,
    is_device_reachable_base_url,
)

_logger = logging.getLogger(__name__)

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
        string="Graph Group By",
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
    ], string="Line Date Group By", default="month", required=True)
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
        string="Preview Display",
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
        related="device_id.last_poll_at",
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

    @api.depends("device_id.last_poll_at", "device_id.desired_refresh_rate")
    def _compute_device_next_expected_poll_at(self):
        for rec in self:
            last = rec.device_id.last_poll_at
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
            query = rec._build_profile_image_query(version=version or None)
            path_suffix = f"?{query}" if query else ""
            # Same endpoint the device downloads — avoids /web/image processing
            # or cache differences vs /api/profile/image/<id>.
            # Backend form preview: no access_token in URL; controller allows
            # authenticated Settings users without a device token.
            url = f"/api/profile/image/{rec.id}{path_suffix}"
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
            params = rec.env["ir.config_parameter"].sudo()
            if params.get_param("trmnl.public_base_url", "").strip():
                rec.url_warning = ""
                continue
            web_url = params.get_param("web.base.url", "").strip()
            if not is_device_reachable_base_url(web_url):
                rec.url_warning = (
                    f"Image URL cannot be generated: web.base.url ({web_url}) is a "
                    f"loopback/internal address that physical devices cannot reach. "
                    f"Set trmnl.public_base_url in Settings → Technical → System Parameters "
                    f"to the URL your devices use to reach this Odoo instance."
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
            if not is_device_reachable_base_url(base):
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

        # Reverse-proxy / HttpCase: client appears as loopback while the device
        # reaches Odoo via a configured LAN base URL.
        if client_ip in ("127.0.0.1", "::1") or _INTERNAL_HOST_RE.match(client_ip or ""):
            for source, base in candidates:
                if is_device_reachable_base_url(base):
                    return base, source

        # No client context (unit tests, cron): first reachable configured URL.
        if not client_ip:
            for source, base in candidates:
                if is_device_reachable_base_url(base):
                    return base, source

        # Last resort: honour an admin-configured, device-reachable base URL even
        # when the poll client_ip appears to be on a different subnet than its
        # host.  This happens with Docker port publishing, where the container
        # sees the bridge gateway (e.g. 172.17.0.1) as remote_addr instead of the
        # device's real LAN IP, so the /24 subnet heuristic above rejects an
        # otherwise correct web.base.url / trmnl.public_base_url.  An explicitly
        # configured reachable URL is preferable to serving a stale image forever.
        # The poll Host header is excluded here since it is the only candidate the
        # admin did not vet.
        for source, base in candidates:
            if source != "poll" and is_device_reachable_base_url(base):
                return base, source

        return False, None

    def _build_profile_image_query(self, *, version=None):
        """Build query string for ``/api/profile/image`` (cache bust + device token)."""
        params = {}
        if version:
            params["v"] = version
        try:
            from odoo.http import request as http_request
            access_token = (http_request.httprequest.environ.get("trmnl.access_token") or "").strip()
        except RuntimeError:
            # Outside an HTTP request context (cron, tests, manual render).
            access_token = ""
        if access_token:
            params["access_token"] = access_token
        return urlencode(params) if params else ""

    def _get_display_image_url(self):
        """Return a device-reachable URL for this profile's preview PNG, or False.

        Base URL resolution is delegated to :meth:`_resolve_device_base_url`.
        The URL includes a ``?v=<png-hash>`` query so TRMNL firmware that caches
        by URL (not only by filename) still re-downloads after a re-render.
        Device polls also append ``access_token`` so the PNG endpoint is not
        anonymously enumerable.
        """
        if not self.preview_image:
            return False

        digest = self._preview_png_digest()
        query = self._build_profile_image_query(version=digest)
        path_suffix = f"?{query}" if query else ""

        base, source = self._resolve_device_base_url()
        if base:
            url = f"{base}/api/profile/image/{self.id}{path_suffix}"
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
