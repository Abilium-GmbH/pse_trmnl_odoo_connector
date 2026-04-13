"""Core TRMNL device model."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone

from odoo import api, fields, models
from odoo.exceptions import ValidationError

MAC_RE = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")
API_TOKEN_PBKDF2_ITERATIONS = 310_000
API_TOKEN_BYTES = 32
DEFAULT_REFRESH_RATE = 1800
DEFAULT_DISPLAY_ERROR_STATUS = 202
DISPLAY_POLICY_ERROR = "error"
DISPLAY_POLICY_AUTO_ACCEPT = "auto_accept"
DISPLAY_POLICY_FACTORY_RESET = "factory_reset"
DISPLAY_POLICY_SELECTION = [
    (DISPLAY_POLICY_ERROR, "Return error"),
    (DISPLAY_POLICY_AUTO_ACCEPT, "Auto accept or register"),
    (DISPLAY_POLICY_FACTORY_RESET, "Trigger factory reset once"),
]


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
    DEFAULT_FILENAME = "abilium_test_screen"
    DEFAULT_IMAGE_URL = (
        "https://sampleimg.com/800x480?bg=000000&fg=ffffff&text=Abilium&format=png"
    )

    ##################################################
    # identity
    ##################################################

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

    ##################################################
    # lifecycle
    ##################################################

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
    display_request_count = fields.Integer(
        string="Display Request Count",
        readonly=True,
        copy=False,
    )
    log_entry_count = fields.Integer(string="Log Entry Count", readonly=True, copy=False)
    invalid_token_count = fields.Integer(string="Invalid Token Count", readonly=True, copy=False)
    display_denied_count = fields.Integer(string="Display Denied Count", readonly=True, copy=False)

    ##################################################
    # device telemetry
    ##################################################

    firmware_version = fields.Char(string="Firmware Version", readonly=True, copy=False)
    
    filename = fields.Char(
        string="Image filename",
        default=lambda self: self.DEFAULT_FILENAME,
        help="The device only refreshes the displayed image when the filename changes.",
    )

    image_url = fields.Char(
        string="Image URL",
        default=lambda self: self.DEFAULT_IMAGE_URL,
        help="URL returned to the display.",
    ) 

    display_action = fields.Char(
        string="Display Action",
        default="",
        help="Action returned to the display on the next poll.",
    )

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
            raise ValidationError("MAC address and Friendly ID cannot be changed once set.")

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

    ##################################################
    # helpers
    ##################################################

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
        return datetime.now(timezone.utc).replace(tzinfo=None)

    @api.model
    def _parse_to_string(self, value):
        """Normalize a value into a stripped string."""
        if value in (None, False, ""):
            return False

        value_text = str(value).strip()
        return value_text or False

    @api.model
    def _parse_to_int(self, value):
        """Normalize a value into an integer."""
        if value in (None, False, ""):
            return False

        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return False

    @api.model
    def _parse_to_float(self, value):
        """Normalize a value into a float."""
        if value in (None, False, ""):
            return False

        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return False

    @api.model
    def _normalize_mac_address(self, value):
        """Return a canonical uppercase colon-separated MAC address."""
        if value in (None, False, ""):
            return False

        value_text = str(value).strip()
        hex_digits = re.sub(r"[^0-9A-Fa-f]", "", value_text)

        if len(hex_digits) != 12:
            return False

        mac_address = ":".join(hex_digits[index : index + 2] for index in range(0, 12, 2)).upper()
        if not MAC_RE.match(mac_address):
            return False

        return mac_address

    @api.model
    def _generate_unique_friendly_id(self):
        """Generate a short unique friendly identifier."""
        for attempt_number in range(25):
            friendly_id = f"TRMNL-{secrets.token_hex(3).upper()}"
            if not self.sudo().search([("friendly_id", "=", friendly_id)], limit=1):
                return friendly_id

        raise ValidationError("Unable to generate a unique friendly ID.")
