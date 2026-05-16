"""UI extensions for the TRMNL device model."""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .trmnl_device import (
    APPROVAL_STATE_ACCEPTED,
    DISPLAY_POLICY_ERROR,
)


class TrmnlDeviceUiExtension(models.Model):
    """Add backend management fields and actions for TRMNL devices.

    Provides sequence-based manual ordering, an admin-facing device name,
    a read-only log relation, a display-only field for the last device-reported
    refresh rate in minutes, a computed flag that controls visibility of the
    manual-accept button, and multi-record action methods wired to the list
    view's Action drop-down (accept, remove, reset).
    """

    _inherit = "trmnl.device"
    _order = "sequence, id"

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
    last_reported_refresh_rate_minutes = fields.Integer(
        string="Last Reported Refresh Rate (min)",
        compute="_compute_last_reported_refresh_rate_minutes",
        readonly=True,
        store=False,
        help="Refresh rate last reported by the device, displayed in minutes.",
    )
    accept_button_visible = fields.Boolean(
        string="Accept Button Visible",
        compute="_compute_accept_button_visible",
        store=False,
        help=(
            "True when the device is not yet accepted and the current policy "
            "is set to 'error', making manual acceptance meaningful."
        ),
    )

    @api.model
    def _next_sequence_value(self):
        """Return the next manual sort position for a new device."""
        highest_sequence_device = self.sudo().search(
            [], order="sequence desc, id desc", limit=1
        )
        return (highest_sequence_device.sequence or 0) + 10

    @api.depends("refresh_rate")
    def _compute_last_reported_refresh_rate_minutes(self):
        """Convert the device-reported refresh rate from seconds to minutes."""
        for device in self:
            raw_seconds = device.refresh_rate or 0
            device.last_reported_refresh_rate_minutes = int(raw_seconds / 60.0)

    @api.depends("approval_state")
    def _compute_accept_button_visible(self):
        """Show the accept button only when the policy is 'error' and device is not accepted.

        Re-reads the policy from ``ir.config_parameter`` for every batch so
        the value stays current without requiring a server restart.
        """
        current_policy = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("trmnl.display_unknown_device_policy", DISPLAY_POLICY_ERROR)
        )
        policy_is_error = current_policy == DISPLAY_POLICY_ERROR

        for device in self:
            device.accept_button_visible = (
                policy_is_error and device.approval_state != APPROVAL_STATE_ACCEPTED
            )

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

    def _open_wizard_for_device(self, wizard_model_name, action_name):
        """Open a modal wizard for the current device."""
        self.ensure_one()
        wizard = self.env[wizard_model_name].create({"device_id": self.id})
        return {
            "type": "ir.actions.act_window",
            "name": action_name,
            "res_model": wizard_model_name,
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
            "context": {"dialog_size": "medium"},
        }

    def action_open_accept_wizard(self):
        """Open the accept-confirmation wizard for this device."""
        return self._open_wizard_for_device(
            "trmnl.device.accept.wizard", _("Accept Device")
        )

    def action_open_remove_wizard(self):
        """Open the delete-confirmation wizard for this device."""
        return self._open_wizard_for_device(
            "trmnl.device.remove.wizard", _("Remove Device")
        )

    def action_open_reset_wizard(self):
        """Open the factory-reset confirmation wizard for this device."""
        return self._open_wizard_for_device(
            "trmnl.device.reset.wizard", _("Reset Device")
        )

    # ------------------------------------------------------------------
    # multi-record list-view actions (Action drop-down)
    # ------------------------------------------------------------------

    def action_bulk_accept(self):
        """Accept all selected devices that are not yet accepted.

        Devices without a stored presented token are skipped with a warning
        rather than aborting the entire batch, so that the remaining devices
        are still processed.
        """
        skipped_names = []

        for device in self:
            if device.approval_state == APPROVAL_STATE_ACCEPTED:
                continue

            if not device.last_presented_token_hash:
                label = device.device_name or device.friendly_id or device.mac_address
                skipped_names.append(label)
                continue

            device.accept_device()

        if skipped_names:
            skipped_list = ", ".join(skipped_names)
            raise UserError(
                _(
                    "The following device(s) could not be accepted because no "
                    "display poll has been recorded yet (no presented token "
                    "stored): %(devices)s",
                    devices=skipped_list,
                )
            )

    def action_bulk_remove(self):
        """Delete all selected device records immediately."""
        self.unlink()

    def action_bulk_reset(self):
        """Schedule a factory reset for all selected devices.

        Sets ``reset_pending`` on every record in the selection.  The record
        is deleted automatically by ``resolve_display_request`` once the
        reset signal has been delivered to the device.
        """
        self.write({"reset_pending": True})
