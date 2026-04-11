"""TRMNL device display and log ingestion helpers."""
from __future__ import annotations

from odoo import api, fields, models


class TrmnlDeviceDisplay(models.Model):
    """Extend TRMNL devices with display request resolution helpers."""

    _inherit = "trmnl.device"

    @api.model
    def resolve_display_request(self, headers):
        """Return the payload that should be sent back to a device display poll."""
        mac_address = self._normalize_mac_address(headers.get("ID"))
        token = self._parse_to_string(headers.get("Access-Token"))

        if not mac_address:
            return self.browse(), self.build_no_user_display_response(), "missing_identity"

        device = self.sudo().search([("mac_address", "=", mac_address)], limit=1)
        if not device:
            return (
                self.browse(),
                self.build_display_error_response(status=self._get_default_display_error_status()),
                "unknown",
            )

        if not token or not device._verify_api_token(token):
            device._record_access_denied(reason="invalid_token")
            return device, device.build_display_error_response(), "invalid_token"

        if device.approval_state != "approved":
            device._record_access_denied(reason=device.approval_state)
            return device, device.build_display_error_response(), device.approval_state

        self._copy_display_headers_to_device(device, headers)
        device._record_display_served()
        return device, device.build_display_response(), "display"

    @api.model
    def _copy_display_headers_to_device(self, device, headers):
        """Persist device telemetry reported during a display poll."""
        update_values = {
            "refresh_rate": self._parse_to_int(headers.get("Refresh-Rate")),
            "battery_voltage": self._parse_to_float(headers.get("Battery-Voltage")),
            "firmware_version": self._parse_to_string(headers.get("FW-Version")),
            "rssi_dbm": self._parse_to_int(headers.get("RSSI")),
            "display_width": self._parse_to_int(headers.get("Width")),
            "display_height": self._parse_to_int(headers.get("Height")),
            "last_display_at": fields.Datetime.now(),
            "last_seen_at": fields.Datetime.now(),
            "display_request_count": (device.display_request_count or 0) + 1,
        }

        filtered_values = {
            field_name: value
            for field_name, value in update_values.items()
            if value is not False
        }

        device.with_context(trmnl_allow_identity_update=True).write(filtered_values)
        return device
