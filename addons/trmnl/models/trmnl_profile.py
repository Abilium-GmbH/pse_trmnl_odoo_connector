from __future__ import annotations

import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Presets prefill layout/fields/order/limit when a known model is selected.
# Users can edit all values afterwards. Fields are validated against
# ir.model.fields at apply time so missing optional modules are silently skipped.
_MODEL_PRESETS = {
    "calendar.event": {
        "layout": "list",
        "fields": ["name", "start", "stop", "location", "user_id"],
        "order": "start asc",
        "limit": 10,
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

        action_ids = self.env["ir.actions.act_window"].sudo().browse(
            imd.mapped("res_id")
        ).exists().ids

        return {"domain": {"odoo_action_id": [("id", "in", action_ids)]}}

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
        return True

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
        rows = [
            [self._extract_field_value(rec, fname) for fname in field_names]
            for rec in records
        ]

        from odoo.addons.trmnl.trmnl_preview import render_list_preview
        png_bytes = render_list_preview(rows, field_labels)

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
        """Search the target model, falling back to default order if display_order is invalid."""
        model_env = self.env[model_name].sudo()
        limit = self.display_limit or 20
        order = self.display_order or False

        try:
            return model_env.search([], limit=limit, order=order)
        except Exception:
            return model_env.search([], limit=limit)

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
