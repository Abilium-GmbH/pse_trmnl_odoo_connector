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
    (DISPLAY_POLICY_ERROR, "Respond with an error"),
    (DISPLAY_POLICY_AUTO_ACCEPT, "Automatically accept the device"),
    (DISPLAY_POLICY_FACTORY_RESET, "Send a reset command"),
]

# Approval state constants
#
# accepted       — device is registered and has a valid, matching API token.
# token_mismatch — device MAC is known but the token it last presented did not
#                  match the stored hash.
# unknown_device — device MAC has never been seen before; a stub record has
#                  been created so the admin can review and manually accept it.
APPROVAL_STATE_ACCEPTED = "accepted"
APPROVAL_STATE_TOKEN_MISMATCH = "token_mismatch"
APPROVAL_STATE_UNKNOWN_DEVICE = "unknown_device"
APPROVAL_STATE_SELECTION = [
    (APPROVAL_STATE_ACCEPTED, "Accepted"),
    (APPROVAL_STATE_TOKEN_MISMATCH, "Token Mismatch"),
    (APPROVAL_STATE_UNKNOWN_DEVICE, "Unknown Device"),
]

REFRESH_RATE_UNIT_SECONDS: dict[str, int] = {
    "minutes": 60,
    "hours": 3_600,
    "days": 86_400,
    "weeks": 604_800,       # 7-day week
    "months": 2_592_000,    # 30-day month
    "years": 31_536_000,    # 365-day year
}

# 1 minute lower bound; 10 years upper bound
REFRESH_RATE_MIN_SECONDS: int = 60
REFRESH_RATE_MAX_SECONDS: int = 10 * REFRESH_RATE_UNIT_SECONDS["years"]


