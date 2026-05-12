"""TRMNL device display request handling and response builders."""

from __future__ import annotations

import logging
from typing import NamedTuple

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

from urllib.parse import urlparse as _urlparse

from .trmnl_device import (
    APPROVAL_STATE_ACCEPTED,
    DEFAULT_DISPLAY_ERROR_STATUS,
    DEFAULT_REFRESH_RATE,
    DISPLAY_POLICY_AUTO_ACCEPT,
    DISPLAY_POLICY_FACTORY_RESET,
    _INTERNAL_HOST_RE,
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

        try:
            image_url, filename = self._resolve_display_image()
            return {
                "status": 0,
                "filename": filename,
                "image_url": image_url,
                "refresh_rate": self.desired_refresh_rate or DEFAULT_REFRESH_RATE,
            }
        except Exception:
            _logger.exception(
                "TRMNL display: build_display_response failed for device id=%s — "
                "returning device fallback fields only",
                self.id,
            )
            return {
                "status": 0,
                "filename": self.filename or "",
                "image_url": self.image_url or "",
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
                order="sequence asc, id asc",
            )

            if not profile:
                _logger.info("TRMNL display: no active profile for %s — using device fallback", device_ref)
                return self.image_url or "", self.filename or ""

            _logger.info(
                "TRMNL display: active profile id=%s name=%r sequence=%s has_preview=%s | %s",
                profile.id,
                profile.name,
                profile.sequence,
                bool(profile.preview_image),
                device_ref,
            )

            now = fields.Datetime.now()
            generated_at = profile.preview_generated_at
            interval = profile.auto_refresh_interval_minutes or 10
            threshold = (generated_at + __import__("datetime").timedelta(minutes=interval)) if generated_at else None

            _logger.info(
                "TRMNL display: poll timing profile id=%s desired_refresh_rate=%ss "
                "device_reported_refresh_rate=%s render_interval_min=%s "
                "preview_generated_at=%s next_render_at=%s now=%s",
                profile.id,
                self.desired_refresh_rate or DEFAULT_REFRESH_RATE,
                self.refresh_rate,
                interval,
                generated_at,
                threshold,
                now,
            )

            old_filename = profile._get_display_filename()
            auto_refresh_due = profile._is_auto_refresh_due()
            will_render = not profile.preview_image or auto_refresh_due

            _logger.info(
                "TRMNL display: refresh decision profile id=%s auto_refresh_due=%s "
                "has_preview_binary=%s will_render=%s old_filename=%r",
                profile.id,
                auto_refresh_due,
                bool(profile.preview_image),
                will_render,
                old_filename,
            )

            if will_render:
                _logger.info("TRMNL display: render START profile id=%s", profile.id)
                if self._is_trmnl_api_debug_enabled():
                    _logger.info(
                        "TRMNL API DEBUG display: _render_and_store_preview start profile_id=%s device_id=%s",
                        profile.id,
                        self.id,
                    )
                profile._render_and_store_preview()
                profile = profile.browse(profile.id)
                if self._is_trmnl_api_debug_enabled():
                    _logger.info(
                        "TRMNL API DEBUG display: _render_and_store_preview done profile_id=%s "
                        "preview_generated_at=%s",
                        profile.id,
                        profile.preview_generated_at,
                    )
                _logger.info(
                    "TRMNL display: render DONE profile id=%s preview_generated_at=%s",
                    profile.id,
                    profile.preview_generated_at,
                )

            image_url = profile._get_display_image_url()
            filename = profile._get_display_filename()
            _logger.info(
                "TRMNL display: filenames profile id=%s old=%r new=%r changed=%s",
                profile.id,
                old_filename,
                filename,
                old_filename != filename,
            )

            _logger.info(
                "TRMNL display: resolved profile id=%s image_url=%r filename=%r",
                profile.id,
                image_url,
                filename,
            )

            if image_url and filename:
                _logger.info(
                    "TRMNL display: serving profile image profile id=%s url=%r filename=%r",
                    profile.id,
                    image_url,
                    filename,
                )
                return image_url, filename

            _logger.warning(
                "TRMNL display: profile id=%s image_url=%r or filename=%r is empty "
                "— trmnl.public_base_url is likely not set and web.base.url is an "
                "internal address. Falling back to device default image.",
                profile.id,
                image_url,
                filename,
            )
        except Exception as exc:
            _logger.warning(
                "TRMNL display: exception resolving profile image for %s: %s",
                device_ref, exc, exc_info=True,
            )

        _logger.info(
            "TRMNL display: using device fallback image_url=%r filename=%r for %s",
            self.image_url or "", self.filename or "", device_ref,
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
    # public base URL auto-detection
    # ------------------------------------------------------------------

    @api.model
    def _maybe_auto_set_public_base_url(self, candidate_url):
        """Auto-set trmnl.public_base_url from the device's Host header if not configured."""
        params = self.env["ir.config_parameter"].sudo()
        if params.get_param("trmnl.public_base_url"):
            return
        try:
            host = _urlparse(candidate_url).hostname or ""
            if host and not _INTERNAL_HOST_RE.match(host):
                params.set_param("trmnl.public_base_url", candidate_url.rstrip("/"))
                _logger.info(
                    "TRMNL auto-set trmnl.public_base_url=%r from device Host header",
                    candidate_url,
                )
        except Exception as exc:
            _logger.debug(
                "TRMNL could not auto-set public_base_url from %r: %s",
                candidate_url, exc,
            )

    # ------------------------------------------------------------------
    # request resolution
    # ------------------------------------------------------------------

    @api.model
    def resolve_display_request(self, headers):
        """Resolve a TRMNL display poll using the configured device policy."""
        debug = self._is_trmnl_api_debug_enabled()
        policy = self._get_display_request_policy()
        mac_address = self._normalize_mac_address(headers.get("ID"))
        api_token = self._parse_to_string(headers.get("Access-Token"))

        if debug:
            _logger.info(
                "TRMNL API DEBUG display: policy=%r host=%r token_header=%s mac_normalized=%s",
                policy,
                (headers or {}).get("Host"),
                bool(api_token),
                bool(mac_address),
            )

        if not mac_address:
            if debug:
                _logger.info("TRMNL API DEBUG display: outcome=missing_identity")
            return DisplayResolutionResult(
                self.browse(),
                self.build_display_error_response(),
                "missing_identity",
            )

        device = self.sudo().search([("mac_address", "=", mac_address)], limit=1)

        # Per-device reset handling (must run before any token validation)
        if device and device.reset_pending:
            if debug:
                _logger.info("TRMNL API DEBUG display: outcome=reset_pending device_id=%s", device.id)
            reset_payload = device.build_reset_response()
            device.unlink()
            return DisplayResolutionResult(
                self.browse(),
                reset_payload,
                "reset_pending",
            )

        if not device:
            if debug:
                _logger.info("TRMNL API DEBUG display: unknown MAC — calling _resolve_unknown_display_request")
            return self._resolve_unknown_display_request(
                mac_address, headers, api_token
            )

        token_ok = bool(api_token and device._verify_api_token(api_token))
        if debug:
            _logger.info(
                "TRMNL API DEBUG display: device_id=%s approval_state=%s token_ok=%s",
                device.id,
                device.approval_state,
                token_ok,
            )

        if token_ok:
            if device.approval_state != APPROVAL_STATE_ACCEPTED:
                if debug:
                    _logger.info("TRMNL API DEBUG display: outcome=not_accepted state=%s", device.approval_state)
                device._record_access_denied(reason=device.approval_state)
                return DisplayResolutionResult(
                    device,
                    self.build_display_error_response(),
                    "not_accepted",
                )

            device._apply_display_telemetry(headers)
            device._record_display_served()
            if debug:
                _logger.info("TRMNL API DEBUG display: outcome=display device_id=%s", device.id)
            return DisplayResolutionResult(
                device,
                device.build_display_response(),
                "display",
            )

        if debug:
            _logger.info("TRMNL API DEBUG display: token mismatch path device_id=%s", device.id)
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
