"""Core TRMNL device model."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

MAC_RE = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")
API_TOKEN_PBKDF2_ITERATIONS = 310_000
API_TOKEN_BYTES = 32
DEFAULT_REFRESH_RATE = 1800
DEFAULT_UNKNOWN_DEVICE_POLICY = "error"


class TrmnlDevice(models.Model):
    """Represent a TRMNL e-ink display and its server-side state."""

    _name = "trmnl.device"
    _description = "TRMNL E-ink display device"
    _rec_name = "friendly_id"
    _unique_mac_address = models.Constraint(
        "UNIQUE(mac_address)",
        "MAC address must be unique.",
    )
    _unique_friendly_id = models.Constraint(
        "UNIQUE(friendly_id)",
        "Friendly ID must be unique.",
    )

    BATTERY_MIN_VOLTAGE = 3.0
    BATTERY_MAX_VOLTAGE = 4.2
    DEFAULT_IMAGE_URL = "https://sampleimg.com/800x480?bg=000000&fg=ffffff&text=Abilium&format=png"
    SETUP_FILENAME = "empty_state"

    friendly_id = fields.Char(
        string="Friendly ID",
        required=True,
        readonly=True,
        index=True,
        copy=False,
        help="Short unique identifier returned to the device during setup.",
    )
    mac_address = fields.Char(
        string="MAC Address",
        required=True,
        readonly=True,
        index=True,
        copy=False,
        help="Canonical MAC address used as the device identity.",
    )
    api_token_hash = fields.Char(
        string="API Token Hash",
        readonly=True,
        copy=False,
        help="Salted hash of the API token.",
    )
    api_token_salt = fields.Char(
        string="API Token Salt",
        readonly=True,
        copy=False,
        help="Random salt used to derive the API token hash.",
    )
    approval_state = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        string="Approval State",
        default="pending",
        required=True,
        index=True,
        copy=False,
    )
    registration_source = fields.Selection(
        selection=[
            ("setup", "Setup"),
            ("display", "Display"),
            ("manual", "Manual"),
        ],
        string="Registration Source",
        default="setup",
        required=True,
        index=True,
        copy=False,
    )
    first_seen_at = fields.Datetime(string="First Seen At", readonly=True, copy=False)
    last_seen_at = fields.Datetime(string="Last Seen At", readonly=True, copy=False)
    last_setup_at = fields.Datetime(string="Last Setup At", readonly=True, copy=False)
    last_display_at = fields.Datetime(string="Last Display At", readonly=True, copy=False)
    last_log_at = fields.Datetime(string="Last Log At", readonly=True, copy=False)
    approved_at = fields.Datetime(string="Approved At", readonly=True, copy=False)
    rejected_at = fields.Datetime(string="Rejected At", readonly=True, copy=False)
    last_access_denied_at = fields.Datetime(
        string="Last Access Denied At",
        readonly=True,
        copy=False,
    )

    setup_request_count = fields.Integer(string="Setup Request Count", readonly=True, copy=False)
    display_request_count = fields.Integer(string="Display Request Count", readonly=True, copy=False)
    log_entry_count = fields.Integer(string="Log Entry Count", readonly=True, copy=False)
    invalid_token_count = fields.Integer(string="Invalid Token Count", readonly=True, copy=False)
    display_denied_count = fields.Integer(string="Display Denied Count", readonly=True, copy=False)

    firmware_version = fields.Char(string="Firmware Version", readonly=True, copy=False)
    current_fw_version = fields.Char(string="Current Firmware Version", readonly=True, copy=False)
    next_display_action = fields.Selection(
        selection=[
            ("normal", "Normal"),
            ("reset_firmware", "Reset Firmware"),
        ],
        string="Next Display Action",
        default="normal",
        required=True,
        index=True,
        copy=False,
    )
    image_url = fields.Char(
        string="Image URL",
        default=lambda self: self.DEFAULT_IMAGE_URL,
        help="URL returned to the display.",
    )
    message = fields.Text(string="Message", help="Message shown during setup responses.")
    refresh_rate = fields.Integer(
        string="Refresh Rate",
        default=DEFAULT_REFRESH_RATE,
        help="Refresh rate reported by the device.",
    )
    battery_voltage = fields.Float(string="Battery Voltage", digits=(16, 3))
    battery_percentage = fields.Float(
        string="Battery Percentage",
        compute="_compute_battery_percentage",
        store=True,
        readonly=True,
    )
    rssi_dbm = fields.Integer(string="RSSI (dBm)")
    rssi_quality = fields.Selection(
        selection=[
            ("excellent", "Excellent"),
            ("good", "Good"),
            ("fair", "Fair"),
            ("poor", "Poor"),
            ("unknown", "Unknown"),
        ],
        string="RSSI Quality",
        compute="_compute_rssi_quality",
        store=True,
        readonly=True,
    )
    display_width = fields.Integer(string="Display Width")
    display_height = fields.Integer(string="Display Height")
    special_function = fields.Char(string="Special Function", default="none")
    wifi_status = fields.Char(string="Wi-Fi Status")

    @api.model_create_multi
    def create(self, values_list):
        """Normalize identity fields before records are inserted."""
        if isinstance(values_list, dict):
            values_list = [values_list]
        normalized_values_list = []
        for values in values_list:
            normalized_values = dict(values)
            mac_address = normalized_values.get("mac_address")
            if mac_address:
                normalized_values["mac_address"] = self._normalize_mac_address(mac_address)
            if not normalized_values.get("friendly_id"):
                normalized_values["friendly_id"] = self._generate_unique_friendly_id()
            normalized_values_list.append(normalized_values)
        return super().create(normalized_values_list)

    def write(self, values):
        """Protect device identity unless an explicit context override is present."""
        protected_fields = {"mac_address", "friendly_id"}
        if protected_fields.intersection(values.keys()) and not self.env.context.get(
            "trmnl_allow_identity_update"
        ):
            raise ValidationError(_("MAC address and Friendly ID cannot be changed once set."))
        return super().write(values)

    @api.depends("battery_voltage")
    def _compute_battery_percentage(self):
        """Compute battery charge as a percentage of the configured voltage window."""
        for device in self:
            device.battery_percentage = device._voltage_to_percentage(device.battery_voltage)

    @api.depends("rssi_dbm")
    def _compute_rssi_quality(self):
        """Derive a human-readable RSSI quality label from the raw dBm reading."""
        for device in self:
            device.rssi_quality = device._rssi_to_quality(device.rssi_dbm)

    @api.model
    def _voltage_to_percentage(self, voltage):
        """Convert a voltage to a battery percentage."""
        if voltage is False or voltage is None:
            return False
        if voltage <= self.BATTERY_MIN_VOLTAGE:
            return 0.0
        if voltage >= self.BATTERY_MAX_VOLTAGE:
            return 100.0
        span = self.BATTERY_MAX_VOLTAGE - self.BATTERY_MIN_VOLTAGE
        return round(((voltage - self.BATTERY_MIN_VOLTAGE) / span) * 100.0, 2)

    @api.model
    def _rssi_to_quality(self, rssi_dbm):
        """Translate an RSSI reading into a coarse quality bucket."""
        if rssi_dbm is False or rssi_dbm is None:
            return "unknown"
        if rssi_dbm >= -60:
            return "excellent"
        if rssi_dbm >= -70:
            return "good"
        if rssi_dbm >= -80:
            return "fair"
        return "poor"

    @staticmethod
    def _utc_now():
        """Return a naive UTC datetime for filename generation."""
        return datetime.utcnow()

    @api.model
    def _normalize_mac_address(self, value):
        """Normalize a MAC address to uppercase colon-separated notation."""
        if value in (None, ""):
            return False
        raw_value = str(value).strip().upper()
        compact_value = re.sub(r"[^0-9A-F]", "", raw_value)
        if len(compact_value) != 12 or not MAC_RE.fullmatch(
            ":".join(compact_value[index : index + 2] for index in range(0, 12, 2))
        ):
            raise ValidationError(_("TRMNL device ID must be a valid MAC address."))
        return ":".join(compact_value[index : index + 2] for index in range(0, 12, 2))

    @api.model
    def _parse_to_string(self, value):
        """Convert a potentially typed value to a stripped string."""
        if value is False or value is None:
            return False
        text_value = str(value).strip()
        return text_value if text_value else False

    @api.model
    def _parse_to_int(self, value):
        """Convert a potentially typed value to an integer."""
        if value is False or value is None or value == "":
            return False
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return False

    @api.model
    def _parse_to_float(self, value):
        """Convert a potentially typed value to a float."""
        if value is False or value is None or value == "":
            return False
        try:
            return float(value)
        except (TypeError, ValueError):
            return False

    @api.model
    def _generate_unique_friendly_id(self):
        """Generate a friendly identifier that does not already exist."""
        for attempt_index in range(20):
            friendly_id = secrets.token_hex(3).upper()
            if not self.sudo().search_count([("friendly_id", "=", friendly_id)]):
                return friendly_id
            _logger.debug("TRMNL friendly ID collision on attempt %s", attempt_index + 1)
        raise ValidationError(_("Unable to allocate a unique TRMNL friendly ID."))

    @api.model
    def _generate_api_token(self):
        """Generate a random token that can be presented by the device."""
        return secrets.token_urlsafe(API_TOKEN_BYTES)

    @api.model
    def _hash_api_token(self, raw_token, salt_bytes=None):
        """Hash a raw API token with PBKDF2."""
        if salt_bytes is None:
            salt_bytes = secrets.token_bytes(16)
        if isinstance(salt_bytes, str):
            salt_bytes = base64.b64decode(salt_bytes.encode("ascii"))
        token_hash = hashlib.pbkdf2_hmac(
            "sha256",
            raw_token.encode("utf-8"),
            salt_bytes,
            API_TOKEN_PBKDF2_ITERATIONS,
        )
        return {
            "api_token_hash": base64.b64encode(token_hash).decode("ascii"),
            "api_token_salt": base64.b64encode(salt_bytes).decode("ascii"),
        }

    @api.model
    def _build_api_token_material(self):
        """Return a freshly generated token together with its persisted hash material."""
        raw_token = self._generate_api_token()
        return raw_token, self._hash_api_token(raw_token)

    def _verify_api_token(self, raw_token):
        """Verify a token against the persisted hash material."""
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

    def _rotate_api_token(self):
        """Replace the device token with a freshly generated one."""
        self.ensure_one()
        raw_token, token_values = self._build_api_token_material()
        self.with_context(trmnl_allow_identity_update=True).write(token_values)
        return raw_token

    @api.model
    def _get_unknown_device_policy(self):
        """Read the policy that governs display requests from unknown devices."""
        config_parameter = self.env["ir.config_parameter"].sudo()
        policy = config_parameter.get_param(
            "trmnl.unknown_device_policy",
            DEFAULT_UNKNOWN_DEVICE_POLICY,
        )
        if policy not in {"error", "reset_firmware", "auto_accept"}:
            return DEFAULT_UNKNOWN_DEVICE_POLICY
        return policy

    def _build_display_filename(self, timestamp=None):
        """Build the filename returned to the display for the current image."""
        timestamp_value = timestamp or self._utc_now()
        return f"{self.friendly_id}-{timestamp_value.strftime('%Y-%m-%dT%H:%M:%S')}"

    def _build_setup_filename(self):
        """Return the filename used for the initial setup image."""
        return self.SETUP_FILENAME

    def _record_setup_request(self, source="setup"):
        """Update counters and timestamps for a setup request."""
        self.ensure_one()
        now_value = fields.Datetime.now()
        self.with_context(trmnl_allow_identity_update=True).write(
            {
                "approval_state": "approved",
                "approved_at": self.approved_at or now_value,
                "last_setup_at": now_value,
                "last_seen_at": now_value,
                "next_display_action": "normal",
                "registration_source": source,
                "setup_request_count": (self.setup_request_count or 0) + 1,
            }
        )
        return self

    def _record_display_served(self):
        """Update counters and timestamps for a successful display response."""
        self.ensure_one()
        now_value = fields.Datetime.now()
        self.with_context(trmnl_allow_identity_update=True).write(
            {
                "last_display_at": now_value,
                "last_seen_at": now_value,
                "display_request_count": (self.display_request_count or 0) + 1,
            }
        )
        return self

    def _record_access_denied(self, reason="invalid_token"):
        """Update counters and timestamps for denied device access."""
        self.ensure_one()
        now_value = fields.Datetime.now()
        update_values = {
            "last_access_denied_at": now_value,
            "last_seen_at": now_value,
        }
        if reason == "invalid_token":
            update_values["invalid_token_count"] = (self.invalid_token_count or 0) + 1
        else:
            update_values["display_denied_count"] = (self.display_denied_count or 0) + 1
        self.with_context(trmnl_allow_identity_update=True).write(update_values)
        return self

    def _approve_record(self, source="manual"):
        """Approve the device and normalize the next action."""
        self.ensure_one()
        now_value = fields.Datetime.now()
        self.with_context(trmnl_allow_identity_update=True).write(
            {
                "approval_state": "approved",
                "approved_at": now_value,
                "next_display_action": "normal",
                "registration_source": source,
            }
        )
        return self

    def _reject_record(self):
        """Reject the device and clear any queued display reset."""
        self.ensure_one()
        now_value = fields.Datetime.now()
        self.with_context(trmnl_allow_identity_update=True).write(
            {
                "approval_state": "rejected",
                "next_display_action": "normal",
                "rejected_at": now_value,
            }
        )
        return self

    def action_approve_device(self):
        """Approve the selected TRMNL devices from the UI."""
        for device in self:
            device._approve_record(source="manual")
        return True

    def action_reject_device(self):
        """Reject the selected TRMNL devices from the UI."""
        for device in self:
            device._reject_record()
        return True

    def action_queue_firmware_reset(self):
        """Ask the next display poll to return a firmware reset payload."""
        self.with_context(trmnl_allow_identity_update=True).write(
            {"next_display_action": "reset_firmware"}
        )
        return True

    def action_clear_queued_action(self):
        """Remove any queued special action for the next display poll."""
        self.with_context(trmnl_allow_identity_update=True).write(
            {"next_display_action": "normal"}
        )
        return True

    @api.model
    def build_setup_error_response(self, message=""):
        """Build the JSON payload returned when setup cannot be processed."""
        return {
            "status": 404,
            "api_key": "",
            "friendly_id": "",
            "filename": "",
            "image_name": "",
            "image_url": "",
            "message": message or "",
        }

    def build_setup_response(self, api_token=""):
        """Build the JSON payload returned after a successful setup request."""
        self.ensure_one()
        filename = self._build_setup_filename()
        return {
            "status": 200,
            "api_key": api_token or "",
            "friendly_id": self.friendly_id,
            "filename": filename,
            "image_name": filename,
            "image_url": self.image_url or "",
            "message": self.message or "",
        }

    @api.model
    def build_display_error_response(self, status=404):
        """Build a generic error payload for display requests."""
        return {
            "status": status,
            "filename": "",
            "image_name": "",
            "image_url": "",
            "image_url_timeout": 0,
            "action": "",
            "firmware_url": "",
            "refresh_rate": DEFAULT_REFRESH_RATE,
            "reset_firmware": False,
            "special_function": "none",
            "update_firmware": False,
        }

    def build_display_reset_response(self):
        """Build the payload instructing the device to reset its firmware state."""
        self.ensure_one()
        payload = self.build_display_error_response(status=0)
        payload["reset_firmware"] = True
        return payload

    @api.model
    def build_no_user_display_response(self):
        """Build the payload returned when no device identity is available."""
        return {
            "status": 202,
            "filename": "",
            "image_name": "",
            "image_url": "",
            "image_url_timeout": 0,
            "action": "",
            "firmware_url": "",
            "refresh_rate": DEFAULT_REFRESH_RATE,
            "reset_firmware": False,
            "special_function": "none",
            "update_firmware": False,
        }

    def build_display_response(self):
        """Build the normal display payload for an approved device."""
        self.ensure_one()
        filename = self._build_display_filename()
        return {
            "status": 0,
            "filename": filename,
            "image_name": filename,
            "image_url": self.image_url or "",
            "image_url_timeout": 0,
            "action": "",
            "firmware_url": "",
            "refresh_rate": self.refresh_rate or DEFAULT_REFRESH_RATE,
            "reset_firmware": False,
            "special_function": self.special_function or "none",
            "update_firmware": False,
        }

    @api.model
    def find_by_mac_and_token(self, mac_address, api_token):
        """Find a device by MAC address and validate the presented token."""
        normalized_mac_address = self._normalize_mac_address(mac_address)
        normalized_token = self._parse_to_string(api_token)
        if not normalized_mac_address or not normalized_token:
            return self.browse()
        device = self.sudo().search([("mac_address", "=", normalized_mac_address)], limit=1)
        if device and device._verify_api_token(normalized_token):
            return device
        return self.browse()
