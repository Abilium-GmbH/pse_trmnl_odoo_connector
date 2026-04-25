"""Confirmation wizards for destructive TRMNL device actions."""

from __future__ import annotations

from odoo import _, fields, models
from odoo.exceptions import UserError

from .trmnl_device import DISPLAY_POLICY_FACTORY_RESET


class TrmnlDeviceDeleteWizard(models.TransientModel):
    """Confirm and execute the permanent removal of a TRMNL device record.

    Presents the operator with three choices:
    - Cancel  — dismiss the dialog without any change.
    - Remove  — delete the device record from the database.
    - Reset & Remove — trigger a one-shot factory-reset response on the next
      display poll (status 500) and then delete the device record.
    """

    _name = "trmnl.device.delete.wizard"
    _description = "TRMNL Device Delete Confirmation"

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
            wizard.device_display_name = device.device_name or device.friendly_id or device.mac_address

    def action_remove(self):
        """Delete the device record without triggering a factory reset."""
        self.ensure_one()
        device = self.device_id

        if not device.exists():
            raise UserError(_("The device no longer exists."))

        device.unlink()
        return self._redirect_to_device_list()

    def action_reset_and_remove(self):
        """Arm the one-shot factory-reset policy and then delete the device record."""
        self.ensure_one()
        device = self.device_id

        if not device.exists():
            raise UserError(_("The device no longer exists."))

        device_model = self.env["trmnl.device"].sudo()
        device_model._set_display_request_policy(DISPLAY_POLICY_FACTORY_RESET)
        device.unlink()
        return self._redirect_to_device_list()

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


class TrmnlDeviceResetWizard(models.TransientModel):
    """Confirm and execute a factory-reset followed by device record removal.

    The reset arms the one-shot ``factory_reset`` display policy so that the
    device receives an HTTP 500 response on its next display poll, which causes
    it to wipe its stored Wi-Fi credentials and re-enter the pairing flow.
    The device record is then deleted from the database.

    Presents the operator with two choices:
    - Cancel — dismiss the dialog without any change.
    - Reset  — arm the factory-reset policy and remove the device record.
    """

    _name = "trmnl.device.reset.wizard"
    _description = "TRMNL Device Reset Confirmation"

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
            wizard.device_display_name = device.device_name or device.friendly_id or device.mac_address

    def action_reset(self):
        """Arm the one-shot factory-reset policy and remove the device record."""
        self.ensure_one()
        device = self.device_id

        if not device.exists():
            raise UserError(_("The device no longer exists."))

        device_model = self.env["trmnl.device"].sudo()
        device_model._set_display_request_policy(DISPLAY_POLICY_FACTORY_RESET)
        device.unlink()
        return self._redirect_to_device_list()

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
