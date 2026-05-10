"""TRMNL device display request handling and response builders."""

from __future__ import annotations

import logging
from typing import NamedTuple

from odoo import api, models

_logger = logging.getLogger(__name__)

from .trmnl_device import (
    APPROVAL_STATE_ACCEPTED,
    DEFAULT_DISPLAY_ERROR_STATUS,
    DEFAULT_REFRESH_RATE,
    DISPLAY_POLICY_AUTO_ACCEPT,
    DISPLAY_POLICY_FACTORY_RESET,
)


class DisplayResolutionResult(NamedTuple):
    """Structured result of a display request resolution."""

    device: object
    payload: dict
    record_status: str


class TrmnlDeviceDisplayMixin(models.Model):
    """Extend TRMNL devices with display request resolution helpers.

    Response builders read ``desired_refresh_rate`` (the admin-configured
    value) rather than the telemetry field ``refresh_rate`` (the value last
    reported by the device), so the server can command a new interval
    independently of what the device currently uses.

    Request resolution follows this decision tree for each incoming poll:

    1. MAC address missing          → error response, no record touched.
    2. MAC unknown + auto-accept    → register & adopt token, serve display.
    3. MAC unknown + factory-reset  → return {"status": 500}.
    4. MAC unknown + error          → create stub record, return error.
    5. MAC known, token valid       → serve display (if accepted).
    6. MAC known, token invalid
        + auto-accept               → adopt new token, serve display.
        + factory-reset             → return {"status": 500}, delete record.
        + error                     → update mismatch record, return {"status": 202}.
    """

    _inherit = "trmnl.device"

    # ------------------------------------------------------------------
    # response builders
    # ------------------------------------------------------------------

    def build_display_error_response(self, status=None):
        """Build the payload returned when a display request cannot be served."""
        if status is None:
            status = DEFAULT_DISPLAY_ERROR_STATUS
        return {"status": status}

    def _consume_identify_flag(self):
        """Consume the one-shot identify flag if set."""
        self.ensure_one()

        if self.identify_pending:
            self.write({"identify_pending": False})
            return True
        return False

    def build_display_response(self):
        """Build the normal display payload for an accepted device."""
        self.ensure_one()

        image_url, filename = self._resolve_display_image()

        return {
            "status": 0,
            "filename": filename,
            "image_url": image_url,
            "refresh_rate": self.desired_refresh_rate or DEFAULT_REFRESH_RATE,
        }

    def _resolve_display_image(self):
        """Return (image_url, filename) from the active profile or device fallback.

        Renders the profile image on first call if it has not been generated yet.
        Falls back to device.image_url / device.filename on any error.
        """
        self.ensure_one()
        device_ref = f"device_id={self.id} mac={self.mac_address or '?'}"
        try:
            profile = self.env["trmnl.profile"].sudo().search(
                [("device_id", "=", self.id), ("active", "=", True)],
                limit=1,
            )

            if not profile:
                _logger.info("TRMNL display: no active profile for %s — using device fallback", device_ref)
                return self.image_url or "", self.filename or ""

            _logger.info(
                "TRMNL display: found profile id=%s name=%r has_image=%s for %s",
                profile.id, profile.name, bool(profile.preview_image), device_ref,
            )

            if not profile.preview_image:
                _logger.info("TRMNL display: rendering preview for profile id=%s", profile.id)
                profile._render_and_store_preview()

            image_url = profile._get_display_image_url()
            filename = profile._get_display_filename()

            _logger.info(
                "TRMNL display: profile id=%s resolved image_url=%r filename=%r",
                profile.id, image_url, filename,
            )

            if image_url and filename:
                return image_url, filename

            _logger.warning(
                "TRMNL display: profile id=%s returned empty url=%r or filename=%r — using device fallback",
                profile.id, image_url, filename,
            )
        except Exception as exc:
            _logger.warning(
                "TRMNL display: exception resolving profile image for %s: %s",
                device_ref, exc, exc_info=True,
            )

        return self.image_url or "", self.filename or ""

    def build_reset_response(self):
        """Build the display payload that instructs the device to factory-reset.

        Uses the semantically correct firmware reset signal: status 0 with
        reset_firmware set to True. All standard display keys are included
        alongside the reset flag so the firmware can parse the response
        normally before acting on the reset instruction.
        """
        self.ensure_one()
        return {
            "status": 0,
            "filename": self.filename or "",
            "image_url": self.image_url or "",
            "refresh_rate": self.desired_refresh_rate or DEFAULT_REFRESH_RATE,
            "reset_firmware": True,
        }

    # ------------------------------------------------------------------
    # request resolution
    # ------------------------------------------------------------------

    @api.model
    def resolve_display_request(self, headers):
        """Resolve a TRMNL display poll using the configured device policy."""
        mac_address = self._normalize_mac_address(headers.get("ID"))
        api_token = self._parse_to_string(headers.get("Access-Token"))

        if not mac_address:
            return DisplayResolutionResult(
                self.browse(),
                self.build_display_error_response(),
                "missing_identity",
            )

        device = self.sudo().search([("mac_address", "=", mac_address)], limit=1)

        # Per-device reset handling (must run before any token validation)
        if device and device.reset_pending:
            reset_payload = device.build_reset_response()
            device.unlink()
            return DisplayResolutionResult(
                self.browse(),
                reset_payload,
                "reset_pending",
            )

        if not device:
            return self._resolve_unknown_display_request(
                mac_address, headers, api_token
            )

        if api_token and device._verify_api_token(api_token):
            if device.approval_state != APPROVAL_STATE_ACCEPTED:
                device._record_access_denied(reason=device.approval_state)
                return DisplayResolutionResult(
                    device,
                    self.build_display_error_response(),
                    "not_accepted",
                )

            device._apply_display_telemetry(headers)
            device._record_display_served()
            return DisplayResolutionResult(
                device,
                device.build_display_response(),
                "display",
            )

        return self._resolve_token_mismatch_display_request(
            device, headers, api_token
        )

    def _resolve_unknown_display_request(self, mac_address, headers, api_token):
        """Resolve a display request from a MAC address not yet in the database."""
        policy = self._get_display_request_policy()

        if api_token and policy == DISPLAY_POLICY_AUTO_ACCEPT:
            device, record_status = self.register_or_adopt_from_display_headers(
                headers, api_token
            )
            if device:
                device._apply_display_telemetry(headers)
                device._record_display_served()
                return DisplayResolutionResult(
                    device,
                    device.build_display_response(),
                    record_status,
                )

        if policy == DISPLAY_POLICY_FACTORY_RESET:
            return DisplayResolutionResult(
                self.browse(),
                self.build_display_error_response(status=500),
                "factory_reset",
            )

        stub_device = self.record_unknown_device_from_display(
            mac_address, api_token, headers
        )
        return DisplayResolutionResult(
            stub_device,
            self.build_display_error_response(),
            "unknown_device",
        )

    def _resolve_token_mismatch_display_request(self, device, headers, api_token):
        """Resolve a display request from a known device that presented a wrong token.

        Under the auto-accept policy the presented token is adopted and the device
        is served normally.  Under the factory-reset policy the device receives a
        reset signal (``{"status": 500}``) and its record is deleted, so the device
        must re-register from scratch.  Under the error policy the mismatch is
        recorded for manual admin review and the device receives a rejection
        response (``{"status": 202}``).
        """

        policy = self._get_display_request_policy()

        if api_token and policy == DISPLAY_POLICY_AUTO_ACCEPT:
            device._store_api_token(api_token)
            device.with_context(trmnl_allow_identity_update=True).write(
                {
                    "approval_state": APPROVAL_STATE_ACCEPTED,
                    "registration_source": "display",
                    "accepted_at": device.accepted_at or self._utc_now(),
                    "last_presented_token_hash": False,
                    "last_presented_token_salt": False,
                }
            )
            device._apply_display_telemetry(headers)
            device._record_display_served()
            return DisplayResolutionResult(
                device,
                device.build_display_response(),
                "token_adopted",
            )

        if policy == DISPLAY_POLICY_FACTORY_RESET:
            error_payload = self.build_display_error_response(status=500)
            device.unlink()
            return DisplayResolutionResult(
                self.browse(),
                error_payload,
                "factory_reset",
            )

        self.record_token_mismatch_from_display(device, api_token, headers)
        return DisplayResolutionResult(
            device,
            self.build_display_error_response(),
            "token_mismatch",
        )
