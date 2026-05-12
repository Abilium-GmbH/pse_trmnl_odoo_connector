from __future__ import annotations

import base64
import hashlib
import io
import logging
from calendar import monthrange
from datetime import date, timedelta, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .trmnl_device import _INTERNAL_HOST_RE

_logger = logging.getLogger(__name__)

# Priority-ordered list of date/datetime fields used by filter_preset and sort_preset=date.
# create_date is the guaranteed fallback — it exists on every Odoo model.
_FILTER_DATE_FIELDS = ["date_deadline", "date_order", "start", "date", "create_date"]

# Priority-ordered list of amount fields used by sort_preset=amount.
_SORT_AMOUNT_FIELDS = ["amount_total", "expected_revenue", "planned_revenue"]

# Maps Odoo module name → res_models allowed for the action picker for that app.
# First model is the default primary when no app-specific display mode applies.
_APP_ALLOWED_MODELS = {
    "calendar":      ["calendar.event"],
    "project":       ["project.project", "project.task"],
    "project_todo":  ["project.task"],
    "crm":           ["crm.lead"],
    "point_of_sale": ["pos.order"],
    "mail":          ["mail.activity"],
}

# Back-compat: primary model per app (first entry of _APP_ALLOWED_MODELS).
_APP_MODELS = {k: v[0] for k, v in _APP_ALLOWED_MODELS.items()}


# App-specific display presets (keys match Selection values on trmnl.profile).
# Applied after picking a matching ir.actions.act_window for ``res_model``.
# ``read_group_field``: when set, list/table data is built via read_group on that field.
# ``pos_dashboard``: aggregate pos.order rows for a simple KPI-style list.
# ``crm_calendar``: use month calendar renderer with crm.lead date_deadline.
_APP_DISPLAY_PRESETS = {
    # --- Project ---
    "project_projects_overview": {
        "res_model": "project.project",
        "layout": "list",
        "fields": ["name", "partner_id", "user_id", "date_start", "task_count"],
        "order": "sequence, name",
        "limit": 20,
        "filter_preset": "my_records",
        "sort_preset": "name",
        "prefer_action_view": "kanban",
    },
    "project_tasks_detail": {
        "res_model": "project.task",
        "layout": "list",
        "fields": ["name", "project_id", "stage_id", "date_deadline", "priority", "user_id"],
        "order": "priority desc, date_deadline asc",
        "limit": 20,
        "filter_preset": "none",
        "sort_preset": "priority",
        "prefer_action_view": "kanban",
    },
    # --- To-Do (project_todo) ---
    "todo_list": {
        "res_model": "project.task",
        "layout": "list",
        "fields": ["name", "project_id", "date_deadline", "priority", "user_id"],
        "order": "date_deadline asc, priority desc",
        "limit": 25,
        "filter_preset": "today",
        "sort_preset": "date",
        "prefer_action_view": "tree",
    },
    "todo_kanban_style": {
        "res_model": "project.task",
        "layout": "kanban",
        "fields": ["name", "stage_id", "date_deadline", "priority"],
        "order": "stage_id, priority desc",
        "limit": 30,
        "filter_preset": "none",
        "sort_preset": "priority",
        "prefer_action_view": "kanban",
    },
    # --- CRM ---
    "crm_pipeline": {
        "res_model": "crm.lead",
        "layout": "list",
        "fields": ["name", "partner_id", "stage_id", "expected_revenue", "probability"],
        "order": "stage_id, expected_revenue desc",
        "limit": 15,
        "filter_preset": "none",
        "sort_preset": "amount",
        "read_group_field": "stage_id",
        "prefer_action_view": "kanban",
    },
    "crm_list": {
        "res_model": "crm.lead",
        "layout": "table",
        "fields": ["name", "partner_id", "email_from", "phone", "stage_id", "expected_revenue", "date_deadline"],
        "order": "create_date desc",
        "limit": 15,
        "filter_preset": "none",
        "sort_preset": "default",
        "prefer_action_view": "tree",
    },
    "crm_calendar": {
        "res_model": "crm.lead",
        "layout": "calendar",
        "fields": ["name", "date_deadline", "expected_revenue", "stage_id"],
        "order": "date_deadline asc",
        "limit": 200,
        "filter_preset": "this_month",
        "sort_preset": "date",
        "calendar_view_mode": "month",
        "calendar_reference_mode": "today",
        "crm_calendar": True,
        "prefer_action_view": "calendar",
    },
    # --- Point of Sale ---
    "pos_dashboard": {
        "res_model": "pos.order",
        "layout": "list",
        "fields": ["name", "date_order", "amount_total", "state"],
        "order": "date_order desc",
        "limit": 1,
        "filter_preset": "today",
        "sort_preset": "default",
        "pos_dashboard": True,
        "prefer_action_view": "tree",
    },
    "pos_orders": {
        "res_model": "pos.order",
        "layout": "table",
        "fields": ["name", "date_order", "partner_id", "amount_total", "state"],
        "order": "date_order desc",
        "limit": 15,
        "filter_preset": "today",
        "sort_preset": "default",
        "prefer_action_view": "tree",
    },
}

