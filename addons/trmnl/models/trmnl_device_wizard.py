"""Confirmation wizards for TRMNL device actions and policy management."""

from __future__ import annotations

from odoo import _, fields, models
from odoo.exceptions import UserError

from .trmnl_device import (
    APPROVAL_STATE_ACCEPTED,
    DISPLAY_POLICY_ERROR,
    DISPLAY_POLICY_SELECTION,
    TRMNL_POLICY_PARAM,
)


class TrmnlDeviceActionWizardMixin(models.AbstractModel):
    """Shared helpers for TRMNL device action confirmation wizards.

    Provides common display-name computation and post-action
    navigation for wizards that operate on a single device record.
    """

    _name = "trmnl.device.action.wizard.mixin"
    _description = "TRMNL Device Action Wizard Mixin"

    device_id = fields.Many2one(
        comodel_name="trmnl.device",
        string="Device",
        required=True,
        ondelete="cascade",
        readonly=True,
    )
    device_display_name = fields.Char(
        string="Device Display Name",
        compute="_compute_device_display_name",
        readonly=True,
    )

    def _compute_device_display_name(self):
        """Derive a human-readable label from the linked device."""
        for wizard in self:
            device = wizard.device_id
            wizard.device_display_name = (
                device.device_name or device.friendly_id or device.mac_address
            )

    @staticmethod
    def _redirect_to_device_list():
        """Return an action that navigates back to the device list view."""
        return {
            "type": "ir.actions.act_window",
            "name": _("Devices"),
            "res_model": "trmnl.device",
            "view_mode": "list,form",
            "target": "current",
        }

    def _action_schedule_reset(self):
        """Schedule a factory reset for the linked device on its next display poll.

        Sets ``reset_pending`` on the device record. The record is not deleted
        here — it is removed automatically by ``resolve_display_request`` after
        the reset signal has been delivered to the device. If the device
        re-registers via /api/setup before polling /api/display, the pending
        flag is cleared and the device is re-registered normally.
        """
        self.ensure_one()
        device = self.device_id

        if not device.exists():
            raise UserError(_("The device no longer exists."))

        device.write({"reset_pending": True})
        return self._redirect_to_device_list()

# ---------------------------------------------------------------------------
# Accept wizard
# ---------------------------------------------------------------------------

class TrmnlDeviceAcceptWizard(models.TransientModel):
    """Confirm and execute the manual acceptance of a TRMNL device.

    Applicable to devices in ``token_mismatch`` or ``unknown_device`` state
    that have attempted at least one display poll (so a presented token has
    been stored).  Accepting the device promotes the last-presented token to
    the accepted-token slot and sets the approval state to ``accepted``.
    """

    _name = "trmnl.device.accept.wizard"
    _description = "TRMNL Device Accept Confirmation"
    _inherit = ["trmnl.device.action.wizard.mixin"]

    approval_state = fields.Selection(
        related="device_id.approval_state",
        readonly=True,
    )

    def action_accept(self):
        """Accept the device by adopting its last-presented token."""
        self.ensure_one()
        device = self.device_id

        if not device.exists():
            raise UserError(_("The device no longer exists."))

        if device.approval_state == APPROVAL_STATE_ACCEPTED:
            raise UserError(_("This device is already accepted."))

        device.accept_device()

        return {
            "type": "ir.actions.act_window",
            "name": _("Devices"),
            "res_model": "trmnl.device",
            "res_id": device.id,
            "view_mode": "form",
            "target": "current",
        }

# ---------------------------------------------------------------------------
# Remove wizard
# ---------------------------------------------------------------------------

class TrmnlDeviceRemoveWizard(models.TransientModel):
    """Confirm and execute the removal of a TRMNL device record.

    Presents the user with three choices:
    -------------------------------------
    - Cancel         — dismiss the dialog without any change.
    - Remove         — delete the device record from the database.
    - Reset & Remove — schedule a factory reset for the device. The record is
                       deleted automatically after the reset signal is delivered
                       on the next /api/display poll.
    """

    _name = "trmnl.device.remove.wizard"
    _description = "TRMNL Device Remove Confirmation"
    _inherit = ["trmnl.device.action.wizard.mixin"]

    def action_remove(self):
        """Delete the device record without triggering a factory reset."""
        self.ensure_one()
        device = self.device_id

        if not device.exists():
            raise UserError(_("The device no longer exists."))

        device.unlink()
        return self._redirect_to_device_list()

    def action_reset_and_remove(self):
        """Schedule a factory reset for this device and return to the device list.

        The device record is retained until the reset signal is delivered on
        the next /api/display poll, at which point the record is deleted
        automatically.
        """
        return self._action_schedule_reset()

# ---------------------------------------------------------------------------
# Reset wizard
# ---------------------------------------------------------------------------

class TrmnlDeviceResetWizard(models.TransientModel):
    """Confirm and execute a factory reset for a TRMNL device.

    The device record is retained until the reset signal is delivered on the
    next /api/display poll, at which point the record is deleted automatically.

    Presents the user with two choices:
    -----------------------------------
    - Cancel — dismiss the dialog without any change.
    - Reset  — schedule a factory reset for the device.
    """

    _name = "trmnl.device.reset.wizard"
    _description = "TRMNL Device Reset Confirmation"
    _inherit = ["trmnl.device.action.wizard.mixin"]

    def action_reset(self):
        """Schedule a factory reset for this device and return to the device list.

        The device record is retained until the reset signal is delivered on
        the next /api/display poll, at which point the record is deleted
        automatically.
        """
        return self._action_schedule_reset()

# ---------------------------------------------------------------------------
# Display policy wizard
# ---------------------------------------------------------------------------

class TrmnlDisplayPolicyWizard(models.TransientModel):
    """Wizard for reviewing and changing the display request policy.

    Policy options
    --------------
    error          — Unknown MACs and token mismatches are rejected.  A stub
                     record is created so the admin can manually accept the
                     device from the list view.
    auto_accept    — The server adopts whatever token the device presents and
                     immediately serves it.  Convenient for first-time setup
                     but gives any device access.
    factory_reset  — The unrecognised or mismatched device receives a response,
                     which triggers a factory reset on the device
                     (wipes Wi-Fi credentials).
    """

    _name = "trmnl.display.policy.wizard"
    _description = "TRMNL Display Policy"

    policy = fields.Selection(
        selection=DISPLAY_POLICY_SELECTION,
        string="Policy",
        required=True,
        default=DISPLAY_POLICY_ERROR,
    )

    def default_get(self, fields_list):
        """Pre-populate the policy field from the current stored value."""
        result = super().default_get(fields_list)
        if "policy" in fields_list:
            current_policy = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param(TRMNL_POLICY_PARAM, DISPLAY_POLICY_ERROR)
            )
            result["policy"] = current_policy
        return result

    def action_apply(self):
        """Persist the selected policy and close the wizard."""
        self.ensure_one()
        self.env["trmnl.device"].sudo()._set_display_request_policy(self.policy)
        return {"type": "ir.actions.act_window_close"}
