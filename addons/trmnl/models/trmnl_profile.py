from __future__ import annotations

import base64
import logging
from calendar import monthrange
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Priority-ordered list of date/datetime fields used by filter_preset and sort_preset=date.
# create_date is the guaranteed fallback — it exists on every Odoo model.
_FILTER_DATE_FIELDS = ["date_deadline", "date_order", "start", "date", "create_date"]

# Priority-ordered list of amount fields used by sort_preset=amount.
_SORT_AMOUNT_FIELDS = ["amount_total", "expected_revenue", "planned_revenue"]

# Maps Odoo module name → the primary res_model for that app.
# Used to filter technical actions out of the action picker and to auto-select
# the most useful action when a known app is chosen.
_APP_MODELS = {
    "calendar":      "calendar.event",
    "project":       "project.task",
    "crm":           "crm.lead",
    "point_of_sale": "pos.order",
    "mail":          "mail.activity",
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

    @api.onchange("app_module_id")
    def _onchange_app_module_id(self):
        self.odoo_action_id = False
        self.app_model_id = False
        self.display_field_ids = False

        if not self.app_module_id:
            return {"domain": {"odoo_action_id": [("id", "=", False)]}}

        imd = self.env["ir.model.data"].sudo().search([
            ("module", "=", self.app_module_id.name),
            ("model", "=", "ir.actions.act_window"),
        ])

        actions = self.env["ir.actions.act_window"].sudo().browse(
            imd.mapped("res_id")
        ).exists()

        # For known apps filter to the expected model, hiding technical actions.
        expected_model = _APP_MODELS.get(self.app_module_id.name)
        if expected_model:
            actions = actions.filtered(lambda a: a.res_model == expected_model)

        # Auto-select: prefer view_mode containing "calendar" (catches the
        # Meetings action), then fall back to the first available action.
        if actions:
            preferred = actions.filtered(lambda a: "calendar" in (a.view_mode or ""))
            self.odoo_action_id = preferred[0] if preferred else actions[0]
            self._onchange_odoo_action_id()

        return {"domain": {"odoo_action_id": [("id", "in", actions.ids)]}}

    @api.onchange("odoo_action_id")
    def _onchange_odoo_action_id(self):
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

        rows = [
            [self._extract_field_value(rec, fname) for fname in field_names]
            for rec in records
        ]
        from odoo.addons.trmnl.trmnl_preview import render_list_preview
        return render_list_preview(rows, field_labels)

    # ------------------------------------------------------------------
    # preview rendering
    # ------------------------------------------------------------------

    def action_render_preview(self):
        self.ensure_one()
        if not self.odoo_action_id or not self.odoo_action_id.res_model:
            raise UserError(_("Select a Data View before rendering a preview."))
        self._render_and_store_preview()
        return {"type": "ir.actions.client", "tag": "reload"}

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

        records = self._load_records(model_name, field_names)
        png_bytes = self._dispatch_renderer(model_name, field_names, field_labels, records)

        self.write({
            "preview_image": base64.b64encode(png_bytes),
            "preview_generated_at": fields.Datetime.now(),
        })

    def _get_display_image_url(self):
        """Return the public URL for this profile's preview image, or False.

        Checks ``trmnl.public_base_url`` first so that a LAN/public hostname
        can be configured when ``web.base.url`` resolves to localhost.
        Set it in Settings → Technical → Parameters → System Parameters.
        """
        if not self.preview_image:
            return False
        params = self.env["ir.config_parameter"].sudo()
        base_url = (
            params.get_param("trmnl.public_base_url", "")
            or params.get_param("web.base.url", "")
        ).rstrip("/")
        return f"{base_url}/api/profile/image/{self.id}"

    def _get_display_filename(self):
        """Return a filename that changes whenever the preview is regenerated."""
        if not self.preview_image or not self.preview_generated_at:
            return False
        ts = self.preview_generated_at.strftime("%Y%m%dT%H%M%S")
        return f"profile_{self.id}_{ts}"

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
