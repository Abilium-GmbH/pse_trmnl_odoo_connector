"""TRMNL API token and identity security helpers."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets

from odoo import api, models

from .trmnl_device import API_TOKEN_BYTES, API_TOKEN_PBKDF2_ITERATIONS


class TrmnlDeviceSecurityMixin(models.Model):
    """Extend TRMNL devices with API token handling helpers.

    Two distinct token slots are managed here:

    api_token_hash / api_token_salt
        The accepted, authoritative token for the device.  Written once
        during /api/setup (or when an admin manually accepts the device).

    last_presented_token_hash / last_presented_token_salt
        The most-recent token that the device presented in a /api/display
        call but that did not match the accepted token.  Stored so that an
        admin can promote it to the accepted token via the accept wizard.
        Uses the same PBKDF2 scheme so the raw token is never persisted in
        plain text.
    """

    _inherit = "trmnl.device"

    # ------------------------------------------------------------------
    # accepted token helpers
    # ------------------------------------------------------------------

    @api.model
    def _generate_api_token(self):
        """Generate a new raw API token."""
        return secrets.token_urlsafe(API_TOKEN_BYTES)

    @api.model
    def _hash_api_token(self, raw_token):
        """Return the persisted hash material for an API token."""
        salt_bytes = secrets.token_bytes(16)
        token_hash_bytes = hashlib.pbkdf2_hmac(
            "sha256",
            raw_token.encode("utf-8"),
            salt_bytes,
            API_TOKEN_PBKDF2_ITERATIONS,
        )

        return {
            "api_token_hash": base64.b64encode(token_hash_bytes).decode("ascii"),
            "api_token_salt": base64.b64encode(salt_bytes).decode("ascii"),
        }

    @api.model
    def _build_api_token_material(self):
        """Return a raw token together with its persisted hash material."""
        raw_token = self._generate_api_token()
        return raw_token, self._hash_api_token(raw_token)

    def _verify_api_token(self, raw_token):
        """Verify a token against the persisted accepted-token hash material."""
        self.ensure_one()

        if not raw_token or not self.api_token_hash or not self.api_token_salt:
            return False

        try:
            salt_bytes = base64.b64decode(self.api_token_salt.encode("ascii"))
            expected_hash = base64.b64decode(self.api_token_hash.encode("ascii"))
        except (ValueError, TypeError, binascii.Error):
            return False

        actual_hash = hashlib.pbkdf2_hmac(
            "sha256",
            raw_token.encode("utf-8"),
            salt_bytes,
            API_TOKEN_PBKDF2_ITERATIONS,
        )
        return hmac.compare_digest(actual_hash, expected_hash)

    def _store_api_token(self, raw_token):
        """Persist a raw token as the accepted token on the current record."""
        self.ensure_one()
        token_values = self._hash_api_token(raw_token)
        self.with_context(trmnl_allow_identity_update=True).write(token_values)
        return self

    @api.model
    def find_by_mac_and_token(self, mac_address, api_token):
        """Return a device that matches the MAC address and raw accepted token."""
        normalized_mac_address = self._normalize_mac_address(mac_address)
        normalized_token = self._parse_to_string(api_token)

        if not normalized_mac_address or not normalized_token:
            return self.browse()

        device = self.sudo().search([("mac_address", "=", normalized_mac_address)], limit=1)
        if device and device._verify_api_token(normalized_token):
            return device

        return self.browse()

    # ------------------------------------------------------------------
    # last-presented token helpers
    # ------------------------------------------------------------------

    @api.model
    def _hash_presented_token(self, raw_token):
        """Return the persisted hash material for a presented-but-not-yet-accepted token."""
        salt_bytes = secrets.token_bytes(16)
        token_hash_bytes = hashlib.pbkdf2_hmac(
            "sha256",
            raw_token.encode("utf-8"),
            salt_bytes,
            API_TOKEN_PBKDF2_ITERATIONS,
        )
        return {
            "last_presented_token_hash": base64.b64encode(token_hash_bytes).decode("ascii"),
            "last_presented_token_salt": base64.b64encode(salt_bytes).decode("ascii"),
        }

    def _store_presented_token(self, raw_token):
        """Persist a raw presented token (hashed) on the current record."""
        self.ensure_one()
        presented_values = self._hash_presented_token(raw_token)
        self.with_context(trmnl_allow_identity_update=True).write(presented_values)
        return self

    def _verify_presented_token(self, raw_token):
        """Verify a token against the stored last-presented token hash material."""
        self.ensure_one()

        if (
            not raw_token
            or not self.last_presented_token_hash
            or not self.last_presented_token_salt
        ):
            return False

        try:
            salt_bytes = base64.b64decode(self.last_presented_token_salt.encode("ascii"))
            expected_hash = base64.b64decode(self.last_presented_token_hash.encode("ascii"))
        except (ValueError, TypeError, binascii.Error):
            return False

        actual_hash = hashlib.pbkdf2_hmac(
            "sha256",
            raw_token.encode("utf-8"),
            salt_bytes,
            API_TOKEN_PBKDF2_ITERATIONS,
        )
        return hmac.compare_digest(actual_hash, expected_hash)

    def _promote_presented_token_to_accepted(self):
        """Promote the last-presented token to the accepted token slot.

        Copies ``last_presented_token_hash/salt`` → ``api_token_hash/salt``
        and clears the presented-token slot.  Raises ``ValidationError`` when
        no presented token is stored.
        """
        self.ensure_one()

        if not self.last_presented_token_hash or not self.last_presented_token_salt:
            from odoo.exceptions import ValidationError
            raise ValidationError(
                "Cannot accept this device: no presented token has been recorded. "
                "The device must attempt a display poll before it can be accepted."
            )

        self.with_context(trmnl_allow_identity_update=True).write({
            "api_token_hash": self.last_presented_token_hash,
            "api_token_salt": self.last_presented_token_salt,
            "last_presented_token_hash": False,
            "last_presented_token_salt": False,
        })
        return self