_APP_DEFAULT_DISPLAY_MODE = {
    "project": "project_projects_overview",
    "project_todo": "todo_list",
    "crm": "crm_pipeline",
    "point_of_sale": "pos_dashboard",
}

# Presets prefill layout/fields/order/limit when a known model is selected.
# Users can edit all values afterwards. Fields are validated against
# ir.model.fields at apply time so missing optional modules are silently skipped.
_MODEL_PRESETS = {
    "calendar.event": {
        "layout": "calendar",
        "fields": ["name", "start", "stop", "location", "user_id"],
        "order": "start asc",
        "limit": 200,
        "filter_preset": "this_month",
        "sort_preset": "date",
        "calendar_view_mode": "month",
        "calendar_reference_mode": "today",
    },
    "project.task": {
        "layout": "list",
        "fields": ["name", "project_id", "stage_id", "date_deadline", "priority"],
        "order": "priority desc, date_deadline asc",
        "limit": 15,
    },
    "project.project": {
        "layout": "list",
        "fields": ["name", "partner_id", "user_id", "date_start", "task_count"],
        "order": "sequence, name",
        "limit": 20,
    },
    "mail.activity": {
        "layout": "list",
        "fields": ["summary", "activity_type_id", "date_deadline", "user_id", "res_model"],
        "order": "date_deadline asc",
        "limit": 15,
    },
    "crm.lead": {
        "layout": "list",
        "fields": ["name", "partner_id", "contact_name", "email_from", "phone", "stage_id", "expected_revenue", "priority"],
        "order": "expected_revenue desc",
        "limit": 10,
    },
    "pos.order": {
        "layout": "table",
        "fields": ["name", "date_order", "partner_id", "amount_total", "state"],
        "order": "date_order desc",
        "limit": 10,
    },
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

    app_module_id = fields.Many2one(
        "ir.module.module",
        string="Odoo App",
        domain=[("state", "=", "installed")],
    )

    odoo_action_id = fields.Many2one(
        "ir.actions.act_window",
        string="Data View",
    )

    app_model_id = fields.Many2one(
        "ir.model",
        string="Odoo Model",
        readonly=True,
    )

    trmnl_layout = fields.Selection(
        [
            ("list", "List"),
            ("table", "Table"),
            ("calendar", "Calendar"),
            ("kanban", "Kanban / Grid"),
            ("kpi", "KPI"),
        ],
        string="Layout",
        default="list",
        required=True,
    )

    display_field_ids = fields.Many2many(
        "ir.model.fields",
        "trmnl_profile_ir_model_fields_rel",
        "profile_id",
        "field_id",
        string="Display Fields",
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

    sort_preset = fields.Selection([
        ("default",  "Default (use Display Order)"),
        ("name",     "Name"),
        ("date",     "Date"),
        ("priority", "Priority"),
        ("amount",   "Amount"),
        ("sequence", "Sequence"),
    ], string="Sort", default="default", required=True)

    calendar_view_mode = fields.Selection([
        ("month", "Month"),
        ("week",  "Week"),
    ], string="Calendar View", default="month", required=True)

    calendar_week_mode = fields.Selection([
        ("work_week", "Work Week (Mon–Fri)"),
        ("full_week", "Full Week (Mon–Sun)"),
    ], string="Week Mode", default="work_week", required=True)

    calendar_reference_mode = fields.Selection([
        ("today",  "Current Month"),
        ("custom", "Custom Date"),
    ], string="Reference", default="today", required=True)

    calendar_reference_date = fields.Date(string="Reference Date")

    preview_image = fields.Binary(string="Preview", readonly=True)
    preview_generated_at = fields.Datetime(string="Preview Generated At", readonly=True)

    auto_refresh_enabled = fields.Boolean(
        string="Auto Refresh",
        default=True,
        help=(
            "When enabled, the preview is automatically re-rendered during device polls "
            "if it is older than the configured interval."
        ),
    )
    auto_refresh_interval_minutes = fields.Integer(
        string="Auto Refresh Interval (min)",
        default=10,
        help="How many minutes between automatic re-renders. Minimum effective value is 1.",
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

    # App-specific display modes (only one is relevant per app_module_id).
    project_display_mode = fields.Selection(
        [
            ("project_projects_overview", "Projects Overview"),
            ("project_tasks_detail", "Tasks Detail"),
        ],
        string="Project display",
        help="Preset for the Project app. Leave empty to keep manual Data View configuration.",
    )
    todo_display_mode = fields.Selection(
        [
            ("todo_list", "List"),
            ("todo_kanban_style", "Kanban-style"),
        ],
        string="To-Do display",
        help="Preset for the To-Do app (project_todo).",
    )
    crm_display_mode = fields.Selection(
        [
            ("crm_pipeline", "Pipeline"),
            ("crm_list", "List"),
            ("crm_calendar", "Calendar"),
        ],
        string="CRM display",
        help="Preset for the CRM app.",
    )
    pos_display_mode = fields.Selection(
        [
            ("pos_dashboard", "Dashboard"),
            ("pos_orders", "Orders"),
        ],
        string="Point of Sale display",
        help="Preset for the Point of Sale app.",
    )
    trmnl_read_group_field_name = fields.Char(
        string="Internal aggregate field",
        help="Technical name of the field used for pipeline-style read_group rows.",
    )

    # ------------------------------------------------------------------
    # onchange
    # ------------------------------------------------------------------

    def _layout_from_view_mode(self, view_mode):
        modes = {m.strip() for m in (view_mode or "").split(",")}
        if "calendar" in modes:
            return "calendar"
        if "kanban" in modes:
            return "kanban"
        if modes & {"graph", "pivot"}:
            return "kpi"
        return "list"

    def _clear_app_display_mode_selections(self):
        """Clear app-specific display mode fields (manual Data View pick)."""
        self.project_display_mode = False
        self.todo_display_mode = False
        self.crm_display_mode = False
        self.pos_display_mode = False

    def _active_display_preset_key(self):
        """Return the active ``_APP_DISPLAY_PRESETS`` key for the current app, if any."""
        self.ensure_one()
        if not self.app_module_id:
            return False
        mod = self.app_module_id.name
        if mod == "project":
            return self.project_display_mode or False
        if mod == "project_todo":
            return self.todo_display_mode or False
        if mod == "crm":
            return self.crm_display_mode or False
        if mod == "point_of_sale":
            return self.pos_display_mode or False
        return False

    def _pick_action_window_for_model(self, module_name, res_model, prefer_view_contains=None):
        """Pick a sensible ``ir.actions.act_window`` for ``res_model`` declared in ``module_name``."""
        Act = self.env["ir.actions.act_window"].sudo()
        imd = self.env["ir.model.data"].sudo().search([
            ("module", "=", module_name),
            ("model", "=", "ir.actions.act_window"),
        ])
        actions = Act.browse(imd.mapped("res_id")).exists().filtered(lambda a: a.res_model == res_model)
        if not actions:
            actions = Act.search([("res_model", "=", res_model)], limit=8, order="id")
        if not actions:
            return Act.browse()
        tokens = []
        if prefer_view_contains:
            tokens = [prefer_view_contains] if isinstance(prefer_view_contains, str) else list(prefer_view_contains)
        for token in tokens:
            if not token:
                continue
            hit = actions.filtered(lambda a, t=token: a.view_mode and t in a.view_mode)
            if hit:
                return hit[0]
        return actions[0]

    def _apply_app_display_preset_from_mode(self):
        """Apply ``_APP_DISPLAY_PRESETS`` for the active app display mode field.

        Returns True when a preset was applied, False otherwise.
        """
        key = self._active_display_preset_key()
        self.trmnl_read_group_field_name = False
        if not key or not self.app_module_id:
            return False
        preset = _APP_DISPLAY_PRESETS.get(key)
        if not preset:
            return False
        res_model = preset.get("res_model")
        if not res_model or res_model not in self.env:
            return False

        module_name = self.app_module_id.name
        action = self._pick_action_window_for_model(
            module_name,
            res_model,
            preset.get("prefer_action_view"),
        )
        if action:
            self.odoo_action_id = action

        model = self.env["ir.model"].sudo().search([("model", "=", res_model)], limit=1)
        self.app_model_id = model

        field_names = preset.get("fields") or []
        valid_fields = self.env["ir.model.fields"].sudo().search([
            ("model", "=", res_model),
            ("name", "in", field_names),
        ])
        order_map = {n: i for i, n in enumerate(field_names)}
        self.display_field_ids = valid_fields.sorted(lambda f, om=order_map: om.get(f.name, 99))

        self.trmnl_layout = preset["layout"]
        self.display_limit = preset.get("limit", 20)
        self.display_order = preset.get("order", "id desc")
        self.filter_preset = preset.get("filter_preset", "none")
        self.sort_preset = preset.get("sort_preset", "default")
        if "calendar_view_mode" in preset:
            self.calendar_view_mode = preset["calendar_view_mode"]
        if "calendar_reference_mode" in preset:
            self.calendar_reference_mode = preset["calendar_reference_mode"]
        if preset.get("read_group_field"):
            fname = preset["read_group_field"]
            if self.env["ir.model.fields"].sudo().search_count([
                ("model", "=", res_model),
                ("name", "=", fname),
            ]):
                self.trmnl_read_group_field_name = fname
        return True

    @api.onchange("app_module_id")
    def _onchange_app_module_id(self):
        self.odoo_action_id = False
        self.app_model_id = False
        self.display_field_ids = False
        self.trmnl_read_group_field_name = False
        self._clear_app_display_mode_selections()

        if not self.app_module_id:
            return {"domain": {"odoo_action_id": [("id", "=", False)]}}

        imd = self.env["ir.model.data"].sudo().search([
            ("module", "=", self.app_module_id.name),
            ("model", "=", "ir.actions.act_window"),
        ])

        actions = self.env["ir.actions.act_window"].sudo().browse(
            imd.mapped("res_id")
        ).exists()

        allowed = _APP_ALLOWED_MODELS.get(self.app_module_id.name)
        if allowed:
            actions = actions.filtered(lambda a: a.res_model in allowed)

        mod_name = self.app_module_id.name
        if mod_name in _APP_DEFAULT_DISPLAY_MODE:
            default_key = _APP_DEFAULT_DISPLAY_MODE[mod_name]
            if mod_name == "project":
                self.project_display_mode = default_key
            elif mod_name == "project_todo":
                self.todo_display_mode = default_key
            elif mod_name == "crm":
                self.crm_display_mode = default_key
            elif mod_name == "point_of_sale":
                self.pos_display_mode = default_key
            self._apply_app_display_preset_from_mode()
            return {"domain": {"odoo_action_id": [("id", "in", actions.ids)]}}

        # Calendar, Mail, … — preserve legacy auto-pick behaviour.
        if actions:
            preferred = actions.filtered(lambda a: "calendar" in (a.view_mode or ""))
            self.odoo_action_id = preferred[0] if preferred else actions[0]
            self._onchange_odoo_action_id()

        return {"domain": {"odoo_action_id": [("id", "in", actions.ids)]}}

    @api.onchange(
        "project_display_mode",
        "todo_display_mode",
        "crm_display_mode",
        "pos_display_mode",
    )
    def _onchange_app_specific_display_modes(self):
        if self.app_module_id and self.app_module_id.name in _APP_DEFAULT_DISPLAY_MODE:
            self._apply_app_display_preset_from_mode()

    @api.onchange("odoo_action_id")
    def _onchange_odoo_action_id(self):
        self._clear_app_display_mode_selections()
        self.trmnl_read_group_field_name = False
        if not self.odoo_action_id or not self.odoo_action_id.res_model:
            self.app_model_id = False
            self.display_field_ids = False
            return

        model_name = self.odoo_action_id.res_model
        model = self.env["ir.model"].sudo().search(
            [("model", "=", model_name)],
            limit=1,
        )
        self.app_model_id = model
        self.display_field_ids = False

        if not self._apply_model_preset(model_name):
            self.trmnl_layout = self._layout_from_view_mode(
                self.odoo_action_id.view_mode
            )

    def _apply_model_preset(self, model_name):
        """Prefill layout/fields/order/limit from _MODEL_PRESETS if a preset exists.

        Returns True if a preset was applied, False if the model is unknown.
        Fields are validated against ir.model.fields so that optional modules
        that did not install a field are silently skipped.
        """
        preset = _MODEL_PRESETS.get(model_name)
        if not preset:
            return False

        valid_fields = self.env["ir.model.fields"].sudo().search([
            ("model", "=", model_name),
            ("name", "in", preset["fields"]),
        ])

        self.trmnl_layout = preset["layout"]
        self.display_field_ids = valid_fields
        self.display_limit = preset["limit"]
        self.display_order = preset["order"]
        if "filter_preset" in preset:
            self.filter_preset = preset["filter_preset"]
        if "sort_preset" in preset:
            self.sort_preset = preset["sort_preset"]
        if "calendar_view_mode" in preset:
            self.calendar_view_mode = preset["calendar_view_mode"]
        if "calendar_reference_mode" in preset:
            self.calendar_reference_mode = preset["calendar_reference_mode"]
        return True

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

    def _detect_date_field(self, model_name):
        """Return the first available date/datetime field name for this model, or None."""
        existing = set(
            self.env["ir.model.fields"].sudo().search([
                ("model", "=", model_name),
                ("name", "in", _FILTER_DATE_FIELDS),
            ]).mapped("name")
        )
        return next((f for f in _FILTER_DATE_FIELDS if f in existing), None)

    def _build_sort_order(self, model_name):
        """Return an ORDER BY string for the active sort_preset, or None.

        Returns None when sort_preset is 'default' or when the required field
        is absent, so the caller falls back to display_order.
        """
        if self.sort_preset == "default":
            return None

        def field_exists(name):
            return bool(self.env["ir.model.fields"].sudo().search_count([
                ("model", "=", model_name),
                ("name", "=", name),
            ]))

        if self.sort_preset == "name":
            rec_name = self.env[model_name]._rec_name or "name"
            return f"{rec_name} asc" if field_exists(rec_name) else None

        if self.sort_preset == "date":
            date_field = self._detect_date_field(model_name)
            return f"{date_field} asc" if date_field else None

        if self.sort_preset == "priority":
            return "priority desc" if field_exists("priority") else None

        if self.sort_preset == "amount":
            existing = set(
                self.env["ir.model.fields"].sudo().search([
                    ("model", "=", model_name),
                    ("name", "in", _SORT_AMOUNT_FIELDS),
                ]).mapped("name")
            )
            amount_field = next((f for f in _SORT_AMOUNT_FIELDS if f in existing), None)
            return f"{amount_field} desc" if amount_field else None

        if self.sort_preset == "sequence":
            return "sequence asc" if field_exists("sequence") else None

        return None

    # ------------------------------------------------------------------
    # renderer dispatch
    # ------------------------------------------------------------------

    def _prepare_calendar_data(self, records) -> list[dict]:
        """Extract plain event dicts from calendar.event ORM records.

        All ORM access is isolated here so the renderer stays import-free.
        Times are in the server timezone (UTC); no conversion for now.
        """
        events = []
        for rec in records:
            try:
                start = rec.start
                if not start:
                    continue
                start_date = start.date() if hasattr(start, "date") and callable(start.date) else start
                time_str = start.strftime("%H:%M") if hasattr(start, "hour") else ""
                events.append({
                    "title":    rec.display_name or "",
                    "start":    start_date,
                    "time_str": time_str,
                })
            except Exception:
                pass
        return events

    def _prepare_calendar_week_data(self, records) -> list[dict]:
        """Extract timed event dicts from calendar.event ORM records for week view.

        All-day events are excluded. Missing stop defaults to start + 1 hour.
        Times are in server timezone (UTC); no conversion applied.
        """
        events = []
        for rec in records:
            try:
                start = rec.start
                if not start:
                    continue
                if getattr(rec, "allday", False):
                    continue
                stop = rec.stop or (start + timedelta(hours=1))
                events.append({
                    "title":          rec.display_name or "",
                    "start_datetime": start,
                    "end_datetime":   stop,
                })
            except Exception:
                pass
        return events

    def _resolve_calendar_date(self) -> tuple[int, int]:
        """Return (year, month) for month view based on reference settings."""
        if self.calendar_reference_mode == "custom" and self.calendar_reference_date:
            ref = self.calendar_reference_date
            return ref.year, ref.month
        today = date.today()
        return today.year, today.month

    def _resolve_calendar_week_start(self) -> date:
        """Return the Monday of the target week based on reference settings."""
        if self.calendar_reference_mode == "custom" and self.calendar_reference_date:
            ref = self.calendar_reference_date
            return ref - timedelta(days=ref.weekday())
        today = date.today()
        return today - timedelta(days=today.weekday())

    def _load_calendar_records(self, year: int, month: int):
        """Load calendar.event records for the displayed month.

        Bypasses filter_preset date ranges (the month window overrides them)
        but still respects my_records so personal calendars work correctly.
        """
        _, last_day = monthrange(year, month)
        month_start = date(year, month, 1)
        month_end   = date(year, month, last_day)
        domain = [("start", ">=", month_start), ("start", "<=", month_end)]

        if self.filter_preset == "my_records":
            domain.append(("user_id", "=", self.env.uid))

        limit = self.display_limit or 200
        return self.env["calendar.event"].sudo().search(
            domain, limit=limit, order="start asc"
        )

    def _load_calendar_week_records(self, week_start: date):
        """Load calendar.event records for the full Mon–Sun week window.

        Always loads the full 7 days regardless of week_mode so the renderer
        can decide which columns to draw. Respects my_records filter.
        """
        week_end = week_start + timedelta(days=6)
        domain = [("start", ">=", week_start), ("start", "<=", week_end)]
        if self.filter_preset == "my_records":
            domain.append(("user_id", "=", self.env.uid))
        limit = self.display_limit or 200
        return self.env["calendar.event"].sudo().search(
            domain, limit=limit, order="start asc"
        )

    def _load_crm_lead_calendar_month(self, year: int, month: int):
        """Load crm.lead records whose deadline falls in the given calendar month."""
        Lead = self.env["crm.lead"].sudo()
        if "date_deadline" not in Lead._fields:
            return Lead.browse()
        _, last_day = monthrange(year, month)
        month_start = date(year, month, 1)
        month_end = date(year, month, last_day)
        domain = [
            ("date_deadline", ">=", month_start),
            ("date_deadline", "<=", month_end),
        ]
        domain += self._build_filter_domain("crm.lead")
        limit = self.display_limit or 200
        try:
            return Lead.search(domain, limit=limit, order="date_deadline asc")
        except Exception:
            return Lead.browse()

    def _prepare_crm_lead_calendar_events(self, records) -> list[dict]:
        """Map ``crm.lead`` records to month-calendar event dicts (date_deadline as day)."""
        events = []
        for rec in records:
            try:
                day = rec.date_deadline
                if not day:
                    continue
                if hasattr(day, "date"):
                    day = day.date()
                title = rec.display_name or rec.name or ""
                events.append({
                    "title":    title,
                    "start":    day,
                    "time_str": "",
                })
            except Exception:
                pass
        return events

    @staticmethod
    def _read_group_line_count(line: dict, group_field: str) -> int:
        for key in (f"{group_field}_count", "__count", "id_count"):
            val = line.get(key)
            if isinstance(val, int):
                return val
        return 0

    def _build_trmnl_read_group_rows(self, model_name: str, group_field: str):
        """Build (rows, headers) for a simple read_group summary table."""
        if model_name not in self.env or not group_field:
            return None
        Model = self.env[model_name].sudo()
        if group_field not in Model._fields:
            return None
        domain = self._build_filter_domain(model_name)
        limit = self.display_limit or 30
        gb = group_field.split(":")[0]
        fields_spec = ["id"]
        if "expected_revenue" in Model._fields:
            fields_spec.insert(0, "expected_revenue")
        try:
            lines = Model.read_group(domain, fields_spec, [gb], limit=limit, lazy=False)
        except Exception as exc:
            _logger.debug("TRMNL read_group failed for %s: %s", model_name, exc)
            return None
        rows = []
        for line in lines:
            label = line.get(gb)
            if isinstance(label, tuple):
                label = label[1] or str(label[0])
            elif label is False:
                label = _("Undefined")
            cnt = self._read_group_line_count(line, gb)
            row = [str(label or ""), str(int(cnt))]
            if "expected_revenue" in Model._fields:
                rev = line.get("expected_revenue")
                if rev is None:
                    rev = 0.0
                row.append(f"{float(rev):.2f}")
            rows.append(row)
        headers = [_("Group"), _("Count")]
        if "expected_revenue" in Model._fields:
            headers.append(_("Expected revenue"))
        return rows, headers

    def _build_pos_order_dashboard_rows(self):
        """Derive simple dashboard rows from ``pos.order`` read_group by state."""
        if "pos.order" not in self.env:
            return [[_("Point of Sale is not installed.")]], [_("Message")]
        Order = self.env["pos.order"].sudo()
        domain = self._build_filter_domain("pos.order")
        try:
            lines = Order.read_group(
                domain, ["amount_total", "id"], ["state"], limit=30, lazy=False,
            )
        except Exception as exc:
            _logger.debug("TRMNL POS dashboard read_group failed: %s", exc)
            return [[_("Could not aggregate orders")]], [_("Error")]
        rows = []
        for line in lines:
            label = line.get("state")
            if isinstance(label, tuple):
                label = label[1] or str(label[0])
            elif label is False:
                label = _("Unknown")
            cnt = self._read_group_line_count(line, "state")
            amt = line.get("amount_total") or 0.0
            rows.append([str(label or ""), str(int(cnt)), f"{float(amt):.2f}"])
        return rows, [_("State"), _("Orders"), _("Amount total")]

    def _dispatch_renderer(self, model_name, field_names, field_labels, records) -> bytes:
        """Route to the correct renderer; fall back to generic list on any failure."""
        if self.trmnl_layout == "calendar" and model_name == "calendar.event":
            try:
                if self.calendar_view_mode == "week":
                    week_start = self._resolve_calendar_week_start()
                    week_events = self._prepare_calendar_week_data(
                        self._load_calendar_week_records(week_start)
                    )
                    from odoo.addons.trmnl.trmnl_calendar_week_preview import (
                        render_calendar_week_preview,
                    )
                    return render_calendar_week_preview(
                        week_events, week_start, self.calendar_week_mode
                    )
                else:
                    year, month = self._resolve_calendar_date()
                    events = self._prepare_calendar_data(
                        self._load_calendar_records(year, month)
                    )
                    from odoo.addons.trmnl.trmnl_calendar_preview import render_calendar_preview
                    return render_calendar_preview(events, year, month)
            except UserError:
                raise
            except Exception as exc:
                _logger.warning(
                    "TRMNL calendar renderer failed for profile id=%s — falling back to list: %s",
                    self.id, exc, exc_info=True,
                )

        if (
            self.trmnl_layout == "calendar"
            and model_name == "crm.lead"
            and self.crm_display_mode == "crm_calendar"
        ):
            try:
                year, month = self._resolve_calendar_date()
                events = self._prepare_crm_lead_calendar_events(
                    self._load_crm_lead_calendar_month(year, month)
                )
                from odoo.addons.trmnl.trmnl_calendar_preview import render_calendar_preview
                return render_calendar_preview(events, year, month)
            except UserError:
                raise
            except Exception as exc:
                _logger.warning(
                    "TRMNL CRM calendar renderer failed for profile id=%s — falling back to list: %s",
                    self.id, exc, exc_info=True,
                )

        rows = [
            [self._extract_field_value(rec, fname) for fname in field_names]
            for rec in records
        ]
        from odoo.addons.trmnl.trmnl_preview import render_list_preview
        return render_list_preview(rows, field_labels)

    # ------------------------------------------------------------------
    # display footer (reserved bottom strip on 800×480)
    # ------------------------------------------------------------------

    @staticmethod
    def _format_poll_timestamp(device_label, poll_at):
        """Return the footer label string in Europe/Zurich local time."""
        zurich = ZoneInfo("Europe/Zurich")
        local_dt = poll_at.replace(tzinfo=timezone.utc).astimezone(zurich)
        return f"{device_label} · Last poll: {local_dt.strftime('%Y-%m-%d %H:%M')}"

    def _get_footer_device_label(self):
        """Human-readable device label for the footer.

        Priority: admin ``device_name`` (device "name" in the UI), then
        ``friendly_id``, then ``mac_address``.
        """
        self.ensure_one()
        device = self.device_id
        name = (device.device_name or "").strip()
        if name:
            return name
        if device.friendly_id:
            return device.friendly_id
        return device.mac_address or "TRMNL"

    def _finalize_display_image(self, png_bytes):
        """Paste content-sized PNG onto 800×480 and draw the poll footer strip.

        Layout renderers produce ``(DISPLAY_WIDTH, CONTENT_HEIGHT)`` bytes. This
        method composites them into a full TRMNL frame with a separator line and
        optional centered poll metadata in the footer band.
        """
        self.ensure_one()
        from odoo.addons.trmnl.trmnl_display_canvas import (
            CONTENT_HEIGHT,
            DISPLAY_HEIGHT,
            DISPLAY_WIDTH,
            FOOTER_BAND_FILL,
            FOOTER_SEPARATOR_GRAY,
            SEPARATOR_Y,
            draw_poll_footer_strip,
        )

        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            return png_bytes

        try:
            content = Image.open(io.BytesIO(png_bytes)).convert("L")
        except Exception:
            _logger.debug(
                "TRMNL profile id=%s: invalid content PNG for finalize", self.id, exc_info=True
            )
            return png_bytes

        cw, ch = content.size
        if cw != DISPLAY_WIDTH:
            _logger.debug(
                "TRMNL profile id=%s: unexpected content width %s (expected %s)",
                self.id, cw, DISPLAY_WIDTH,
            )
            return png_bytes
        if ch == DISPLAY_HEIGHT:
            content = content.crop((0, 0, DISPLAY_WIDTH, CONTENT_HEIGHT))
            ch = CONTENT_HEIGHT
        elif ch != CONTENT_HEIGHT:
            _logger.debug(
                "TRMNL profile id=%s: unexpected content height %s (expected %s)",
                self.id, ch, CONTENT_HEIGHT,
            )
            return png_bytes

        out = Image.new("L", (DISPLAY_WIDTH, DISPLAY_HEIGHT), 255)
        out.paste(content, (0, 0))
        draw = ImageDraw.Draw(out)

        poll_at = self.device_id.last_poll_at
        label = None
        font = None
        if poll_at:
            for path in (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            ):
                try:
                    font = ImageFont.truetype(path, 11)
                    break
                except (OSError, IOError):
                    continue
            if font is None:
                font = ImageFont.load_default()

            label = self._format_poll_timestamp(self._get_footer_device_label(), poll_at)
            margin_h = 8
            max_text_w = DISPLAY_WIDTH - 2 * margin_h

            def _text_w(txt):
                try:
                    return int(draw.textlength(txt, font=font))
                except AttributeError:
                    return draw.textsize(txt, font=font)[0]

            while len(label) > 8 and _text_w(label + "…") > max_text_w:
                label = label[:-1]
            if _text_w(label) > max_text_w:
                label = (label[: max(4, len(label) - 4)] + "…") if label else ""

        try:
            draw_poll_footer_strip(draw, label=label, font=font)
            buf = io.BytesIO()
            out.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as exc:
            _logger.warning(
                "TRMNL profile id=%s: finalize footer/save failed (%s) — "
                "returning full frame with content + empty footer band",
                self.id,
                exc,
                exc_info=True,
            )
            out2 = Image.new("L", (DISPLAY_WIDTH, DISPLAY_HEIGHT), 255)
            out2.paste(content, (0, 0))
            d2 = ImageDraw.Draw(out2)
            d2.line(
                [(0, SEPARATOR_Y), (DISPLAY_WIDTH - 1, SEPARATOR_Y)],
                fill=FOOTER_SEPARATOR_GRAY,
                width=1,
            )
            d2.rectangle(
                [0, SEPARATOR_Y + 1, DISPLAY_WIDTH - 1, DISPLAY_HEIGHT - 1],
                fill=FOOTER_BAND_FILL,
            )
            buf2 = io.BytesIO()
            out2.save(buf2, format="PNG")
            return buf2.getvalue()

    # ------------------------------------------------------------------
    # computed delivery-status fields
    # ------------------------------------------------------------------

    @staticmethod
    def _is_publicly_reachable_base_url(url):
        """Return True if url's host is not a localhost/internal/bridge address."""
        try:
            host = urlparse(url).hostname or ""
            return bool(host) and not _INTERNAL_HOST_RE.match(host)
        except Exception:
            return False

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
            if not rec._is_publicly_reachable_base_url(web_url):
                rec.url_warning = (
                    f"trmnl.public_base_url is not set and web.base.url ({web_url}) "
                    f"is an internal address unreachable by physical devices. "
                    f"Go to Settings → Technical → Parameters → System Parameters "
                    f"and set trmnl.public_base_url to your LAN IP "
                    f"(e.g. http://192.168.1.127:8069)."
                )
            else:
                rec.url_warning = ""

    # ------------------------------------------------------------------
    # refresh-rate actions
    # ------------------------------------------------------------------

    def action_set_fast_refresh(self):
        self.ensure_one()
        self.device_id.write({"desired_refresh_rate": 60})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Fast Refresh Enabled"),
                "message": _(
                    "Device refresh rate set to 60 seconds. "
                    "The device will apply this on its next poll."
                ),
                "type": "info",
                "sticky": False,
            },
        }

    def action_restore_refresh(self):
        self.ensure_one()
        self.device_id.write({"desired_refresh_rate": 1800})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Refresh Restored"),
                "message": _("Device refresh rate restored to 30 minutes."),
                "type": "info",
                "sticky": False,
            },
        }

    # ------------------------------------------------------------------
    # preview rendering
    # ------------------------------------------------------------------

    def _is_auto_refresh_due(self):
        """Return True if the profile preview should be re-rendered now.

        False when auto-refresh is disabled.
        True when no preview has ever been generated (preview_generated_at is unset).
        Otherwise True when the time elapsed since the last render exceeds the interval.
        A zero or negative interval is treated as 10 minutes.
        """
        self.ensure_one()
        if not self.auto_refresh_enabled:
            _logger.debug("TRMNL auto-refresh: DISABLED for profile id=%s → False", self.id)
            return False
        if not self.preview_generated_at:
            _logger.debug("TRMNL auto-refresh: no preview_generated_at for profile id=%s → True", self.id)
            return True
        interval = self.auto_refresh_interval_minutes
        if not interval or interval <= 0:
            interval = 10
        threshold = self.preview_generated_at + timedelta(minutes=interval)
        now = fields.Datetime.now()
        due = now >= threshold
        _logger.debug(
            "TRMNL auto-refresh: profile id=%s generated_at=%s interval=%smin "
            "threshold=%s now=%s due=%s",
            self.id, self.preview_generated_at, interval, threshold, now, due,
        )
        return due

    def action_render_preview(self):
        self.ensure_one()
        if not self.odoo_action_id or not self.odoo_action_id.res_model:
            raise UserError(_("Select a Data View before rendering a preview."))
        self._render_and_store_preview()

        last_poll = self.device_id.last_display_at
        rate = self.device_id.desired_refresh_rate or 1800

        if last_poll:
            next_poll = last_poll + timedelta(seconds=rate)
            msg = (
                f"Preview updated. "
                f"Last poll: {last_poll.strftime('%Y-%m-%d %H:%M')} UTC · "
                f"Next expected poll: {next_poll.strftime('%Y-%m-%d %H:%M')} UTC."
            )
        else:
            msg = _(
                "Preview updated. "
                "The device has not polled yet — power-cycle it to trigger the first poll."
            )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Preview Updated"),
                "message": msg,
                "type": "success",
                "sticky": True,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def _render_and_store_preview(self):
        """Render the preview image and persist it. Raises on configuration errors."""
        self.ensure_one()

        model_name = self.odoo_action_id.res_model

        # Re-sync app_model_id if it was not populated (e.g. records pre-dating onchange).
        if not self.app_model_id:
            synced_model = self.env["ir.model"].sudo().search(
                [("model", "=", model_name)], limit=1
            )
            if synced_model:
                self.app_model_id = synced_model

        if model_name not in self.env:
            raise UserError(
                _("Model '%s' is not available in this environment.") % model_name
            )

        if self.display_field_ids:
            field_names = self.display_field_ids.mapped("name")
            field_labels = self.display_field_ids.mapped("field_description")
        else:
            field_names = ["display_name"]
            field_labels = [_("Name")]

        from odoo.addons.trmnl.trmnl_preview import render_list_preview

        png_bytes = None
        if self.pos_display_mode == "pos_dashboard" and model_name == "pos.order":
            rows, labels = self._build_pos_order_dashboard_rows()
            png_bytes = render_list_preview(rows, labels)
        elif self.trmnl_read_group_field_name:
            packed = self._build_trmnl_read_group_rows(model_name, self.trmnl_read_group_field_name)
            if packed:
                rows, labels = packed
                png_bytes = render_list_preview(rows, labels)

        if png_bytes is None:
            records = self._load_records(model_name, field_names)
            png_bytes = self._dispatch_renderer(model_name, field_names, field_labels, records)
        png_bytes = self._finalize_display_image(png_bytes)

        self.write({
            "preview_image": base64.b64encode(png_bytes),
            "preview_generated_at": fields.Datetime.now(),
        })

    def _get_display_image_url(self):
        """Return a device-reachable URL for this profile's preview PNG, or False.

        Resolution order:
        1. trmnl.public_base_url  — admin-set, always trusted, no validation.
        2. web.base.url           — used only when its host is not localhost /
                                    a Docker bridge / the libvirt KVM bridge.

        If neither yields a reachable URL a warning is logged and False is
        returned so the caller can fall back gracefully.
        """
        if not self.preview_image:
            return False

        params = self.env["ir.config_parameter"].sudo()

        public_url = params.get_param("trmnl.public_base_url", "").strip().rstrip("/")
        if public_url:
            url = f"{public_url}/api/profile/image/{self.id}"
            _logger.info("TRMNL profile id=%s image_url (trmnl.public_base_url): %s", self.id, url)
            return url

        web_url = params.get_param("web.base.url", "").strip().rstrip("/")
        if web_url and self._is_publicly_reachable_base_url(web_url):
            url = f"{web_url}/api/profile/image/{self.id}"
            _logger.info("TRMNL profile id=%s image_url (web.base.url): %s", self.id, url)
            return url

        _logger.warning(
            "TRMNL profile id=%s: cannot generate a reachable image URL — "
            "trmnl.public_base_url is not set and web.base.url=%r is a "
            "localhost/internal address. "
            "Set trmnl.public_base_url to your LAN IP in System Parameters "
            "(e.g. http://192.168.1.127:8069).",
            self.id, web_url,
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
        try:
            raw = base64.b64decode(self.preview_image)
            digest = hashlib.sha256(raw).hexdigest()[:12]
        except Exception:
            digest = "unknown"
        return f"profile_{self.id}_{ts}_{digest}"

    def _load_records(self, model_name, field_names):
        """Search the target model applying filter_preset domain and sort_preset order.

        Sort resolution: sort_preset wins when it resolves a field; falls back
        to display_order (manual). Falls back to no order on invalid order string.
        The domain is always safe — _build_filter_domain never raises.
        """
        model_env = self.env[model_name].sudo()
        limit  = self.display_limit or 20
        domain = self._build_filter_domain(model_name)

        preset_order = self._build_sort_order(model_name)
        order = preset_order if preset_order is not None else (self.display_order or False)

        try:
            return model_env.search(domain, limit=limit, order=order)
        except Exception:
            return model_env.search(domain, limit=limit)

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
