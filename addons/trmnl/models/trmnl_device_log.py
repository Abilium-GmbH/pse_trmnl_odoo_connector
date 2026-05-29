"""TRMNL device log model."""

from odoo import api, fields, models


class TrmnlDeviceLog(models.Model):
    """Store log entries reported by TRMNL devices.

    Each entry corresponds to one item inside the ``logs`` array of a
    ``/api/log`` request.  The ``created_at`` field is stored as a UTC
    ``Datetime`` so that Odoo's web client can automatically convert it to
    the viewing user's local timezone for display.

    Individual log entries can be deleted by administrators directly from the
    device form view.  Deleting a device record removes all associated log
    entries automatically via the database cascade on ``device_id``.
    """

    _name = "trmnl.device.log"
    _description = "TRMNL device log entry"
    _rec_name = "name"
    _order = "created_at desc, id desc"

    _trmnl_device_log_unique_device_log_id = models.Constraint(
        "UNIQUE(device_id, log_id)",
        "The same log ID may only be stored once per device.",
    )

    # ondelete="cascade" ensures log entries are removed automatically
    # when the parent device record is deleted.
    device_id = fields.Many2one(
        comodel_name="trmnl.device",
        string="Device",
        required=True,
        ondelete="cascade",
        index=True,
    )

    created_at = fields.Datetime(
        string="Created At",
        index=True,
        help="UTC timestamp converted from the Unix epoch value reported by the device.",
    )
    wifi_rssi_level = fields.Integer(string="Wi-Fi RSSI Level")
    wifi_status = fields.Char(string="Wi-Fi Status")
    refresh_rate = fields.Integer(string="Refresh Rate")
    time_since_last_sleep_start = fields.Integer(string="Sleep Duration")
    current_fw_version = fields.Char(string="Firmware Version")
    special_function = fields.Char(string="Special Function")
    battery_voltage = fields.Float(string="Battery Voltage", digits=(16, 3))
    wakeup_reason = fields.Char(string="Wake Reason")
    free_heap_size = fields.Integer(string="Free Heap Size")
    max_alloc_size = fields.Integer(string="Max Alloc Size")

    log_id = fields.Integer(string="Device Log ID", required=True, index=True)
    log_message = fields.Text(string="Log Message")
    log_codeline = fields.Integer(string="Source Line")
    log_sourcefile = fields.Char(string="Source Path")
    retry_attempt = fields.Integer(string="Retry Attempt")

    name = fields.Char(
        string="Name",
        compute="_compute_name",
        store=True,
        readonly=True,
    )

    @api.depends("log_id", "log_message", "log_sourcefile", "log_codeline")
    def _compute_name(self):
        """Build a readable label for each log entry."""
        for log_entry in self:
            message_text = (log_entry.log_message or "").strip()
            if message_text:
                log_entry.name = f"{log_entry.log_id}: {message_text[:60]}"
                continue

            source_path = (log_entry.log_sourcefile or "").strip()
            source_line_value = log_entry.log_codeline

            if source_path and source_line_value not in (False, None):
                log_entry.name = f"{log_entry.log_id}: {source_path}:{source_line_value}"
            elif source_path:
                log_entry.name = f"{log_entry.log_id}: {source_path}"
            elif source_line_value not in (False, None):
                log_entry.name = f"{log_entry.log_id}: line {source_line_value}"
            else:
                log_entry.name = f"Log {log_entry.log_id}"
