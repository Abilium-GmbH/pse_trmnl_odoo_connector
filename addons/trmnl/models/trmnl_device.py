"""Core TRMNL device model."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone

from urllib.parse import urlparse

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

# TRMNL-Displays send a 6-octet, uppercase hex, colon-separated string according to the
# firmware, e.g.: A4:CF:12:7E:3B:01
MAC_RE = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")

# System parameter key for the display-request policy.  Defined once here so
# lifecycle, UI, and wizard code all reference the same string.
TRMNL_POLICY_PARAM = "trmnl.display_unknown_device_policy"
# When set to 1/true/yes/on, TRMNL HTTP controllers log extra request/branch detail.
TRMNL_API_DEBUG_PARAM = "trmnl.api_debug"

# Hosts/IPs that are not reachable by a physical device on the LAN: loopback
# addresses and the libvirt/KVM virbr0 bridge (192.168.122.x).
#
# Normal LAN ranges — 10.x.x.x, 192.168.x.x, 172.x.x.x — are intentionally
# NOT blocked.  A configured LAN IP is a valid device target regardless of
# whether it falls inside RFC-1918 space.  Note: Docker bridge IPs
# (commonly 172.17.0.x) overlap with legitimate corporate LAN ranges and
# cannot be excluded reliably by pattern alone; set trmnl.public_base_url
# explicitly when web.base.url resolves to a container-internal address.
_INTERNAL_HOST_RE = re.compile(
    r"^("
    r"localhost"
    r"|0\.0\.0\.0"
    r"|127(?:\.\d+){3}"
    r"|::1"
    r"|192\.168\.122\.\d+"
    r")$",
    re.IGNORECASE,
)

_IPV4_RE = re.compile(
    r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$"
)


def _ipv4_octets(host_or_ip):
    """Return (a, b, c, d) for a dotted IPv4 string, else None."""
    if not host_or_ip:
        return None
    match = _IPV4_RE.match(str(host_or_ip).strip())
    if not match:
        return None
    octets = tuple(int(g) for g in match.groups())
    if any(o < 0 or o > 255 for o in octets):
        return None
    return octets


def _private_subnet_key(octets):
    """Grouping key for RFC1918-style LAN reachability heuristics."""
    if octets[0] == 10:
        return ("10", octets[1], octets[2])
    if octets[0] == 192 and octets[1] == 168:
        return ("192.168", octets[2])
    if octets[0] == 172 and 16 <= octets[1] <= 31:
        return ("172", octets[1])
    return octets[:3]


def client_can_reach_host(client_ip, host):
    """True when a TRMNL on client_ip can plausibly reach host (IPv4 LAN heuristic).

    Non-IPv4 hostnames are treated as reachable (DNS / mDNS setups).
    """
    client = _ipv4_octets(client_ip)
    if not client:
        return True
    target = _ipv4_octets(host)
    if not target:
        return True
    return _private_subnet_key(client) == _private_subnet_key(target)


def is_device_reachable_base_url(url):
    """Return True if url's host is reachable by a physical LAN device.

    Rejects loopback (localhost / 127.x.x.x / ::1 / 0.0.0.0) and the
    libvirt KVM virbr0 bridge (192.168.122.x).
    """
    try:
        host = urlparse(url).hostname or ""
        return bool(host) and not _INTERNAL_HOST_RE.match(host)
    except Exception:
        return False

# PBKDF2-HMAC-SHA256 iteration count chosen per
# OWASP Password Storage Cheat Sheet (2026).
#
# Increase this value as hardware improves, but note that changing it
# invalidates all existing stored hashes without a migration.
API_TOKEN_PBKDF2_ITERATIONS = 600_000
API_TOKEN_BYTES = 32

SECONDS_PER_MINUTE: int = 60

# Refresh rate bounds.
# Both bounds are expressed in seconds; the UI always displays minutes.
REFRESH_RATE_MIN_SECONDS: int = 1 * SECONDS_PER_MINUTE  # 1 minute
REFRESH_RATE_MAX_SECONDS: int = 30 * SECONDS_PER_MINUTE  # 30 minutes
DEFAULT_REFRESH_RATE: int = 1 * SECONDS_PER_MINUTE       # 1 minute

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
# accepted       — device is registered and has a valid, matching API token
#                  stored in the accepted-token slot (api_token_hash /
#                  api_token_salt).
# token_mismatch — device MAC is known, the device is accepted, but the token
#                  it last presented did not match the stored accepted-token
#                  hash.  Only reachable from ``accepted``; never from
#                  ``unknown_device``.
# unknown_device — device MAC has not been registered before; a full record has
#                  been created so the admin can review and manually accept it.
#                  Any token the device presents is stored in the presented-token
#                  slot (last_presented_token_hash / last_presented_token_salt)
#                  only.  The accepted-token slot is always empty for these
#                  records, so token validation is never performed.
APPROVAL_STATE_ACCEPTED = "accepted"
APPROVAL_STATE_TOKEN_MISMATCH = "token_mismatch"
APPROVAL_STATE_UNKNOWN_DEVICE = "unknown_device"
APPROVAL_STATE_SELECTION = [
    (APPROVAL_STATE_ACCEPTED, "Accepted"),
    (APPROVAL_STATE_TOKEN_MISMATCH, "Token Mismatch"),
    (APPROVAL_STATE_UNKNOWN_DEVICE, "Unknown Device"),
]

REGISTRATION_SOURCE_SETUP = "setup"
REGISTRATION_SOURCE_DISPLAY = "display"
REGISTRATION_SOURCE_SELECTION = [
    (REGISTRATION_SOURCE_SETUP, "Setup"),
    (REGISTRATION_SOURCE_DISPLAY, "Display"),
]

# Last API call options — the three endpoints a device can reach.
LAST_API_CALL_SETUP = "setup"
LAST_API_CALL_DISPLAY = "display"
LAST_API_CALL_LOG = "log"
LAST_API_CALL_SELECTION = [
    (LAST_API_CALL_SETUP, "Setup"),
    (LAST_API_CALL_DISPLAY, "Display"),
    (LAST_API_CALL_LOG, "Log"),
]

# Filenames for the two built-in display images.
DEFAULT_FILENAME = "default_screen.bmp"
UNAUTHORIZED_IMAGE_FILENAME = "unauthorized_screen.bmp"

# Static asset paths — used only as a last-resort fallback when the
# ir.attachment seed has not been created yet (e.g. during the very first
# install before post_init_hook runs).  TRMNL devices must never be served
# these relative paths directly; they need absolute URLs built from
# web.base.url via TrmnlImageSeeder.get_image_url().
DEFAULT_IMAGE_STATIC_PATH = "/trmnl/static/default_screen.bmp"
UNAUTHORIZED_IMAGE_STATIC_PATH = "/trmnl/static/unauthorized_screen.bmp"


def _default_image_url(self):
    """Resolve the absolute URL for the default display image.

    Used as the ``default=`` callable for the ``image_url`` field so that
    every newly created device record is immediately populated with an
    absolute, device-reachable URL.  Falls back to the static asset path
    when the attachment has not been seeded yet.
    """
    from .trmnl_image import DEFAULT_IMAGE_CONFIG_KEY
    return (
        self.env["trmnl.image.seeder"].get_image_url(DEFAULT_IMAGE_CONFIG_KEY)
        or DEFAULT_IMAGE_STATIC_PATH
    )


class TrmnlDevice(models.Model):
    """Represent a TRMNL e-ink display and its server-side state.

    Identity fields (mac_address) are write-protected after creation and may
    only be mutated via the ``trmnl_allow_identity_update`` context flag.

    Approval states
    ---------------
    accepted       — device is registered with a matching API token stored in
                     the accepted-token slot (``api_token_hash`` /
                     ``api_token_salt``) and will be served display content
                     and have its logs stored.
    token_mismatch — the device was previously accepted but the token it last
                     presented did not match the accepted-token hash.  Only
                     reachable from ``accepted``; token validation is never
                     performed on ``unknown_device`` records.
    unknown_device — MAC has never been registered via /api/setup; a full
                     record was created automatically so the admin can act on
                     it.  Any token presented by the device is stored in the
                     presented-token slot (``last_presented_token_hash`` /
                     ``last_presented_token_salt``) only.  The accepted-token
                     slot is always empty, so token validation is skipped
                     entirely for records in this state.

    Refresh rate
    ------------
    ``desired_refresh_rate`` is stored in seconds internally.  The UI always
    works in minutes (the only supported unit) via the
    ``desired_refresh_rate_minutes`` compute/inverse pair.  Valid range:
    1 minute (``REFRESH_RATE_MIN_SECONDS``) to 30 minutes
    (``REFRESH_RATE_MAX_SECONDS``).

    Image URL
    ---------
    ``image_url`` holds an absolute URL built from ``web.base.url`` and the
    ``/web/image/{id}`` route of the seeded ``ir.attachment`` record.  This
    URL is reachable by the TRMNL device regardless of whether Odoo is running
    in a local Docker container or on odoo.sh.  The static asset files under
    ``static/`` are only used as the seed source during installation
    and as a last-resort fallback; they are never served directly to devices.
    """

    _name = "trmnl.device"
    _description = "TRMNL E-ink display device"
    _rec_name = "mac_address"

    _unique_mac_address = models.Constraint(
        "UNIQUE(mac_address)",
        "MAC address must be unique.",
    )

    BATTERY_MIN_VOLTAGE = 3.0
    BATTERY_MAX_VOLTAGE = 4.2

    # ------------------------------------------------------------------
    # identity
    # ------------------------------------------------------------------

    mac_address = fields.Char(
        string="MAC Address",
        required=True,
        readonly=True,
        index=True,
        copy=False,
        help="Canonical MAC address used as the device identity.",
    )

    friendly_id = fields.Char(
        string="Friendly ID",
        readonly=True,
        copy=False,
        index=True,
        help="Short human-readable identifier shown on device previews when no device name is set.",
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
        selection=REGISTRATION_SOURCE_SELECTION,
        string="Registration Source",
        readonly=True,
        copy=False,
    )

    last_seen_at = fields.Datetime(string="Last Seen At", readonly=True, copy=False)

    last_setup_at = fields.Datetime(string="Last Setup At", readonly=True, copy=False)
    last_display_at = fields.Datetime(string="Last Display At", readonly=True, copy=False)
    last_poll_at = fields.Datetime(string="Last Poll At", readonly=True, copy=False)
    last_log_at = fields.Datetime(string="Last Log At", readonly=True, copy=False)
    accepted_at = fields.Datetime(string="Accepted At", readonly=True, copy=False)

    added_at = fields.Datetime(
        string="Added At",
        readonly=True,
        copy=False,
        help=(
            "When the device was added to the system. "
            "For devices registered via /api/setup this is the registration timestamp. "
            "For devices first seen via /api/display this is the timestamp at which "
            "the device was accepted, either automatically (auto-accept policy) or "
            "manually by an administrator."
        ),
    )

    last_api_call = fields.Selection(
        selection=LAST_API_CALL_SELECTION,
        string="Last API Call",
        readonly=True,
        copy=False,
        help="The most recent endpoint the device contacted: setup, display, or log.",
    )

    # ------------------------------------------------------------------
    # device configuration (server → device)
    # ------------------------------------------------------------------

    filename = fields.Char(
        string="Image Filename",
        default=lambda self: DEFAULT_FILENAME,
        help=(
            "The filename most recently served to the device. "
            "The device only refreshes the displayed image when the filename changes. "
            "Managed by the image renderer and lifecycle transitions; read-only in the admin UI."
        ),
    )

    image_url = fields.Char(
        string="Image URL",
        default=_default_image_url,
        help=(
            "Absolute URL returned to the display device. "
            "Built from web.base.url and the /web/image/{id} route of the seeded "
            "ir.attachment record so the device can fetch it over the network. "
            "Managed by the image renderer and lifecycle transitions; read-only in the admin UI."
        ),
    )

    reset_pending = fields.Boolean(
        string="Reset Pending",
        default=False,
        copy=False,
        help=(
            "One-shot flag set by the admin Reset action. When True the next "
            "/api/display poll from this device will receive a reset_firmware."
        ),
    )

    desired_refresh_rate = fields.Integer(
        string="Desired Refresh Rate (s)",
        default=DEFAULT_REFRESH_RATE,
        required=True,
        copy=True,
        help=(
            "Refresh interval in seconds sent to the device on the next "
            "/api/display response. Must be between "
            f"{REFRESH_RATE_MIN_SECONDS} s ({REFRESH_RATE_MIN_SECONDS // 60} min) and "
            f"{REFRESH_RATE_MAX_SECONDS} s ({REFRESH_RATE_MAX_SECONDS // 60} min)."
        ),
    )

    desired_refresh_rate_minutes = fields.Integer(
        string="Refresh Rate (min)",
        compute="_compute_desired_refresh_rate_minutes",
        inverse="_inverse_desired_refresh_rate_minutes",
        store=False,
        help=(
            "Refresh rate expressed in minutes. "
            f"Valid range: {REFRESH_RATE_MIN_SECONDS // 60}–"
            f"{REFRESH_RATE_MAX_SECONDS // 60} minutes."
        ),
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

            normalized_values_list.append(normalized_values)

        return super().create(normalized_values_list)

    def write(self, values):
        """Protect device identity unless an explicit context override is present."""
        if "mac_address" in values and not self.env.context.get(
            "trmnl_allow_identity_update"
        ):
            raise AccessError(
                "MAC address is a protected identity field and "
                "cannot be modified after creation."
            )

        return super().write(values)

    # ------------------------------------------------------------------
    # constraints
    # ------------------------------------------------------------------

    @api.constrains("desired_refresh_rate")
    def _check_desired_refresh_rate_bounds(self):
        """Enforce the 1-minute lower and 30-minute upper bounds."""
        for device in self:
            if device.desired_refresh_rate < REFRESH_RATE_MIN_SECONDS:
                raise ValidationError(
                    f"Refresh rate must be at least {REFRESH_RATE_MIN_SECONDS} seconds "
                    f"({REFRESH_RATE_MIN_SECONDS // 60} minute)."
                )
            if device.desired_refresh_rate > REFRESH_RATE_MAX_SECONDS:
                raise ValidationError(
                    f"Refresh rate must not exceed {REFRESH_RATE_MAX_SECONDS} seconds "
                    f"({REFRESH_RATE_MAX_SECONDS // 60} minutes)."
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
    def _compute_desired_refresh_rate_minutes(self):
        """Convert ``desired_refresh_rate`` seconds to whole minutes for the UI.

        The stored value is always an exact multiple of 60 within the allowed
        range, so integer division is exact.  If the stored value is somehow
        out of range it is clamped to the nearest valid minute count so that
        the form field remains editable.
        """
        min_minutes = REFRESH_RATE_MIN_SECONDS // SECONDS_PER_MINUTE
        max_minutes = REFRESH_RATE_MAX_SECONDS // SECONDS_PER_MINUTE

        for device in self:
            raw_seconds = device.desired_refresh_rate or DEFAULT_REFRESH_RATE
            minutes = max(min_minutes, min(max_minutes, raw_seconds // SECONDS_PER_MINUTE))
            device.desired_refresh_rate_minutes = minutes

    def _inverse_desired_refresh_rate_minutes(self):
        """Convert the UI minutes value back into ``desired_refresh_rate`` seconds."""
        for device in self:
            minutes = device.desired_refresh_rate_minutes or (
                REFRESH_RATE_MIN_SECONDS // SECONDS_PER_MINUTE
            )
            device.desired_refresh_rate = minutes * SECONDS_PER_MINUTE

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _voltage_to_percentage(voltage):
        """Convert a voltage to a battery percentage."""
        if voltage is False or voltage is None:
            return False

        if voltage <= TrmnlDevice.BATTERY_MIN_VOLTAGE:
            return 0.0

        if voltage >= TrmnlDevice.BATTERY_MAX_VOLTAGE:
            return 100.0

        span = TrmnlDevice.BATTERY_MAX_VOLTAGE - TrmnlDevice.BATTERY_MIN_VOLTAGE
        return int(((voltage - TrmnlDevice.BATTERY_MIN_VOLTAGE) / span) * 100.0)

    @staticmethod
    def _rssi_to_quality(rssi_dbm):
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
        """Return a naive UTC datetime for use in timestamps."""
        return datetime.now(timezone.utc).replace(tzinfo=None)

    @staticmethod
    def _parse_to_string(value):
        """Normalize a value into a stripped string."""
        if value in (None, False, ""):
            return False

        value_text = str(value).strip()
        return value_text or False

    @staticmethod
    def _parse_to_int(value):
        """Normalize a value into an integer."""
        if value in (None, False, ""):
            return False

        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _parse_to_float(value):
        """Normalize a value into a float."""
        if value in (None, False, ""):
            return False

        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _normalize_mac_address(value):
        """Return a canonical uppercase colon-separated MAC address."""
        if value in (None, False, ""):
            return False

        value_text = str(value).strip()
        hex_digits = re.sub(r"[^0-9A-Fa-f]", "", value_text)

        if len(hex_digits) != 12:
            return False

        mac_address = ":".join(hex_digits[index: index + 2] for index in range(0, 12, 2)).upper()
        if not MAC_RE.match(mac_address):
            return False

        return mac_address

    @api.model
    def _is_trmnl_api_debug_enabled(self):
        """Return True when verbose TRMNL API tracing is enabled (System Parameters)."""
        raw = self.env["ir.config_parameter"].sudo().get_param(TRMNL_API_DEBUG_PARAM, "")
        return str(raw).strip().lower() in ("1", "true", "yes", "on")

    @api.model
    def _generate_unique_friendly_id(self):
        """Generate a short unique friendly identifier."""
        for attempt in range(25):
            friendly_id = f"TRMNL-{secrets.token_hex(3).upper()}"
            if not self.sudo().search([("friendly_id", "=", friendly_id)], limit=1):
                return friendly_id

        raise ValidationError("Unable to generate a unique friendly ID.")