class TrmnlDevice(models.Model):
    """Represent a TRMNL e-ink display and its server-side state.

    Identity fields (mac_address, friendly_id) are write-protected after
    creation and may only be mutated via the ``trmnl_allow_identity_update``
    context flag.

    Approval states
    ---------------
    accepted       — device is registered with a matching API token and will
                     be served display content and have its logs stored.
    token_mismatch — MAC is known but the token last presented by the device
                     did not match; the admin can manually accept the device to
                     adopt the presented token.
    unknown_device — MAC has never been seen via /api/setup; a stub record was
                     created automatically so the admin can act on it.  The
                     friendly_id is absent for such devices because it is only
                     assigned by the server during /api/setup.
    """

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

    # ------------------------------------------------------------------
    # identity
    # ------------------------------------------------------------------

    friendly_id = fields.Char(
        string="Friendly ID",
        readonly=True,
        index=True,
        copy=False,
        help=(
            "Short unique identifier returned to the device during /api/setup. "
            "Absent for devices that were first seen via /api/display."
        ),
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
        help="Salted PBKDF2 hash of the accepted API token.",
    )

    api_token_salt = fields.Char(
        string="API Token Salt",
        readonly=True,
        copy=False,
        help="Random salt used to derive the accepted API token hash.",
    )

    last_presented_token_hash = fields.Char(
        string="Last Presented Token Hash",
        readonly=True,
        copy=False,
        help=(
            "Salted PBKDF2 hash of the most recent token presented by the "
            "device in a display call.  Used when an admin manually accepts "
            "a token-mismatch or unknown-device record."
        ),
    )

    last_presented_token_salt = fields.Char(
        string="Last Presented Token Salt",
        readonly=True,
        copy=False,
        help="Random salt used to derive the last-presented token hash.",
    )

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    approval_state = fields.Selection(
        selection=APPROVAL_STATE_SELECTION,
        string="Approval State",
        default=APPROVAL_STATE_UNKNOWN_DEVICE,
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
    accepted_at = fields.Datetime(string="Accepted At", readonly=True, copy=False)
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

    # ------------------------------------------------------------------
    # device configuration (server → device)
    # ------------------------------------------------------------------

    filename = fields.Char(
        string="Image Filename",
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

    identify_pending = fields.Boolean(
        string="Identify Pending",
        default=False,
        copy=False,
        help=(
            "One-shot flag set by the admin Identify action.  When True the "
            "next /api/display response will carry special_function='identify' "
            "and action='identify'.  The flag is cleared automatically after "
            "the response is sent."
        ),
    )

    desired_refresh_rate = fields.Integer(
        string="Desired Refresh Rate (s)",
        default=DEFAULT_REFRESH_RATE,
        required=True,
        copy=True,
        help=(
            "Refresh interval in seconds that the server sends to the device on "
            "the next /api/display response. Must be between "
            f"{REFRESH_RATE_MIN_SECONDS} s (1 min) and "
            f"{REFRESH_RATE_MAX_SECONDS} s (10 years)."
        ),
    )

    desired_refresh_rate_value = fields.Integer(
        string="Refresh Rate",
        compute="_compute_desired_refresh_rate_display",
        inverse="_inverse_desired_refresh_rate_display",
        store=False,
        help="Refresh rate expressed in the selected unit.",
    )

    desired_refresh_rate_unit = fields.Selection(
        string="Unit",
        selection=[
            ("minutes", "Minutes"),
            ("hours", "Hours"),
            ("days", "Days"),
            ("weeks", "Weeks"),
            ("months", "Months"),
            ("years", "Years"),
        ],
        compute="_compute_desired_refresh_rate_display",
        inverse="_inverse_desired_refresh_rate_display",
        store=False,
        help="Unit used to express the desired refresh rate in the UI.",
    )

    # ------------------------------------------------------------------
    # device telemetry (device → server, read-only)
    # ------------------------------------------------------------------

    firmware_version = fields.Char(string="Firmware Version", readonly=True, copy=False)

    refresh_rate = fields.Integer(
        string="Last Reported Refresh Rate (s)",
        readonly=True,
        copy=False,
        help="Refresh rate last reported by the device in its display poll headers.",
    )

    battery_voltage = fields.Float(string="Battery Voltage", digits=(16, 3))
    battery_percentage = fields.Integer(
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

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------

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

            # friendly_id is optional for unknown_device records created via
            # /api/display.  Only auto-generate one when the state is not
            # unknown_device, or when the caller explicitly requested one.
            state = normalized_values.get("approval_state", APPROVAL_STATE_UNKNOWN_DEVICE)
            if not normalized_values.get("friendly_id") and state != APPROVAL_STATE_UNKNOWN_DEVICE:
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

    # ------------------------------------------------------------------
    # constraints
    # ------------------------------------------------------------------

    @api.constrains("desired_refresh_rate")
    def _check_desired_refresh_rate_bounds(self):
        """Enforce the 1-minute lower and 10-year upper bounds."""
        for device in self:
            if device.desired_refresh_rate < REFRESH_RATE_MIN_SECONDS:
                raise ValidationError(
                    f"Refresh rate must be at least {REFRESH_RATE_MIN_SECONDS} seconds (1 minute)."
                )
            if device.desired_refresh_rate > REFRESH_RATE_MAX_SECONDS:
                raise ValidationError(
                    f"Refresh rate must not exceed {REFRESH_RATE_MAX_SECONDS} seconds (10 years)."
                )

    # ------------------------------------------------------------------
    # computed fields
    # ------------------------------------------------------------------

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

    @api.depends("desired_refresh_rate")
    def _compute_desired_refresh_rate_display(self):
        """Decompose ``desired_refresh_rate`` (seconds) into a value/unit pair.

        The largest unit that divides evenly into the stored seconds is chosen
        so that the UI shows the most human-readable representation, e.g.
        3600 seconds → 1 hour, 7200 seconds → 2 hours, 300 seconds → 5 minutes.

        Months are defined as 30 days (2 592 000 seconds) and years as 365 days
        (31 536 000 seconds). Because a month is shorter than a year, the ordered
        probe list checks years before months so that exact multiples of a
        year are not misclassified as months etc.
        """
        ordered_units = tuple(
            sorted(
                REFRESH_RATE_UNIT_SECONDS,
                key=REFRESH_RATE_UNIT_SECONDS.get,
                reverse=True,
            )
        )
        for device in self:
            raw_seconds = device.desired_refresh_rate or DEFAULT_REFRESH_RATE
            chosen_unit = "minutes"
            chosen_value = max(1, raw_seconds // REFRESH_RATE_UNIT_SECONDS["minutes"])

            for unit in ordered_units:
                unit_seconds = REFRESH_RATE_UNIT_SECONDS[unit]
                if raw_seconds >= unit_seconds and raw_seconds % unit_seconds == 0:
                    chosen_unit = unit
                    chosen_value = raw_seconds // unit_seconds
                    break

            device.desired_refresh_rate_value = chosen_value
            device.desired_refresh_rate_unit = chosen_unit

    def _inverse_desired_refresh_rate_display(self):
        """Convert the UI value/unit pair back into ``desired_refresh_rate`` seconds."""
        for device in self:
            unit = device.desired_refresh_rate_unit or "minutes"
            value = device.desired_refresh_rate_value or 1
            unit_seconds = REFRESH_RATE_UNIT_SECONDS.get(unit, REFRESH_RATE_UNIT_SECONDS["minutes"])
            device.desired_refresh_rate = value * unit_seconds

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

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
        return int(((voltage - self.BATTERY_MIN_VOLTAGE) / span) * 100.0)

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
        for _attempt in range(25):
            friendly_id = f"TRMNL-{secrets.token_hex(3).upper()}"
            if not self.sudo().search([("friendly_id", "=", friendly_id)], limit=1):
                return friendly_id

        raise ValidationError("Unable to generate a unique friendly ID.")
