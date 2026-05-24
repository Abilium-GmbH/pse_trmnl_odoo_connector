"""TRMNL device registration and lifecycle helpers."""

from __future__ import annotations

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .trmnl_device import (
    APPROVAL_STATE_ACCEPTED,
    APPROVAL_STATE_TOKEN_MISMATCH,
    APPROVAL_STATE_UNKNOWN_DEVICE,
    DISPLAY_POLICY_AUTO_ACCEPT,
    DISPLAY_POLICY_ERROR,
    DISPLAY_POLICY_FACTORY_RESET,
)


class TrmnlDeviceLifecycleMixin(models.Model):
    """Extend TRMNL devices with setup, registration, and lifecycle helpers.

    Responsibilities
    ----------------
    - Display-policy read/write helpers.
    - Device registration from /api/setup headers.
    - Full record upsert for unknown devices arriving via /api/display.
    - Token-mismatch recording for accepted devices that present a wrong token.
    - Auto-register/adopt path used by the auto-accept policy.
    - Manual accept logic invoked from the accept wizard.
    - Setup and display error/success response builders.
    """

    _inherit = "trmnl.device"

    # ------------------------------------------------------------------
    # display policy
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # /api/setup registration
    # ------------------------------------------------------------------

    @api.model
    def upsert_from_setup_headers(self, headers):
        """Create a device from setup headers or fail if the MAC already exists.

        A device registered via /api/setup is immediately placed in the
        ``accepted`` state with a freshly generated API token.  ``added_at``
        is set to the creation timestamp.

        Returns a tuple of (device, raw_token, record_status).
        """
        mac_address = self._normalize_mac_address(headers.get("ID"))
        if not mac_address:
            raise ValidationError(_("TRMNL setup request is missing a valid ID header."))

        existing_device = self.sudo().search([("mac_address", "=", mac_address)], limit=1)
        if existing_device:
            if existing_device.reset_pending:
                existing_device.with_context(trmnl_allow_identity_update=True).write({
                    "reset_pending": False
                })
                existing_device.unlink()
            else:
                raise ValidationError(
                    _("TRMNL device with this MAC address is already registered.")
                )

        firmware_version = self._parse_to_string(headers.get("FW-Version"))
        now_value = fields.Datetime.now()
        raw_token, token_values = self._build_api_token_material()

        create_values = {
            "mac_address": mac_address,
            "approval_state": APPROVAL_STATE_ACCEPTED,
            "registration_source": "setup",
            "first_seen_at": now_value,
            "last_seen_at": now_value,
            "added_at": now_value,
        }
        if firmware_version is not False:
            create_values["firmware_version"] = firmware_version

        create_values.update(token_values)
        device = self.sudo().create(create_values)
        return device, raw_token, "created"

    # ------------------------------------------------------------------
    # /api/display unknown-device upsert (error policy)
    # ------------------------------------------------------------------

    @api.model
    def record_unknown_device_from_display(self, mac_address, presented_token, headers):
        """Upsert a full device record for an unknown MAC address.

        Called under the error policy (and when re-polling an existing
        ``unknown_device`` record) so that the admin can review and manually
        accept the device from the list view.

        If a record for ``mac_address`` already exists in the ``unknown_device``
        state, it is updated in place (telemetry refreshed, presented token
        overwritten).  Creating a duplicate record is never correct: the unique
        MAC constraint would raise, and the admin would lose the previously
        stored telemetry context.

        If no record exists, a new one is created with all available telemetry
        from the display headers.

        ``added_at`` is intentionally left unset because the device has not yet
        been accepted.

        Returns the created-or-updated device record.
        """
        now_value = fields.Datetime.now()
        existing_device = self.sudo().search(
            [("mac_address", "=", mac_address)], limit=1
        )

        if existing_device:
            update_values = {"last_seen_at": now_value}
            self._apply_telemetry_to_values(update_values, headers)
            if presented_token:
                update_values.update(self._hash_presented_token(presented_token))
            existing_device.with_context(trmnl_allow_identity_update=True).write(update_values)
            return existing_device

        create_values = {
            "mac_address": mac_address,
            "approval_state": APPROVAL_STATE_UNKNOWN_DEVICE,
            "registration_source": "display",
            "first_seen_at": now_value,
            "last_seen_at": now_value,
        }
        self._apply_telemetry_to_values(create_values, headers)
        if presented_token:
            create_values.update(self._hash_presented_token(presented_token))

        return self.sudo().create(create_values)

    @api.model
    def _apply_telemetry_to_values(self, values, headers):
        """Merge parsed telemetry from display headers into a values dict in place.

        Only fields whose parsed value is not ``False`` are written, so
        missing or unparseable headers do not overwrite existing data with
        empty values.
        """
        telemetry_map = {
            "firmware_version": self._parse_to_string(headers.get("FW-Version")),
            "refresh_rate": self._parse_to_int(headers.get("Refresh-Rate")),
            "battery_voltage": self._parse_to_float(headers.get("Battery-Voltage")),
            "rssi_dbm": self._parse_to_int(headers.get("RSSI")),
            "display_width": self._parse_to_int(headers.get("Width")),
            "display_height": self._parse_to_int(headers.get("Height")),
        }
        for field_name, parsed_value in telemetry_map.items():
            if parsed_value is not False:
                values[field_name] = parsed_value

    @api.model
    def record_token_mismatch_from_display(self, device, presented_token, headers):
        """Update a known device record to reflect a token-mismatch display attempt.

        Only called for devices in the ``accepted`` or ``token_mismatch`` state.
        Stores the presented token hashed for later manual acceptance and bumps
        the access-denied counters.
        """
        now_value = fields.Datetime.now()
        update_values = {
            "approval_state": APPROVAL_STATE_TOKEN_MISMATCH,
            "last_seen_at": now_value,
            "last_access_denied_at": now_value,
            "invalid_token_count": (device.invalid_token_count or 0) + 1,
        }

        self._apply_telemetry_to_values(update_values, headers)

        if presented_token:
            update_values.update(self._hash_presented_token(presented_token))

        device.with_context(trmnl_allow_identity_update=True).write(update_values)
        return device

    # ------------------------------------------------------------------
    # /api/display auto-accept registration
    # ------------------------------------------------------------------

    @api.model
    def register_or_adopt_from_display_headers(self, headers, api_token):
        """Register a device from display headers by adopting the presented token.

        Used exclusively by the auto-accept policy path.  ``added_at`` is set
        to the acceptance timestamp.

        Returns a tuple of (device, record_status).
        """
        mac_address = self._normalize_mac_address(headers.get("ID"))
        token_value = self._parse_to_string(api_token)

        if not mac_address or not token_value:
            return self.browse(), "missing_identity"

        now_value = fields.Datetime.now()
        device = self.sudo().search([("mac_address", "=", mac_address)], limit=1)

        if device:
            update_values = {
                "approval_state": APPROVAL_STATE_ACCEPTED,
                "registration_source": "display",
                "added_at": now_value,
                "last_seen_at": now_value,
                "last_presented_token_hash": False,
                "last_presented_token_salt": False,
            }
            self._apply_telemetry_to_values(update_values, headers)
            update_values.update(self._hash_api_token(token_value))
            device.with_context(trmnl_allow_identity_update=True).write(update_values)
            return device, "updated"

        create_values = {
            "mac_address": mac_address,
            "approval_state": APPROVAL_STATE_ACCEPTED,
            "registration_source": "display",
            "first_seen_at": now_value,
            "last_seen_at": now_value,
            "added_at": now_value,
        }
        self._apply_telemetry_to_values(create_values, headers)
        create_values.update(self._hash_api_token(token_value))
        device = self.sudo().create(create_values)
        return device, "created"

    # ------------------------------------------------------------------
    # manual accept
    # ------------------------------------------------------------------

    def accept_device(self):
        """Promote this device to ``accepted`` by adopting its last presented token.

        Called from ``TrmnlDeviceAcceptWizard``.  The device must have a stored
        presented token (i.e. it must have attempted at least one display poll
        since the record was created).  ``added_at`` is set to the acceptance
        timestamp.
        """
        self.ensure_one()
        self._promote_presented_token_to_accepted()

        now_value = fields.Datetime.now()
        update_values = {
            "approval_state": APPROVAL_STATE_ACCEPTED,
            "added_at": now_value,
            "last_seen_at": now_value,
        }

        self.with_context(trmnl_allow_identity_update=True).write(update_values)
        return self

    # ------------------------------------------------------------------
    # response builders
    # ------------------------------------------------------------------

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
            "image_url": self.image_url or "",
        }
