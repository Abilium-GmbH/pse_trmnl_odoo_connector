"""TRMNL device telemetry and log ingestion helpers."""

from __future__ import annotations

import datetime as dt

from odoo import api, fields, models

from .trmnl_device import APPROVAL_STATE_ACCEPTED, LAST_API_CALL_DISPLAY, LAST_API_CALL_LOG


class TrmnlDeviceTelemetryMixin(models.Model):
    """Extend TRMNL devices with telemetry capture and log ingestion helpers.

    Telemetry written here reflects what the device *reported* and is always
    stored in read-only fields.  The admin-configurable ``desired_refresh_rate``
    field is intentionally left untouched so that the server can command a
    different interval without the device overwriting it on the next poll.

    Log ingestion only stores entries for devices in the ``accepted`` state.
    Submissions from devices in any other state are ignored; the
    caller receives HTTP 401.
    """

    _inherit = "trmnl.device"

    # ------------------------------------------------------------------
    # display telemetry
    # ------------------------------------------------------------------

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

        self.write(values)
        return self

    def _record_display_served(self):
        """Update the last-seen timestamp and last API call for a successful display response."""
        self.ensure_one()
        now_value = fields.Datetime.now()
        self.write(
            {
                "last_display_at": now_value,
                "last_poll_at": now_value,
                "last_seen_at": now_value,
                "last_api_call": LAST_API_CALL_DISPLAY,
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
        self.write(update_values)
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
            "last_seen_at": now_value,
            "last_api_call": LAST_API_CALL_LOG,
        }
        device.write(update_values)

    @api.model
    def ingest_logs_from_payload(self, headers, payload):
        """Create log entries from the raw JSON payload sent by the device.

        Only devices in the ``accepted`` state have their logs stored.  For
        devices in any other state (unknown_device, token_mismatch, or missing
        identity) the submitted data is silently dropped and ``"unauthorized"``
        is returned so the controller can send HTTP 401.  No writes are made
        to the database for non-accepted devices.
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

        all_values = [
            self._prepare_log_values(device, raw_entry)
            for raw_entry in raw_entries
        ]
        valid_values = [v for v in all_values if v]

        if not valid_values:
            self._update_log_activity(device)
            return 0, "empty"

        candidate_log_ids = [v["log_id"] for v in valid_values]
        existing_log_ids = set(
            log_model.search(
                [("device_id", "=", device.id), ("log_id", "in", candidate_log_ids)]
            ).mapped("log_id")
        )
        seen_log_ids = set(existing_log_ids)
        new_values = []
        for values in valid_values:
            log_id = values["log_id"]
            if log_id in seen_log_ids:
                continue
            seen_log_ids.add(log_id)
            new_values.append(values)

        if new_values:
            log_model.create(new_values)
        created_count = len(new_values)

        self._update_log_activity(device)
        return created_count, "stored" if created_count else "ignored"
