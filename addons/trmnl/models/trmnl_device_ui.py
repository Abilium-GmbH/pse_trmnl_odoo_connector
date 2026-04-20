"""UI extensions for the TRMNL device model."""

from __future__ import annotations

from odoo import api, fields, models


class TrmnlDeviceUiExtension(models.Model):
    """Add backend management fields and actions for TRMNL devices."""

    _inherit = "trmnl.device"
    _order = "sequence, friendly_id, id"

    sequence = fields.Integer(
        string="Sequence",
        default=10,
        index=True,
        copy=False,
        help="Controls the manual ordering of devices in the backend list.",
    )
    device_name = fields.Char(
        string="Device Name",
        index=True,
        copy=False,
        help="Admin-facing name for the device.",
    )
    log_ids = fields.One2many(
        comodel_name="trmnl.device.log",
        inverse_name="device_id",
        string="Logs",
        readonly=True,
        copy=False,
        help="Read-only log entries collected from this device.",
    )
    ui_status = fields.Char(
        string="Status",
        readonly=True,
        copy=False,
        compute="_compute_ui_status",
        help=(
            "Placeholder for the device responsiveness indicator. "
            "Replace this with a heartbeat-based implementation later."
        ),
    )

    @api.model
    def _next_sequence_value(self):
        """Return the next manual sort position for a new device."""

        highest_sequence_device = self.sudo().search(
            [], order="sequence desc, id desc", limit=1
        )
        return (highest_sequence_device.sequence or 0) + 10

    @api.depends()
    def _compute_ui_status(self):
        """Provide the current placeholder status text."""

        for device in self:
            device.ui_status = "Status pending implementation"

    @api.model_create_multi
    def create(self, values_list):
        """Assign a stable sequence when one is not provided."""

        next_sequence_value = self._next_sequence_value()
        normalized_values_list = []

        for values in values_list:
            normalized_values = dict(values)

            if normalized_values.get("sequence") in (None, False):
                normalized_values["sequence"] = next_sequence_value
                next_sequence_value += 10

            normalized_values_list.append(normalized_values)

        return super().create(normalized_values_list)

    def action_open_device_form(self):
        """Open the current device in its editable form view."""

        self.ensure_one()

        form_view = self.env.ref(
            "trmnl.trmnl_device_view_form", raise_if_not_found=False
        )
        action = {
            "type": "ir.actions.act_window",
            "name": self.device_name or self.friendly_id,
            "res_model": "trmnl.device",
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
            "context": {},
        }
        if form_view:
            action["views"] = [(form_view.id, "form")]
        return action
    
    def action_delete_device(self):
        """Method to delete a device from the data base"""

        self.ensure_one()
        self.unlink()
        return {
            "type": "ir.actions.act_window",
            "name": "Known TRMNL Devices",
            "res_model": "trmnl.device",
            "view_mode": "list,form",
            "target": "current",
        }
