import base64
import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

MAC_RE = re.compile(r"^[0-9A-F]{2}(?::[0-9A-F]{2}){5}$")
API_TOKEN_PBKDF2_ITERATIONS = 310_000
API_TOKEN_BYTES = 32


class TrmnlDevice(models.Model):
    _name = "trmnl.device"
    _description = "TRMNL E-ink display device"
    _rec_name = "friendly_id"

    _sql_constraints = [
        (
            "unique_device_mac_address",
            "UNIQUE(mac_address)",
            "MAC address must be unique.",
        ),
        (
            "unique_device_friendly_id",
            "UNIQUE(friendly_id)",
            "Friendly ID must be unique.",
        ),
    ]

    BATTERY_MIN_VOLTAGE = 3.0
    BATTERY_MAX_VOLTAGE = 4.2
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
        help="Salted hash of the API token. The plain token is never stored.",
    )

    api_token_salt = fields.Char(
        string="API Token Salt",
        readonly=True,
        copy=False,
        help="Salt used to hash the API token.",
    )

    api_token_created_at = fields.Datetime(
        string="API Token Created At",
        readonly=True,
        copy=False,
        help="When the current API token was first issued.",
    )

    api_token_rotated_at = fields.Datetime(
        string="API Token Rotated At",
        readonly=True,
        copy=False,
        help="When the current API token was last rotated.",
    )

    approval_state = fields.Selection(
        string="Approval State",
        selection=[
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="pending",
        required=True,
        index=True,
        copy=False,
        help="Whether the device is allowed to receive normal display payloads.",
    )

    registration_source = fields.Selection(
        string="Registration Source",
        selection=[
            ("manual", "Manual"),
            ("setup", "Setup"),
            ("display", "Display"),
        ],
        default="manual",
        required=True,
        index=True,
        copy=False,
        help="How the device record first entered the system.",
    )

    next_display_action = fields.Selection(
        string="Next Display Action",
        selection=[
            ("normal", "Normal"),
            ("reset_firmware", "Reset Firmware"),
        ],
        default="normal",
        required=True,
        index=True,
        copy=False,
        help="One-time action to apply the next time the device calls /api/display.",
    )

    first_seen_at = fields.Datetime(
        string="First Seen At",
        readonly=True,
        copy=False,
        help="When the device was first observed by Odoo.",
    )

    last_seen_at = fields.Datetime(
        string="Last Seen At",
        readonly=True,
        copy=False,
        help="Most recent authenticated or observed device contact.",
    )

    last_setup_at = fields.Datetime(
        string="Last Setup At",
        readonly=True,
        copy=False,
    )

    last_display_at = fields.Datetime(
        string="Last Display At",
        readonly=True,
        copy=False,
    )

    last_log_at = fields.Datetime(
        string="Last Log At",
        readonly=True,
        copy=False,
    )

    last_access_denied_at = fields.Datetime(
        string="Last Access Denied At",
        readonly=True,
        copy=False,
    )

    approved_at = fields.Datetime(
        string="Approved At",
        readonly=True,
        copy=False,
    )

    rejected_at = fields.Datetime(
        string="Rejected At",
        readonly=True,
        copy=False,
    )

    setup_request_count = fields.Integer(
        string="Setup Request Count",
        default=0,
        copy=False,
        help="How many setup requests have been handled for this device.",
    )

    display_request_count = fields.Integer(
        string="Display Request Count",
        default=0,
        copy=False,
        help="How many authenticated display requests have been handled.",
    )

    display_denied_count = fields.Integer(
        string="Display Denied Count",
        default=0,
        copy=False,
        help="How many display requests were denied because the device was not allowed.",
    )

    invalid_token_count = fields.Integer(
        string="Invalid Token Count",
        default=0,
        copy=False,
        help="How many display requests presented an invalid API token.",
    )

    log_entry_count = fields.Integer(
        string="Log Entry Count",
        default=0,
        copy=False,
        help="How many log entries have been stored for this device.",
    )

    firmware_version = fields.Char(
        string="Firmware Version",
        copy=False,
        help="Firmware version reported by the device.",
    )

    refresh_rate = fields.Integer(
        string="Refresh Rate (s)",
        copy=False,
        help="Refresh interval reported by the device.",
    )

    battery_voltage = fields.Float(
        string="Battery Voltage (V)",
        digits=(16, 2),
        copy=False,
        help="Battery voltage reported by the device.",
    )

    battery_percentage = fields.Integer(
        string="Battery (%)",
        compute="_compute_battery_percentage",
        store=True,
        readonly=True,
        help="Estimated battery percentage derived from battery voltage.",
    )

    rssi_dbm = fields.Integer(
        string="RSSI (dBm)",
        copy=False,
        help="Wi-Fi signal strength reported by the device.",
    )

    rssi_quality = fields.Selection(
        string="Signal Quality",
        selection=[
            ("very_strong", "Very Strong"),
            ("strong", "Strong"),
            ("moderate", "Moderate"),
            ("weak", "Weak"),
            ("very_weak", "Very Weak"),
        ],
        compute="_compute_rssi_quality",
        store=True,
        readonly=True,
        help="Human-readable signal quality derived from RSSI.",
    )

    display_width = fields.Integer(
        string="Display Width",
        copy=False,
        help="Display width reported by the device.",
    )

    display_height = fields.Integer(
        string="Display Height",
        copy=False,
        help="Display height reported by the device.",
    )

    image_url = fields.Char(
        string="Image URL",
        default="https://sampleimg.com/800x480?bg=000000&fg=ffffff&text=Abilium&format=png",
        copy=False,
        help="Current image URL returned to the device on /api/display and /api/setup.",
    )

    message = fields.Char(
        string="Setup Message",
        copy=False,
        help="Optional message returned during setup.",
    )

    @staticmethod
    def _parse_to_int(raw_value):
        if raw_value in (None, ""):
            return False
        try:
            return int(str(raw_value).strip())
        except (TypeError, ValueError, AttributeError):
            return False

    @staticmethod
    def _parse_to_float(raw_value):
        if raw_value in (None, ""):
            return False
        try:
            return float(str(raw_value).strip())
        except (TypeError, ValueError, AttributeError):
            return False

    @staticmethod
    def _parse_to_string(raw_value):
        if raw_value in (None, ""):
            return False
        try:
            return str(raw_value).strip()
        except (TypeError, ValueError, AttributeError):
            return False

    @classmethod
    def _normalize_mac_address(cls, raw_value):
        mac = cls._parse_to_string(raw_value)
        if not mac:
            return False
        mac = mac.upper()
        if not MAC_RE.match(mac):
            return False
        return mac

    @staticmethod
    def _utc_now():
        return datetime.utcnow().replace(microsecond=0)

    def _build_display_filename(self, timestamp=None):
        timestamp = timestamp or self._utc_now()
        return f"{self.friendly_id}-{timestamp.strftime('%Y-%m-%dT%H:%M:%S')}"

    def _build_setup_filename(self):
        return self.SETUP_FILENAME

    @api.model
    def _generate_unique_friendly_id(self):
        for _attempt in range(20):
            friendly_id = secrets.token_hex(3).upper()
            if not self.sudo().search_count([("friendly_id", "=", friendly_id)]):
                return friendly_id
        raise ValidationError(_("Could not generate a unique friendly ID."))

    @staticmethod
    def _generate_api_token():
        return secrets.token_urlsafe(API_TOKEN_BYTES).rstrip("=")

    @classmethod
    def _hash_api_token(cls, token, salt=None):
        if not token:
            return False

        salt_bytes = salt or secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            token.encode("utf-8"),
            salt_bytes,
            API_TOKEN_PBKDF2_ITERATIONS,
        )
        return {
            "api_token_hash": base64.b64encode(digest).decode("ascii"),
            "api_token_salt": base64.b64encode(salt_bytes).decode("ascii"),
        }

    @classmethod
    def _build_api_token_material(cls):
        raw_token = cls._generate_api_token()
        return raw_token, cls._hash_api_token(raw_token)

    def _verify_api_token(self, raw_token):
        self.ensure_one()
        if not raw_token or not self.api_token_hash or not self.api_token_salt:
            return False

        try:
            salt = base64.b64decode(self.api_token_salt.encode("ascii"))
            expected_hash = base64.b64decode(self.api_token_hash.encode("ascii"))
        except (ValueError, AttributeError, TypeError):
            return False

        candidate_hash = hashlib.pbkdf2_hmac(
            "sha256",
            raw_token.encode("utf-8"),
            salt,
            API_TOKEN_PBKDF2_ITERATIONS,
        )
        return hmac.compare_digest(candidate_hash, expected_hash)

    @api.model
    def _get_unknown_device_policy(self):
        policy = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("trmnl.unknown_device_policy", "error")
            or "error"
        )
        policy = str(policy).strip().lower()
        if policy not in {"error", "reset_firmware", "auto_accept"}:
            return "error"
        return policy

    @api.model
    def _create_placeholder_device(self, mac_address, token=None, source="display"):
        values = {
            "mac_address": mac_address,
            "friendly_id": self._generate_unique_friendly_id(),
            "approval_state": "pending",
            "registration_source": source,
            "first_seen_at": fields.Datetime.now(),
            "last_seen_at": fields.Datetime.now(),
        }

        if token:
            token_values = self._hash_api_token(token)
            if token_values:
                values.update(token_values)
                values["api_token_created_at"] = fields.Datetime.now()

        return self.sudo().create(values)

    def _rotate_api_token(self):
        self.ensure_one()
        raw_token, token_values = self._build_api_token_material()
        token_values["api_token_rotated_at"] = fields.Datetime.now()
        if not self.api_token_created_at:
            token_values["api_token_created_at"] = fields.Datetime.now()
        self.with_context(trmnl_allow_identity_update=True).write(token_values)
        return raw_token

    @api.depends("battery_voltage")
    def _compute_battery_percentage(self):
        for device in self:
            device.battery_percentage = device._voltage_to_percentage(
                device.battery_voltage
            )

    @api.depends("rssi_dbm")
    def _compute_rssi_quality(self):
        for device in self:
            device.rssi_quality = device._rssi_to_quality(device.rssi_dbm)

    @classmethod
    def _voltage_to_percentage(cls, voltage):
        if voltage in (False, None):
            return False

        if voltage < cls.BATTERY_MIN_VOLTAGE or voltage > cls.BATTERY_MAX_VOLTAGE:
            _logger.warning(
                "TRMNL device reported out-of-range battery voltage: %s V "
                "(expected %.2f..%.2f V)",
                voltage,
                cls.BATTERY_MIN_VOLTAGE,
                cls.BATTERY_MAX_VOLTAGE,
            )

        clamped_voltage = max(
            cls.BATTERY_MIN_VOLTAGE,
            min(cls.BATTERY_MAX_VOLTAGE, voltage),
        )
        span = cls.BATTERY_MAX_VOLTAGE - cls.BATTERY_MIN_VOLTAGE
        percent = ((clamped_voltage - cls.BATTERY_MIN_VOLTAGE) / span) * 100.0
        return int(round(percent))

    @classmethod
    def _rssi_to_quality(cls, rssi):
        if rssi in (False, None):
            return False
        if rssi >= -50:
            return "very_strong"
        if rssi >= -60:
            return "strong"
        if rssi >= -70:
            return "moderate"
        if rssi >= -80:
            return "weak"
        return "very_weak"

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals_list = []

        for vals in vals_list:
            vals = dict(vals)

            mac = self._normalize_mac_address(vals.get("mac_address"))
            if not mac:
                raise ValidationError(_("MAC address is required and must be valid."))

            vals["mac_address"] = mac
            if not vals.get("friendly_id"):
                vals["friendly_id"] = self._generate_unique_friendly_id()

            if vals.pop("_issue_api_token", False):
                if not vals.get("api_token_hash") or not vals.get("api_token_salt"):
                    raw_token, token_values = self._build_api_token_material()
                    vals.update(token_values)

            prepared_vals_list.append(vals)

        created_records = super().create(prepared_vals_list)
        return created_records

    def write(self, vals):
        protected_fields = {"mac_address", "friendly_id"}
        if protected_fields.intersection(vals.keys()) and not self.env.context.get(
            "trmnl_allow_identity_update"
        ):
            raise ValidationError(
                _("MAC address and Friendly ID cannot be changed once set.")
            )
        return super().write(vals)

    @api.model
    def upsert_from_setup_headers(self, headers):
        mac = self._normalize_mac_address(headers.get("ID"))
        if not mac:
            raise ValidationError(
                _("TRMNL setup request is missing a valid ID header.")
            )

        firmware_version = self._parse_to_string(headers.get("FW-Version"))
        now = fields.Datetime.now()

        device = self.sudo().search([("mac_address", "=", mac)], limit=1)
        if device:
            raw_token = device._rotate_api_token()
            values = {
                "approval_state": "approved",
                "approved_at": now,
                "last_setup_at": now,
                "last_seen_at": now,
                "next_display_action": "normal",
                "registration_source": "setup",
                "setup_request_count": (device.setup_request_count or 0) + 1,
            }
            if firmware_version is not False:
                values["firmware_version"] = firmware_version

            device.with_context(trmnl_allow_identity_update=True).write(values)
            return device, raw_token, "rotated"

        raw_token, token_values = self._build_api_token_material()
        values = {
            "mac_address": mac,
            "friendly_id": self._generate_unique_friendly_id(),
            "approval_state": "approved",
            "approved_at": now,
            "api_token_created_at": now,
            "last_setup_at": now,
            "last_seen_at": now,
            "next_display_action": "normal",
            "registration_source": "setup",
            "setup_request_count": 1,
        }
        values.update(token_values)
        if firmware_version is not False:
            values["firmware_version"] = firmware_version

        device = self.sudo().create(values)
        return device, raw_token, "created"

    @api.model
    def update_from_display_headers(self, headers):
        mac = self._normalize_mac_address(headers.get("ID"))
        if not mac:
            raise ValidationError(
                _("TRMNL display request is missing a valid ID header.")
            )

        device = self.sudo().search([("mac_address", "=", mac)], limit=1)
        if not device:
            raise ValidationError(
                _("TRMNL device with MAC %s is not registered.") % mac
            )

        values = {
            "refresh_rate": self._parse_to_int(headers.get("Refresh-Rate")),
            "battery_voltage": self._parse_to_float(headers.get("Battery-Voltage")),
            "firmware_version": self._parse_to_string(headers.get("FW-Version")),
            "rssi_dbm": self._parse_to_int(headers.get("RSSI")),
            "display_width": self._parse_to_int(headers.get("Width")),
            "display_height": self._parse_to_int(headers.get("Height")),
            "last_display_at": fields.Datetime.now(),
            "last_seen_at": fields.Datetime.now(),
            "display_request_count": (device.display_request_count or 0) + 1,
        }

        values = {key: value for key, value in values.items() if value is not False}
        device.with_context(trmnl_allow_identity_update=True).write(values)
        return device

    def _record_access_denied(self, reason="invalid_token"):
        self.ensure_one()
        now = fields.Datetime.now()
        values = {
            "last_access_denied_at": now,
            "last_seen_at": now,
        }

        if reason == "invalid_token":
            values["invalid_token_count"] = (self.invalid_token_count or 0) + 1
        else:
            values["display_denied_count"] = (self.display_denied_count or 0) + 1

        self.with_context(trmnl_allow_identity_update=True).write(values)
        return self

    def _approve_record(self, source="manual"):
        self.ensure_one()
        now = fields.Datetime.now()
        values = {
            "approval_state": "approved",
            "approved_at": now,
            "next_display_action": "normal",
            "registration_source": source,
        }
        self.with_context(trmnl_allow_identity_update=True).write(values)
        return self

    def _reject_record(self):
        self.ensure_one()
        now = fields.Datetime.now()
        values = {
            "approval_state": "rejected",
            "next_display_action": "normal",
            "rejected_at": now,
        }
        self.with_context(trmnl_allow_identity_update=True).write(values)
        return self

    def action_approve_device(self):
        for device in self:
            device._approve_record(source="manual")
        return True

    def action_reject_device(self):
        for device in self:
            device._reject_record()
        return True

    def action_queue_firmware_reset(self):
        self.with_context(trmnl_allow_identity_update=True).write(
            {"next_display_action": "reset_firmware"}
        )
        return True

    def action_clear_queued_action(self):
        self.with_context(trmnl_allow_identity_update=True).write(
            {"next_display_action": "normal"}
        )
        return True

    @api.model
    def find_by_mac_and_token(self, mac_address, api_token):
        mac = self._normalize_mac_address(mac_address)
        token = self._parse_to_string(api_token)
        if not mac or not token:
            return self.browse()

        device = self.sudo().search([("mac_address", "=", mac)], limit=1)
        if device and device._verify_api_token(token):
            return device
        return self.browse()

    @api.model
    def build_setup_error_response(self, message=""):
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
        return {
            "status": status,
            "filename": "",
            "image_name": "",
            "image_url": "",
            "image_url_timeout": 0,
            "action": "",
            "firmware_url": "",
            "refresh_rate": 1800,
            "reset_firmware": False,
            "special_function": "none",
            "update_firmware": False,
        }

    def build_display_reset_response(self):
        self.ensure_one()
        payload = self.build_display_error_response(status=0)
        payload["reset_firmware"] = True
        return payload

    @api.model
    def build_no_user_display_response(self):
        return {
            "status": 202,
            "filename": "",
            "image_name": "",
            "image_url": "",
            "image_url_timeout": 0,
            "action": "",
            "firmware_url": "",
            "refresh_rate": 1800,
            "reset_firmware": False,
            "special_function": "none",
            "update_firmware": False,
        }

    def build_display_response(self):
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
            "refresh_rate": self.refresh_rate or 1800,
            "reset_firmware": False,
            "special_function": "none",
            "update_firmware": False,
        }

    @api.model
    def _extract_log_entries(self, payload):
        if not isinstance(payload, dict):
            return []

        log_container = payload.get("log") or {}
        if not isinstance(log_container, dict):
            return []

        entries = log_container.get("logs_array") or []
        if isinstance(entries, dict):
            entries = [entries]

        if not isinstance(entries, list):
            return []

        return [entry for entry in entries if isinstance(entry, dict)]

    @api.model
    def _prepare_log_values(self, device, entry):
        status_stamp = entry.get("device_status_stamp") or {}
        additional_info = entry.get("additional_info") or {}

        if not isinstance(status_stamp, dict):
            status_stamp = {}
        if not isinstance(additional_info, dict):
            additional_info = {}

        log_id = self._parse_to_int(entry.get("log_id"))
        if log_id is False:
            return False

        values = {
            "device_id": device.id,
            "creation_timestamp": self._parse_to_int(entry.get("creation_timestamp")),
            "wifi_rssi_level": self._parse_to_int(status_stamp.get("wifi_rssi_level")),
            "wifi_status": self._parse_to_string(status_stamp.get("wifi_status")),
            "refresh_rate": self._parse_to_int(status_stamp.get("refresh_rate")),
            "time_since_last_sleep_start": self._parse_to_int(
                status_stamp.get("time_since_last_sleep_start")
            ),
            "current_fw_version": self._parse_to_string(
                status_stamp.get("current_fw_version")
            ),
            "special_function": self._parse_to_string(
                status_stamp.get("special_function")
            ),
            "battery_voltage": self._parse_to_float(
                status_stamp.get("battery_voltage")
            ),
            "wakeup_reason": self._parse_to_string(status_stamp.get("wakeup_reason")),
            "free_heap_size": self._parse_to_int(status_stamp.get("free_heap_size")),
            "max_alloc_size": self._parse_to_int(status_stamp.get("max_alloc_size")),
            "log_id": log_id,
            "log_message": self._parse_to_string(entry.get("log_message")),
            "log_codeline": self._parse_to_int(entry.get("log_codeline")),
            "log_sourcefile": self._parse_to_string(entry.get("log_sourcefile")),
            "filename_current": self._parse_to_string(
                additional_info.get("filename_current")
            ),
            "filename_new": self._parse_to_string(additional_info.get("filename_new")),
            "retry_attempt": self._parse_to_int(additional_info.get("retry_attempt")),
        }

        return {key: value for key, value in values.items() if value is not False}

    @api.model
    def ingest_logs_from_payload(self, headers, payload):
        mac = self._normalize_mac_address(headers.get("ID"))
        token = self._parse_to_string(headers.get("Access-Token"))
        if not mac or not token:
            return self.browse(), 0, "missing_identity"

        device = self.find_by_mac_and_token(mac, token)
        if not device or device.approval_state != "approved":
            return self.browse(), 0, "unauthorized"

        entries = self._extract_log_entries(payload)
        if not entries:
            device.with_context(trmnl_allow_identity_update=True).write(
                {
                    "last_log_at": fields.Datetime.now(),
                    "last_seen_at": fields.Datetime.now(),
                }
            )
            return device, 0, "empty"

        Log = self.env["trmnl.device.log"].sudo()
        created_count = 0

        for entry in entries:
            values = self._prepare_log_values(device, entry)
            if not values:
                continue

            existing = Log.search(
                [("device_id", "=", device.id), ("log_id", "=", values["log_id"])],
                limit=1,
            )
            if existing:
                continue

            Log.create(values)
            created_count += 1

        device.with_context(trmnl_allow_identity_update=True).write(
            {
                "last_log_at": fields.Datetime.now(),
                "last_seen_at": fields.Datetime.now(),
                "log_entry_count": (device.log_entry_count or 0) + created_count,
            }
        )
        return device, created_count, "stored" if created_count else "ignored"

    @api.model
    def resolve_display_request(self, headers):
        mac = self._normalize_mac_address(headers.get("ID"))
        token = self._parse_to_string(headers.get("Access-Token"))

        if not mac:
            return (
                self.browse(),
                self.build_no_user_display_response(),
                "missing_identity",
            )

        policy = self._get_unknown_device_policy()
        now = fields.Datetime.now()
        device = self.sudo().search([("mac_address", "=", mac)], limit=1)

        if not device:
            if token and policy == "auto_accept":
                device = self._create_placeholder_device(
                    mac, token=token, source="display"
                )
                device.with_context(trmnl_allow_identity_update=True).write(
                    {
                        "approval_state": "approved",
                        "approved_at": now,
                        "registration_source": "display",
                    }
                )
                self._copy_display_headers_to_device(device, headers)
                return device, device.build_display_response(), "auto_approved"

            device = self._create_placeholder_device(mac, token=token, source="display")
            if policy == "reset_firmware":
                device._record_access_denied(reason="pending")
                device.with_context(trmnl_allow_identity_update=True).write(
                    {"next_display_action": "reset_firmware"}
                )
                return device, device.build_display_reset_response(), "unknown_reset"

            device._record_access_denied(reason="pending")
            return device, device.build_display_error_response(status=404), "unknown"

        if not token:
            device._record_access_denied(reason="invalid_token")
            return (
                device,
                device.build_display_error_response(status=403),
                "invalid_token",
            )

        if not device._verify_api_token(token):
            device._record_access_denied(reason="invalid_token")
            return (
                device,
                device.build_display_error_response(status=403),
                "invalid_token",
            )

        if device.approval_state == "rejected":
            device._record_access_denied(reason="rejected")
            return device, device.build_display_error_response(status=403), "rejected"

        if device.approval_state == "pending":
            if policy == "auto_accept":
                device._approve_record(source="display")
                self._copy_display_headers_to_device(device, headers)
                return device, device.build_display_response(), "auto_approved"

            device._record_access_denied(reason="pending")
            if policy == "reset_firmware":
                device.with_context(trmnl_allow_identity_update=True).write(
                    {"next_display_action": "reset_firmware"}
                )
                return device, device.build_display_reset_response(), "pending_reset"

            return device, device.build_display_error_response(status=404), "pending"

        self._copy_display_headers_to_device(device, headers)

        if device.next_display_action == "reset_firmware":
            device.with_context(trmnl_allow_identity_update=True).write(
                {"next_display_action": "normal"}
            )
            return device, device.build_display_reset_response(), "reset"

        return device, device.build_display_response(), "display"

    @api.model
    def _copy_display_headers_to_device(self, device, headers):
        values = {
            "refresh_rate": self._parse_to_int(headers.get("Refresh-Rate")),
            "battery_voltage": self._parse_to_float(headers.get("Battery-Voltage")),
            "firmware_version": self._parse_to_string(headers.get("FW-Version")),
            "rssi_dbm": self._parse_to_int(headers.get("RSSI")),
            "display_width": self._parse_to_int(headers.get("Width")),
            "display_height": self._parse_to_int(headers.get("Height")),
            "last_display_at": fields.Datetime.now(),
            "last_seen_at": fields.Datetime.now(),
            "display_request_count": (device.display_request_count or 0) + 1,
        }
        values = {key: value for key, value in values.items() if value is not False}
        device.with_context(trmnl_allow_identity_update=True).write(values)
        return device
