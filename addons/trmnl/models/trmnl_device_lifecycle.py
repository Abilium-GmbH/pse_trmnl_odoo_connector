"""TRMNL device registration and lifecycle helpers."""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .trmnl_device import (
    DISPLAY_POLICY_AUTO_ACCEPT,
    DISPLAY_POLICY_ERROR,
    DISPLAY_POLICY_FACTORY_RESET,
)


class TrmnlDeviceLifecycleMixin(models.Model):
    """Extend TRMNL devices with setup and registration helpers."""

    _inherit = "trmnl.device"

    ##################################################
    # display policy
    ##################################################

    @api.model
    def _get_display_request_policy(self):
        """Return the configured default policy for unresolved display polls."""
        config_parameter = self.env["ir.config_parameter"].sudo()
        policy = config_parameter.get_param(
            "trmnl.display_unknown_device_policy",
            DISPLAY_POLICY_ERROR,
        )

        if policy not in {
            DISPLAY_POLICY_ERROR,
            DISPLAY_POLICY_AUTO_ACCEPT,
            DISPLAY_POLICY_FACTORY_RESET,
        }:
            return DISPLAY_POLICY_ERROR

        return policy

    @api.model
    def _set_display_request_policy(self, policy):
        """Persist the default policy for unresolved display polls."""
        if policy not in {
            DISPLAY_POLICY_ERROR,
            DISPLAY_POLICY_AUTO_ACCEPT,
            DISPLAY_POLICY_FACTORY_RESET,
        }:
            raise ValidationError(_("Unsupported TRMNL display policy."))

        self.env["ir.config_parameter"].sudo().set_param(
            "trmnl.display_unknown_device_policy",
            policy,
        )

    @api.model
    def _consume_factory_reset_policy(self):
        """Reset the one-shot factory-reset behavior back to the default policy."""
        current_policy = self._get_display_request_policy()
        if current_policy == DISPLAY_POLICY_FACTORY_RESET:
            self._set_display_request_policy(DISPLAY_POLICY_ERROR)

    ##################################################
    # setup
    ##################################################

    @api.model
    def upsert_from_setup_headers(self, headers):
        """Create a device from setup headers or fail if the MAC already exists."""
        mac_address = self._normalize_mac_address(headers.get("ID"))
        if not mac_address:
            raise ValidationError(_("TRMNL setup request is missing a valid ID header."))

        existing_device = self.sudo().search([("mac_address", "=", mac_address)], limit=1)
        if existing_device:
            raise ValidationError(_("TRMNL device with this MAC address is already registered."))

        firmware_version = self._parse_to_string(headers.get("FW-Version"))
        now_value = fields.Datetime.now()
        raw_token, token_values = self._build_api_token_material()

        create_values = {
            "mac_address": mac_address,
            "friendly_id": self._generate_unique_friendly_id(),
            "approval_state": "approved",
            "registration_source": "setup",
            "first_seen_at": now_value,
            "last_seen_at": now_value,
            "last_setup_at": now_value,
            "approved_at": now_value,
            "setup_request_count": 1,
        }
        if firmware_version is not False:
            create_values["firmware_version"] = firmware_version

        create_values.update(token_values)
        device = self.sudo().create(create_values)
        return device, raw_token, "created"

    ##################################################
    # display registration
    ##################################################

    @api.model
    def register_or_adopt_from_display_headers(self, headers, api_token):
        """Register a device from display headers by adopting the presented token."""
        mac_address = self._normalize_mac_address(headers.get("ID"))
        token_value = self._parse_to_string(api_token)

        if not mac_address or not token_value:
            return self.browse(), "missing_identity"

        firmware_version = self._parse_to_string(headers.get("FW-Version"))
        now_value = fields.Datetime.now()

        device = self.sudo().search([("mac_address", "=", mac_address)], limit=1)

        if device:
            update_values = {
                "approval_state": "approved",
                "registration_source": "display",
                "approved_at": device.approved_at or now_value,
                "last_seen_at": now_value,
            }
            if firmware_version is not False:
                update_values["firmware_version"] = firmware_version

            update_values.update(self._hash_api_token(token_value))
            device.with_context(trmnl_allow_identity_update=True).write(update_values)
            return device, "updated"

        create_values = {
            "mac_address": mac_address,
            "friendly_id": self._generate_unique_friendly_id(),
            "approval_state": "approved",
            "registration_source": "display",
            "first_seen_at": now_value,
            "last_seen_at": now_value,
            "approved_at": now_value,
        }
        if firmware_version is not False:
            create_values["firmware_version"] = firmware_version

        create_values.update(self._hash_api_token(token_value))
        device = self.sudo().create(create_values)
        return device, "created"

    @api.model
    def build_setup_error_response(self):
        """Build the JSON payload returned when setup cannot be processed."""
        return {"status": 404}

    def build_setup_response(self, api_token=""):
        """Build the JSON payload returned after a successful setup request."""
        self.ensure_one()
        return {
            "status": 200,
            "api_key": api_token or "",
            "friendly_id": self.friendly_id,
            "image_url": self.image_url or "",
        }
