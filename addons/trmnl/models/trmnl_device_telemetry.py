"""TRMNL device telemetry and log ingestion helpers."""

from __future__ import annotations

from odoo import api, fields, models

from .trmnl_device import DEFAULT_REFRESH_RATE


class TrmnlDeviceTelemetryMixin(models.Model):
    """Extend TRMNL devices with telemetry capture and log ingestion helpers."""

    _inherit = "trmnl.device"

    ##################################################
    # display telemetry
    ##################################################

    @api.model
    def _apply_display_telemetry(self, headers):
        """Persist the latest telemetry snapshot reported by a display poll."""
        firmware_version = self._parse_to_string(headers.get("FW-Version"))
        refresh_rate = self._parse_to_int(headers.get("Refresh-Rate"))
        battery_voltage = self._parse_to_float(headers.get("Battery-Voltage"))
        rssi_dbm = self._parse_to_int(headers.get("RSSI"))
        display_width = self._parse_to_int(headers.get("Width"))
        display_height = self._parse_to_int(headers.get("Height"))
        special_function = self._parse_to_string(headers.get("special_function"))

        values = {
            "last_seen_at": fields.Datetime.now(),
        }
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

    ##################################################
    # log ingestion
    ##################################################

    @api.model
    def _extract_log_entries(self, payload):
        """Normalize the nested payload structure returned by the device."""
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
        """Convert one raw device log entry into create() values."""
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
            "current_fw_version": self._parse_to_string(status_stamp.get("current_fw_version")),
            "special_function": self._parse_to_string(status_stamp.get("special_function")),
            "battery_voltage": self._parse_to_float(status_stamp.get("battery_voltage")),
            "wakeup_reason": self._parse_to_string(status_stamp.get("wakeup_reason")),
            "free_heap_size": self._parse_to_int(status_stamp.get("free_heap_size")),
            "max_alloc_size": self._parse_to_int(status_stamp.get("max_alloc_size")),
            "log_id": log_id,
            "log_message": self._parse_to_string(entry.get("log_message")),
            "log_codeline": self._parse_to_int(entry.get("log_codeline")),
            "log_sourcefile": self._parse_to_string(entry.get("log_sourcefile")),
            "filename_current": self._parse_to_string(additional_info.get("filename_current")),
            "filename_new": self._parse_to_string(additional_info.get("filename_new")),
        }

        return {field_name: value for field_name, value in values.items() if value is not False}

    @api.model
    def ingest_logs_from_payload(self, headers, payload):
        """Create log entries from the raw JSON payload sent by the device."""
        mac_address = self._normalize_mac_address(headers.get("ID"))
        token_value = self._parse_to_string(headers.get("Access-Token"))

        if not mac_address or not token_value:
            return 0, "missing_identity"

        device = self.find_by_mac_and_token(mac_address, token_value)
        if not device or device.approval_state != "approved":
            return 0, "unauthorized"

        entries = self._extract_log_entries(payload)
        if not entries:
            now_value = fields.Datetime.now()
            device.with_context(trmnl_allow_identity_update=True).write(
                {
                    "last_log_at": now_value,
                    "last_seen_at": now_value,
                }
            )
            return 0, "empty"

        log_model = self.env["trmnl.device.log"].sudo()
        created_count = 0

        for entry in entries:
            values = self._prepare_log_values(device, entry)
            if not values:
                continue

            existing_log = log_model.search(
                [("device_id", "=", device.id), ("log_id", "=", values["log_id"])],
                limit=1,
            )
            if existing_log:
                continue

            log_model.create(values)
            created_count += 1

        now_value = fields.Datetime.now()
        device.with_context(trmnl_allow_identity_update=True).write(
            {
                "last_log_at": now_value,
                "last_seen_at": now_value,
                "log_entry_count": (device.log_entry_count or 0) + created_count,
            }
        )
        return created_count, "stored" if created_count else "ignored"
