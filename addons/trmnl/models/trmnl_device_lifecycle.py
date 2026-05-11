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
    TRMNL_POLICY_PARAM,
)


class TrmnlDeviceLifecycleMixin(models.Model):
    """Extend TRMNL devices with setup, registration, and lifecycle helpers.

    Responsibilities
    ----------------
    - Display-policy read/write/consume helpers.
    - Device registration from /api/setup headers.
    - Stub-record creation for unknown devices arriving via /api/display.
    - Token-mismatch recording for known devices that present a wrong token.
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
            TRMNL_POLICY_PARAM,
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
            TRMNL_POLICY_PARAM,
            policy,
        )

    # ------------------------------------------------------------------
    # /api/setup registration
    # ------------------------------------------------------------------

    @api.model
    def upsert_from_setup_headers(self, headers):
        """Create a device from setup headers or fail if the MAC already exists.

        Returns a tuple of (device, raw_token, record_status).
        """
        mac_address = self._normalize_mac_address(headers.get("ID"))
        if not mac_address:
            raise ValidationError(_("TRMNL setup request is missing a valid ID header."))

        existing_device = self.sudo().search([("mac_address", "=", mac_address)], limit=1)
        if existing_device:
            # Allow re-registration for stub records (unknown_device) created by an
            # unanswered display poll — the device was never properly registered on this
            # server and setup is the correct way to claim it.
            # Also allow when reset_pending is set (admin-initiated factory reset).
            if existing_device.reset_pending or existing_device.approval_state == APPROVAL_STATE_UNKNOWN_DEVICE:
                existing_device.with_context(trmnl_allow_identity_update=True).unlink()
            else:
                raise ValidationError(_("TRMNL device with this MAC address is already registered."))

        firmware_version = self._parse_to_string(headers.get("FW-Version"))
        now_value = fields.Datetime.now()
        raw_token, token_values = self._build_api_token_material()

        create_values = {
            "mac_address": mac_address,
            "friendly_id": self._generate_unique_friendly_id(),
            "approval_state": APPROVAL_STATE_ACCEPTED,
            "registration_source": "setup",
            "first_seen_at": now_value,
            "last_seen_at": now_value,
            "last_setup_at": now_value,
            "accepted_at": now_value,
            "setup_request_count": 1,
        }
        if firmware_version is not False:
            create_values["firmware_version"] = firmware_version

        create_values.update(token_values)
        device = self.sudo().create(create_values)
        return device, raw_token, "created"

    # ------------------------------------------------------------------
    # /api/display stub-record creation (error policy)
    # ------------------------------------------------------------------

    @api.model
    def record_unknown_device_from_display(self, mac_address, presented_token, headers):
        """Create a minimal stub record for a previously unseen MAC address.

        Called under the error policy so that the admin can review and
        manually accept the device.  The presented token is stored as a
        hashed value so it can be promoted on manual acceptance.

        No friendly_id is assigned because that is only issued during
        /api/setup; the device already has one stored on-board.

        Returns the newly created device record.
        """
        firmware_version = self._parse_to_string(headers.get("FW-Version"))
        now_value = fields.Datetime.now()

        create_values = {
            "mac_address": mac_address,
            "approval_state": APPROVAL_STATE_UNKNOWN_DEVICE,
            "registration_source": "display",
            "first_seen_at": now_value,
            "last_seen_at": now_value,
        }
        if firmware_version is not False:
            create_values["firmware_version"] = firmware_version

        if presented_token:
            create_values.update(self._hash_presented_token(presented_token))

        return self.sudo().create(create_values)

    @api.model
    def record_token_mismatch_from_display(self, device, presented_token, headers):
        """Update a known device record to reflect a token-mismatch display attempt.

        Stores the presented token (hashed) for later manual acceptance and
        bumps the access-denied counters.
        """
        now_value = fields.Datetime.now()
        update_values = {
            "approval_state": APPROVAL_STATE_TOKEN_MISMATCH,
            "last_seen_at": now_value,
            "last_access_denied_at": now_value,
            "invalid_token_count": (device.invalid_token_count or 0) + 1,
        }
        firmware_version = self._parse_to_string(headers.get("FW-Version"))
        if firmware_version is not False:
            update_values["firmware_version"] = firmware_version

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

        Used exclusively by the auto-accept policy path.  Returns a tuple of
        (device, record_status).
        """
        mac_address = self._normalize_mac_address(headers.get("ID"))
        token_value = self._parse_to_string(api_token)

        if not mac_address or not token_value:
            return self.browse(), "missing_identity"

        firmware_version = self._parse_to_string(headers.get("FW-Version"))
        now_value = fields.Datetime.now()

        device = self.sudo().search([("mac_address", "=", mac_address)], limit=1)

        if device:
            update_values = {
                "approval_state": APPROVAL_STATE_ACCEPTED,
                "registration_source": "display",
                "accepted_at": device.accepted_at or now_value,
                "last_seen_at": now_value,
                "last_presented_token_hash": False,
                "last_presented_token_salt": False,
            }
            if firmware_version is not False:
                update_values["firmware_version"] = firmware_version

            update_values.update(self._hash_api_token(token_value))
            device.with_context(trmnl_allow_identity_update=True).write(update_values)
            return device, "updated"

        create_values = {
            "mac_address": mac_address,
            "approval_state": APPROVAL_STATE_ACCEPTED,
            "registration_source": "display",
            "first_seen_at": now_value,
            "last_seen_at": now_value,
            "accepted_at": now_value,
        }
        if firmware_version is not False:
            create_values["firmware_version"] = firmware_version

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
        since the stub record was created).

        A friendly_id is generated here for unknown_device records that never
        went through /api/setup, so the admin can identify the device in the UI.
        The device itself will not use this server-generated ID because it
        already has its own stored ID from its original /api/setup call against
        whichever server it was previously paired with.
        """
        self.ensure_one()
        self._promote_presented_token_to_accepted()

        now_value = fields.Datetime.now()
        update_values = {
            "approval_state": APPROVAL_STATE_ACCEPTED,
            "accepted_at": now_value,
            "last_seen_at": now_value,
        }

        if not self.friendly_id:
            update_values["friendly_id"] = self._generate_unique_friendly_id()

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
            "friendly_id": self.friendly_id,
            "image_url": self.image_url or "",
        }
