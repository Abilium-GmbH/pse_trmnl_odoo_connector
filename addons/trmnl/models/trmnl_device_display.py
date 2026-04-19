"""TRMNL device display request handling and response builders."""

from __future__ import annotations

from odoo import api, models

from .trmnl_device import (
    DEFAULT_DISPLAY_ERROR_STATUS,
    DEFAULT_REFRESH_RATE,
    DISPLAY_POLICY_AUTO_ACCEPT,
    DISPLAY_POLICY_FACTORY_RESET,
)


class TrmnlDeviceDisplayMixin(models.Model):
    """Extend TRMNL devices with display request resolution helpers."""

    _inherit = "trmnl.device"

    ##################################################
    # responses
    ##################################################

    def build_display_error_response(self, status=None):
        """Build the payload returned when a display request cannot be served."""
        if status is None:
            status = DEFAULT_DISPLAY_ERROR_STATUS
        return {"status": status}

    def build_display_response(self):
        """Build the normal display payload for an approved device."""
        self.ensure_one()

        return {
            "status": 0,
            "filename": self.filename or "",
            "image_url": self.image_url or "",
            "refresh_rate": self.refresh_rate or DEFAULT_REFRESH_RATE,
            "special_function": self.special_function or "none",
            "action": self.display_action or "",
        }

    ##################################################
    # request resolution
    ##################################################

    @api.model
    def resolve_display_request(self, headers):
        """Resolve a TRMNL display poll using the configured device policy."""
        mac_address = self._normalize_mac_address(headers.get("ID"))
        api_token = self._parse_to_string(headers.get("Access-Token"))

        if not mac_address:
            return self.browse(), self.build_display_error_response(), "missing_identity"

        device = self.sudo().search([("mac_address", "=", mac_address)], limit=1)
        if not device:
            return self._resolve_unknown_display_request(headers, api_token)

        if api_token and device._verify_api_token(api_token):
            if device.approval_state != "approved":
                device._record_access_denied(reason=device.approval_state)
                return device, self.build_display_error_response(), "not_approved"

            device._apply_display_telemetry(headers)
            device._record_display_served()
            return device, device.build_display_response(), "display"

        return self._resolve_invalid_token_display_request(device, headers, api_token)

    def _resolve_unknown_display_request(self, headers, api_token):
        """Resolve a display request from a MAC address that is not registered yet."""
        if api_token and self._get_display_request_policy() == DISPLAY_POLICY_AUTO_ACCEPT:
            device, record_status = self.register_or_adopt_from_display_headers(headers, api_token)
            if device:
                device._apply_display_telemetry(headers)
                device._record_display_served()
                return device, device.build_display_response(), record_status

        if self._get_display_request_policy() == DISPLAY_POLICY_FACTORY_RESET:
            self._consume_factory_reset_policy()
            return self.browse(), self.build_display_error_response(status=500), "factory_reset"

        return self.browse(), self.build_display_error_response(), "unknown"

    def _resolve_invalid_token_display_request(self, device, headers, api_token):
        """Resolve a display request from a known device with an invalid token."""
        policy = self._get_display_request_policy()

        if api_token and policy == DISPLAY_POLICY_AUTO_ACCEPT:
            device._store_api_token(api_token)
            device.with_context(trmnl_allow_identity_update=True).write(
                {
                    "approval_state": "approved",
                    "registration_source": "display",
                    "approved_at": device.approved_at or self._utc_now(),
                }
            )
            device._apply_display_telemetry(headers)
            device._record_display_served()
            return device, device.build_display_response(), "token_adopted"

        if policy == DISPLAY_POLICY_FACTORY_RESET:
            self._consume_factory_reset_policy()
            return device, self.build_display_error_response(status=500), "factory_reset"

        device._record_access_denied(reason="invalid_token")
        return device, self.build_display_error_response(), "invalid_token"
