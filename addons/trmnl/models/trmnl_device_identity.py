"""TRMNL device registration and identity lifecycle helpers."""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class TrmnlDeviceIdentity(models.Model):
    """Extend TRMNL devices with setup and identity management helpers."""

    _inherit = "trmnl.device"

    @api.model
    def _create_placeholder_device(self, mac_address, token=None, source="display"):
        """Create a minimal device record for a previously unknown device."""
        now_value = fields.Datetime.now()
        values = {
            "mac_address": mac_address,
            "friendly_id": self._generate_unique_friendly_id(),
            "approval_state": "pending",
            "registration_source": source,
            "first_seen_at": now_value,
            "last_seen_at": now_value,
        }
        if token:
            values.update(self._hash_api_token(token))
        return self.sudo().create([values])[0]

    @api.model
    def upsert_from_setup_headers(self, headers):
        """Create or refresh a device from the HTTP headers used by TRMNL setup."""
        mac_address = self._normalize_mac_address(headers.get("ID"))
        if not mac_address:
            raise ValidationError(_("TRMNL setup request is missing a valid ID header."))

        firmware_version = self._parse_to_string(headers.get("FW-Version"))
        now_value = fields.Datetime.now()
        device = self.sudo().search([("mac_address", "=", mac_address)], limit=1)

        if device:
            raw_token = device._rotate_api_token()
            update_values = {
                "approval_state": "approved",
                "approved_at": now_value,
                "last_setup_at": now_value,
                "last_seen_at": now_value,
                "next_display_action": "normal",
                "registration_source": "setup",
                "setup_request_count": (device.setup_request_count or 0) + 1,
            }
            if firmware_version is not False:
                update_values["firmware_version"] = firmware_version
            device.with_context(trmnl_allow_identity_update=True).write(update_values)
            return device, raw_token, "updated"

        raw_token, token_values = self._build_api_token_material()
        create_values = {
            "mac_address": mac_address,
            "friendly_id": self._generate_unique_friendly_id(),
            "approval_state": "approved",
            "approved_at": now_value,
            "first_seen_at": now_value,
            "last_setup_at": now_value,
            "last_seen_at": now_value,
            "next_display_action": "normal",
            "registration_source": "setup",
            "setup_request_count": 1,
        }
        create_values.update(token_values)
        if firmware_version is not False:
            create_values["firmware_version"] = firmware_version
        device = self.sudo().create([create_values])[0]
        return device, raw_token, "created"

    @api.model
    def update_from_display_headers(self, headers):
        """Refresh device metadata from display polling headers."""
        mac_address = self._normalize_mac_address(headers.get("ID"))
        if not mac_address:
            raise ValidationError(_("TRMNL display request is missing a valid ID header."))

        device = self.sudo().search([("mac_address", "=", mac_address)], limit=1)
        if not device:
            raise ValidationError(_("TRMNL device is not registered."))

        self._copy_display_headers_to_device(device, headers)
        return device
