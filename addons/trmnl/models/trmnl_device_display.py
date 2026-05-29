"""TRMNL device display request handling and response builders."""

from __future__ import annotations

import logging
from typing import NamedTuple
from urllib.parse import urlparse as _urlparse

from odoo import api, fields, models

from .trmnl_device import (
    APPROVAL_STATE_ACCEPTED,
    APPROVAL_STATE_UNKNOWN_DEVICE,
    DEFAULT_REFRESH_RATE,
    DISPLAY_POLICY_AUTO_ACCEPT,
    DISPLAY_POLICY_FACTORY_RESET,
    LAST_API_CALL_DISPLAY,
    UNAUTHORIZED_IMAGE_FILENAME,
    UNAUTHORIZED_IMAGE_STATIC_PATH,
    _INTERNAL_HOST_RE,
    client_can_reach_host,
    is_device_reachable_base_url,
)
from .trmnl_image import UNAUTHORIZED_IMAGE_CONFIG_KEY

_logger = logging.getLogger(__name__)


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

    _POLL_CONTEXT_KEYS = ("trmnl_poll_base_url", "trmnl_client_ip", "trmnl_access_token")

    def _poll_context(self):
        """Return poll-scoped context keys for profile URL/render helpers."""
        return {
            key: self.env.context[key]
            for key in self._POLL_CONTEXT_KEYS
            if key in self.env.context
        }

    def _profile_model_for_poll(self):
        """``trmnl.profile`` model accessor with device poll context applied."""
        return self.env["trmnl.profile"].sudo().with_context(**self._poll_context())

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
            profile = self._profile_model_for_poll().search(
                [("device_id", "=", self.id), ("active", "=", True)],
                limit=1,
                order="sequence asc, id asc",
            )

            if not profile:
                _logger.info("TRMNL display: no active profile for %s — using device fallback", device_ref)
                return self.image_url or "", self.filename or ""

            _logger.debug(
                "TRMNL display: active profile id=%s name=%r sequence=%s has_preview=%s | %s",
                profile.id,
                profile.name,
                profile.sequence,
                bool(profile.preview_image),
                device_ref,
            )

            will_render = profile._should_render_for_device()
            renderer_stale = profile._is_preview_renderer_stale()

            _logger.debug(
                "TRMNL display: refresh decision profile id=%s will_render=%s "
                "renderer_stale=%s",
                profile.id,
                will_render,
                renderer_stale,
            )

            if will_render:
                _logger.info("TRMNL display: rendering profile id=%s", profile.id)
                profile._render_and_store_preview()
                profile.invalidate_recordset()
                _logger.info(
                    "TRMNL display: render done profile id=%s generated_at=%s",
                    profile.id,
                    profile.preview_generated_at,
                )

            image_url = profile._get_display_image_url()
            filename = profile._get_display_filename()
            _logger.debug(
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
                if self.image_url != image_url or self.filename != filename:
                    self.sudo().write({"image_url": image_url, "filename": filename})
                return image_url, filename

            _logger.warning(
                "TRMNL display: profile id=%s image_url=%r or filename=%r is empty "
                "— no device-reachable base URL could be resolved. Falling back to "
                "device default image.",
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
        fallback_url = self.image_url or ""
        if profile and fallback_url and "/api/profile/image/" in fallback_url:
            digest = profile._preview_png_digest()
            query = profile._build_profile_image_query(version=digest)
            if query and "access_token=" not in fallback_url:
                parsed = _urlparse(fallback_url)
                fallback_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{query}"
        return fallback_url, self.filename or ""

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
    # public base URL auto-detection
    # ------------------------------------------------------------------

    @api.model
    def _maybe_auto_set_public_base_url(self, candidate_url, client_ip=None):
        """Auto-set trmnl.public_base_url from the device's Host header when needed.

        Skips when the Host is on a different private network than the device
        (e.g. Host 10.x while the device polls from 192.168.x). Does nothing if
        trmnl.public_base_url is already set, or if web.base.url is already
        device-reachable on the same LAN as the client.
        """
        params = self.env["ir.config_parameter"].sudo()
        if params.get_param("trmnl.public_base_url"):
            return

        web_url = params.get_param("web.base.url", "").strip()
        if web_url:
            try:
                web_host = _urlparse(web_url).hostname or ""
                if web_host and not _INTERNAL_HOST_RE.match(web_host):
                    if not client_ip or client_can_reach_host(client_ip, web_host):
                        _logger.debug(
                            "TRMNL skip auto-set: web.base.url=%r is already device-reachable",
                            web_url,
                        )
                        return
            except Exception:
                pass

        try:
            host = _urlparse(candidate_url).hostname or ""
            if not host or _INTERNAL_HOST_RE.match(host):
                return
            if client_ip and not client_can_reach_host(client_ip, host):
                _logger.info(
                    "TRMNL skip auto-set: Host %r is not on the same LAN as device %s",
                    candidate_url,
                    client_ip,
                )
                return
            params.set_param("trmnl.public_base_url", candidate_url.rstrip("/"))
            _logger.info(
                "TRMNL auto-set trmnl.public_base_url=%r from device Host header "
                "(web.base.url is not device-reachable)",
                candidate_url,
            )
        except Exception as exc:
            _logger.debug(
                "TRMNL could not auto-set public_base_url from %r: %s",
                candidate_url, exc,
            )

    @api.model
    def _sync_public_base_url_from_poll(self, poll_base_url, client_ip=None):
        """Align trmnl.public_base_url with how devices actually reach Odoo.

        Corrects stale values (e.g. a VPN/campus 10.x address saved earlier while
        TRMNL devices poll over 192.168.x).
        """
        Profile = self.env["trmnl.profile"]
        poll = (poll_base_url or "").strip().rstrip("/")
        if not poll or not is_device_reachable_base_url(poll):
            return

        host = _urlparse(poll).hostname or ""
        if client_ip and host and not client_can_reach_host(client_ip, host):
            base, _source = Profile.with_context(
                trmnl_poll_base_url="",
                trmnl_client_ip=client_ip,
            )._resolve_device_base_url()
            if not base:
                return
            poll = base.rstrip("/")
            host = _urlparse(poll).hostname or ""
            if client_ip and host and not client_can_reach_host(client_ip, host):
                return

        params = self.env["ir.config_parameter"].sudo()
        current = params.get_param("trmnl.public_base_url", "").strip().rstrip("/")
        if current != poll:
            params.set_param("trmnl.public_base_url", poll)
            _logger.info(
                "TRMNL synced trmnl.public_base_url to %r from device poll (was %r)",
                poll,
                current or "(unset)",
            )

    # ------------------------------------------------------------------
    # request resolution
    # ------------------------------------------------------------------

    def _display_factory_reset_result(self, device=None):
        """Delete *device* when given and return the firmware factory-reset payload."""
        if device:
            device.unlink()
        return DisplayResolutionResult(
            self.browse(),
            {"status": 500},
            "factory_reset",
        )

    def _display_error_policy_result(self, device, record_status):
        """Return the seeded unauthorized-image payload for policy ``error``."""
        return DisplayResolutionResult(
            device,
            self.build_display_error_response(),
            record_status,
        )

    def _display_serve_accepted(self, device, headers, record_status):
        """Apply poll telemetry and return the normal display payload."""
        device = device.with_context(**self._poll_context())
        device._apply_display_telemetry(headers)
        device._record_display_served()
        return DisplayResolutionResult(
            device,
            device.build_display_response(),
            record_status,
        )

    @api.model
    def resolve_display_request(self, headers):
        """Resolve a TRMNL display poll using the configured device policy."""
        api_token = self._parse_to_string(headers.get("Access-Token"))
        if api_token:
            self = self.with_context(trmnl_access_token=api_token)

        debug = self._is_trmnl_api_debug_enabled()
        policy = self._get_display_request_policy()
        mac_address = self._normalize_mac_address(headers.get("ID"))

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

        # Per-device reset handling (runs before any other checks).
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

        if device and device.approval_state == APPROVAL_STATE_UNKNOWN_DEVICE:
            return self._resolve_known_unknown_device_display_request(
                device, headers, api_token
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
                device.with_context(trmnl_allow_identity_update=True).write(
                    {
                        "last_seen_at": fields.Datetime.now(),
                        "last_api_call": LAST_API_CALL_DISPLAY,
                    }
                )
                return DisplayResolutionResult(
                    device,
                    self.build_display_error_response(),
                    "not_accepted",
                )

            device = device.with_context(**self._poll_context())
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
                return self._display_serve_accepted(
                    promoted_device, headers, record_status
                )

        if policy == DISPLAY_POLICY_FACTORY_RESET:
            return self._display_factory_reset_result(device)

        # Error policy (default): refresh the record for admin review.
        self.record_unknown_device_from_display(
            device.mac_address, api_token, headers
        )
        return self._display_error_policy_result(device, "unknown_device")

    def _resolve_unknown_display_request(self, mac_address, headers, api_token):
        """Resolve a display request from a MAC address not yet in the database."""
        policy = self._get_display_request_policy()

        if api_token and policy == DISPLAY_POLICY_AUTO_ACCEPT:
            device, record_status = self.register_or_adopt_from_display_headers(
                headers, api_token
            )
            if device:
                return self._display_serve_accepted(device, headers, record_status)

        if policy == DISPLAY_POLICY_FACTORY_RESET:
            return self._display_factory_reset_result()

        # Error policy: create a full record so the admin can review and
        # manually accept the device; serve the error image to the device.
        stub_device = self.record_unknown_device_from_display(
            mac_address, api_token, headers
        )
        return self._display_error_policy_result(stub_device, "unknown_device")

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
                "added_at": self._utc_now(),
                "last_seen_at": fields.Datetime.now(),
                "last_api_call": LAST_API_CALL_DISPLAY,
                "last_presented_token_hash": False,
                "last_presented_token_salt": False,
            }
            update_values.update(self._default_image_field_values())
            device.with_context(trmnl_allow_identity_update=True).write(update_values)
            return self._display_serve_accepted(device, headers, "token_adopted")

        if policy == DISPLAY_POLICY_FACTORY_RESET:
            return self._display_factory_reset_result(device)

        # Error policy: record the mismatch for admin review and serve the
        # error image so the device has something to display.
        self.record_token_mismatch_from_display(device, api_token, headers)
        return self._display_error_policy_result(device, "token_mismatch")
