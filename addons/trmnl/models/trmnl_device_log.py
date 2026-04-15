"""TRMNL device log model."""

from __future__ import annotations

from odoo import api, fields, models


class TrmnlDeviceLog(models.Model):
    """Store raw log entries reported by TRMNL devices."""

    _name = "trmnl.device.log"
    _description = "TRMNL device log entry"
    _rec_name = "name"
    _order = "creation_timestamp desc, id desc"

    _trmnl_device_log_unique_device_log_id = models.Constraint(
        "UNIQUE(device_id, log_id)",
        "The same log ID may only be stored once per device.",
    )

    device_id = fields.Many2one(
        comodel_name="trmnl.device",
        string="Device",
        required=True,
        ondelete="cascade",
        index=True,
    )

    creation_timestamp = fields.Integer(string="Creation Timestamp")
    wifi_rssi_level = fields.Integer(string="Wi-Fi RSSI Level")
    wifi_status = fields.Char(string="Wi-Fi Status")
    refresh_rate = fields.Integer(string="Refresh Rate")
    time_since_last_sleep_start = fields.Integer(string="Time Since Last Sleep Start")
    current_fw_version = fields.Char(string="Current Firmware Version")
    special_function = fields.Char(string="Special Function")
    battery_voltage = fields.Float(string="Battery Voltage", digits=(16, 3))
    wakeup_reason = fields.Char(string="Wakeup Reason")
    free_heap_size = fields.Integer(string="Free Heap Size")
    max_alloc_size = fields.Integer(string="Max Alloc Size")
    log_id = fields.Integer(string="Log ID", required=True, index=True)
    log_message = fields.Text(string="Log Message")
    log_codeline = fields.Integer(string="Log Codeline")
    log_sourcefile = fields.Char(string="Log Sourcefile")
    filename_current = fields.Char(string="Current Filename")
    filename_new = fields.Char(string="New Filename")

    name = fields.Char(
        string="Name",
        compute="_compute_name",
        store=True,
        readonly=True,
    )

    @api.depends("log_id", "log_message")
    def _compute_name(self):
        """Build a readable label for each log entry."""
        for log_entry in self:
            message_text = (log_entry.log_message or "").strip()
            if message_text:
                log_entry.name = f"{log_entry.log_id}: {message_text[:60]}"
            else:
                log_entry.name = f"Log {log_entry.log_id}"
