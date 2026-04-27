"""TRMNL device telemetry and log ingestion helpers."""

from __future__ import annotations

import datetime as dt

from odoo import api, fields, models

from .trmnl_device import APPROVAL_STATE_ACCEPTED


class TrmnlDeviceTelemetryMixin(models.Model):
    """Extend TRMNL devices with telemetry capture and log ingestion helpers.

    Telemetry written here reflects what the device *reported* and is always
    stored in read-only fields.  The admin-configurable ``desired_refresh_rate``
    field is intentionally left untouched so that the server can command a
    different interval without the device overwriting it on the next poll.

    Log ingestion only stores entries for devices in the ``accepted`` state.
    All other devices receive a 401 response without any data being persisted.
    """

    _inherit = "trmnl.device"

    # ------------------------------------------------------------------
    # display telemetry
    # ------------------------------------------------------------------

    @api.model
    def _apply_display_telemetry(self, headers):
        """Persist the latest telemetry snapshot reported by a display poll.

        Only ``refresh_rate`` (the device-reported value) is updated here.
        ``desired_refresh_rate`` (the admin-configured command) is never
        overwritten by incoming telemetry.
        """
        firmware_version = self._parse_to_string(headers.get("FW-Version"))
        refresh_rate = self._parse_to_int(headers.get("Refresh-Rate"))
        battery_voltage = self._parse_to_float(headers.get("Battery-Voltage"))
        rssi_dbm = self._parse_to_int(headers.get("RSSI"))
        display_width = self._parse_to_int(headers.get("Width"))
        display_height = self._parse_to_int(headers.get("Height"))
        special_function = self._parse_to_string(headers.get("special_function"))

        values = {"last_seen_at": fields.Datetime.now()}

        if firmware_version is not False:
            values["firmware_version"] = firmware_version
        if refresh_rate is not False:
            values["refresh_rate"] = refresh_rate
        if battery_voltage is not False:
            values["battery_voltage"] = battery_voltage
        if rssi_dbm is not False:
            values["rssi_dbm"] = rssi_dbm
        if display_width is not False:
            values["display_width"] = display_width
        if display_height is not False:
            values["display_height"] = display_height
        if special_function is not False:
            values["special_function"] = special_function

        self.with_context(trmnl_allow_identity_update=True).write(values)
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

    # ------------------------------------------------------------------
    # log ingestion
    # ------------------------------------------------------------------

    @api.model
    def _extract_log_entries(self, payload):
        """Return the raw log entries from a TRMNL ``/api/log`` payload."""
        if not isinstance(payload, dict):
            return []

        raw_entries = payload.get("logs")
        if raw_entries is None:
            return []

        if isinstance(raw_entries, dict):
            raw_entries = [raw_entries]

        if not isinstance(raw_entries, list):
            return []

        return [raw_entry for raw_entry in raw_entries if isinstance(raw_entry, dict)]

    @api.model
    def _unix_epoch_to_datetime(self, epoch_value):
        """Convert a Unix epoch integer to a naive UTC datetime suitable for Odoo.

        Returns ``False`` when the value is absent or cannot be parsed.
        Odoo's ``Datetime`` fields always store and expect naive UTC datetimes.
        """
        parsed_epoch = self._parse_to_int(epoch_value)
        if parsed_epoch is False:
            return False

        try:
            return dt.datetime.fromtimestamp(parsed_epoch, tz=dt.timezone.utc).replace(
                tzinfo=None
            )
        except (OSError, OverflowError, ValueError):
            return False

    @api.model
    def _prepare_log_values(self, device, entry):
        """Convert one raw TRMNL log entry into ``create()`` values."""
        log_id = self._parse_to_int(entry.get("id"))
        if log_id is False:
            return False

        values = {
            "device_id": device.id,
            "created_at": self._unix_epoch_to_datetime(entry.get("created_at")),
            "wifi_rssi_level": self._parse_to_int(entry.get("wifi_signal")),
            "wifi_status": self._parse_to_string(entry.get("wifi_status")),
            "refresh_rate": self._parse_to_int(entry.get("refresh_rate")),
            "time_since_last_sleep_start": self._parse_to_int(entry.get("sleep_duration")),
            "current_fw_version": self._parse_to_string(entry.get("firmware_version")),
            "special_function": self._parse_to_string(entry.get("special_function")),
            "battery_voltage": self._parse_to_float(entry.get("battery_voltage")),
            "wakeup_reason": self._parse_to_string(entry.get("wake_reason")),
            "free_heap_size": self._parse_to_int(entry.get("free_heap_size")),
            "max_alloc_size": self._parse_to_int(entry.get("max_alloc_size")),
            "log_id": log_id,
            "log_message": self._parse_to_string(entry.get("message")),
            "log_codeline": self._parse_to_int(entry.get("source_line")),
            "log_sourcefile": self._parse_to_string(entry.get("source_path")),
            "retry_attempt": self._parse_to_int(entry.get("retry")),
        }

        return {field_name: value for field_name, value in values.items() if value is not False}

    @api.model
    def _update_log_activity(self, device, created_count=0):
        """Touch the device after a log submission and update counters."""
        now_value = fields.Datetime.now()
        update_values = {
            "last_log_at": now_value,
            "last_seen_at": now_value,
        }

        if created_count:
            update_values["log_entry_count"] = (device.log_entry_count or 0) + created_count

        device.with_context(trmnl_allow_identity_update=True).write(update_values)

    @api.model
    def ingest_logs_from_payload(self, headers, payload):
        """Create log entries from the raw JSON payload sent by the device.

        Only devices in the ``accepted`` state have their logs stored.  Any
        other state (unknown_device, token_mismatch, or missing identity)
        results in an ``unauthorized`` status so the controller can return 401.
        """
        mac_address = self._normalize_mac_address(headers.get("ID"))
        token_value = self._parse_to_string(headers.get("Access-Token"))

        if not mac_address or not token_value:
            return 0, "missing_identity"

        device = self.find_by_mac_and_token(mac_address, token_value)
        if not device or device.approval_state != APPROVAL_STATE_ACCEPTED:
            return 0, "unauthorized"

        raw_entries = self._extract_log_entries(payload)
        if not raw_entries:
            self._update_log_activity(device)
            return 0, "empty"

        log_model = self.env["trmnl.device.log"].sudo()
        created_count = 0

        for raw_entry in raw_entries:
            log_values = self._prepare_log_values(device, raw_entry)
            if not log_values:
                continue

            existing_log = log_model.search(
                [("device_id", "=", device.id), ("log_id", "=", log_values["log_id"])],
                limit=1,
            )
            if existing_log:
                continue

            log_model.create(log_values)
            created_count += 1

        self._update_log_activity(device, created_count)
        return created_count, "stored" if created_count else "ignored"
