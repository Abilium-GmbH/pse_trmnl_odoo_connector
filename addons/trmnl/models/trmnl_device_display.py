"""TRMNL device display request handling and response builders."""

from __future__ import annotations

from typing import NamedTuple

from odoo import api, models

from .trmnl_device import (
    APPROVAL_STATE_ACCEPTED,
    APPROVAL_STATE_UNKNOWN_DEVICE,
    DEFAULT_REFRESH_RATE,
    DISPLAY_POLICY_AUTO_ACCEPT,
    DISPLAY_POLICY_FACTORY_RESET,
    UNAUTHORIZED_IMAGE_FILENAME,
    UNAUTHORIZED_IMAGE_STATIC_PATH,
)
from .trmnl_image import UNAUTHORIZED_IMAGE_CONFIG_KEY


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

        State machine contract
        ----------------------
        ``unknown_device`` records are handled entirely separately from token
        validation.  Token checking (and the ``token_mismatch`` state) only ever
        applies to devices that are currently in the ``accepted`` or
        ``token_mismatch`` state, both of which imply that the device was
        previously registered with a known API token stored in the accepted-token
        slot (``api_token_hash`` / ``api_token_salt``).  A device in the
        ``unknown_device`` state stores any presented token only in the
        presented-token slot (``last_presented_token_hash`` /
        ``last_presented_token_salt``); the accepted-token slot is always empty,
        so token verification via ``_verify_api_token`` is meaningless and is
        never attempted.

        Request resolution follows this decision tree for each incoming poll:

        1. MAC address missing
            → error-image response, no record touched.
        2. Per-device reset_pending flag set
            → reset signal, record deleted.
        3. MAC known, device is ``unknown_device``
            → _resolve_known_unknown_device_display_request (policy-driven).
                error:         refresh record, serve error image.
                auto_accept:   promote record to accepted, serve display payload.
                factory_reset: delete record, return {"status": 500}.
        4. MAC unknown (no DB record)
            → _resolve_unknown_display_request (policy-driven).
        5. MAC known, device is ``accepted`` or ``token_mismatch``, token valid
            → serve display (if ``accepted``); serve error image (if
                ``token_mismatch`` — manual or auto-accept required to restore).
        6. MAC known, device is ``accepted`` or ``token_mismatch``, token invalid
            → _resolve_token_mismatch_display_request (policy-driven).
        """

    _inherit = "trmnl.device"

    # ------------------------------------------------------------------
    # response builders
    # ------------------------------------------------------------------

    def build_display_error_response(self):
        """Build the payload returned when a display request cannot be served.

        Returns a full display-shaped payload using the seeded error image URL
        (resolved via ``web.base.url``) and the default refresh rate so the
        device always has something to render.  Falls back to the static asset
        path when the attachment URL is not yet available.

        This response is used for the error policy (unknown device and token
        mismatch); the factory-reset path returns ``{"status": 500}`` directly.
        """
        unauthorized_image_url = (
            self.env["trmnl.image.seeder"].get_image_url(UNAUTHORIZED_IMAGE_CONFIG_KEY)
            or UNAUTHORIZED_IMAGE_STATIC_PATH
        )
        return {
            "status": 0,
            "filename": UNAUTHORIZED_IMAGE_FILENAME,
            "image_url": unauthorized_image_url,
            "refresh_rate": DEFAULT_REFRESH_RATE,
        }

    def build_display_response(self):
        """Build the normal display payload for an accepted device."""
        self.ensure_one()
        return {
            "status": 0,
            "filename": self.filename or "",
            "image_url": self.image_url or "",
            "refresh_rate": self.desired_refresh_rate or DEFAULT_REFRESH_RATE,
        }

    def build_reset_response(self):
        """Build the display payload that instructs the device to factory-reset.

        Uses the semantically correct firmware reset signal: status 0 with
        reset_firmware set to True.  All standard display keys are included
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

        # Per-device reset handling (runs before any other checks).
        if device and device.reset_pending:
            reset_payload = device.build_reset_response()
            device.unlink()
            return DisplayResolutionResult(
                self.browse(),
                reset_payload,
                "reset_pending",
            )

        if device and device.approval_state == APPROVAL_STATE_UNKNOWN_DEVICE:
            return self._resolve_known_unknown_device_display_request(
                device, headers, api_token
            )

        if not device:
            return self._resolve_unknown_display_request(
                mac_address, headers, api_token
            )

        # At this point the device exists and is either ``accepted`` or
        # ``token_mismatch`` — both states have an accepted token on file.
        if api_token and device._verify_api_token(api_token):
            if device.approval_state != APPROVAL_STATE_ACCEPTED:
                # token_mismatch device presenting the correct token: the device
                # must be explicitly re-accepted (manual or auto-accept) before
                # it is served display content again.
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

    def _resolve_known_unknown_device_display_request(self, device, headers, api_token):
        """Handle a display poll from a device whose record is in ``unknown_device`` state.

        Consults the current display policy so that a policy change takes effect
        immediately, even for devices that already have a stub record:

        - ``error``        — Update telemetry and the presented token on the existing
                             record; return the error image unconditionally.
        - ``auto_accept``  — Promote the stub record to ``accepted`` by adopting the
                             presented token; serve the normal display payload.
        - ``factory_reset``— Delete the stub record and return the reset signal
                             (``{"status": 500}``), consistent with the first-seen
                             factory-reset path.

        Token validation is never performed for ``unknown_device`` records;
        ``token_mismatch`` is never set from this path.
        """
        policy = self._get_display_request_policy()

        if policy == DISPLAY_POLICY_AUTO_ACCEPT and api_token:
            promoted_device, record_status = self.register_or_adopt_from_display_headers(
                headers, api_token
            )
            if promoted_device:
                promoted_device._apply_display_telemetry(headers)
                promoted_device._record_display_served()
                return DisplayResolutionResult(
                    promoted_device,
                    promoted_device.build_display_response(),
                    record_status,
                )

        if policy == DISPLAY_POLICY_FACTORY_RESET:
            device.unlink()
            return DisplayResolutionResult(
                self.browse(),
                {"status": 500},
                "factory_reset",
            )

        # Error policy (default): refresh the record for admin review.
        self.record_unknown_device_from_display(
            device.mac_address, api_token, headers
        )
        return DisplayResolutionResult(
            device,
            self.build_display_error_response(),
            "unknown_device",
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
                {"status": 500},
                "factory_reset",
            )

        # Error policy: create a full record so the admin can review and
        # manually accept the device; serve the error image to the device.
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

        Only called for devices in the ``accepted`` or ``token_mismatch`` state.
        Under the auto-accept policy the presented token is adopted and the
        device is served normally.  Under the factory-reset policy the device
        receives a reset signal (``{"status": 500}``) and its record is deleted,
        so the device must re-register from scratch.  Under the error policy
        the mismatch is recorded for manual admin review and the device receives
        the error image.
        """
        policy = self._get_display_request_policy()

        if api_token and policy == DISPLAY_POLICY_AUTO_ACCEPT:
            device._store_api_token(api_token)
            update_values = {
                "approval_state": APPROVAL_STATE_ACCEPTED,
                "registration_source": "display",
                "added_at": self._utc_now(),
                "last_presented_token_hash": False,
                "last_presented_token_salt": False,
            }
            update_values.update(self._default_image_field_values())
            device.with_context(trmnl_allow_identity_update=True).write(update_values)
            device._apply_display_telemetry(headers)
            device._record_display_served()
            return DisplayResolutionResult(
                device,
                device.build_display_response(),
                "token_adopted",
            )

        if policy == DISPLAY_POLICY_FACTORY_RESET:
            device.unlink()
            return DisplayResolutionResult(
                self.browse(),
                {"status": 500},
                "factory_reset",
            )

        # Error policy: record the mismatch for admin review and serve the
        # error image so the device has something to display.
        self.record_token_mismatch_from_display(device, api_token, headers)
        return DisplayResolutionResult(
            device,
            self.build_display_error_response(),
            "token_mismatch",
        )
