from odoo import api, fields, models, _


class TrmnlDeviceLog(models.Model):
    _name = "trmnl.device.log"
    _description = "TRMNL device log entry"
    _rec_name = "name"
    _order = "creation_timestamp desc, id desc"

    _sql_constraints = [
        (
            "unique_device_log_id",
            "UNIQUE(device_id, log_id)",
            "Log ID must be unique per device.",
        ),
    ]

    name = fields.Char(
        string="Name",
        compute="_compute_name",
        store=True,
        readonly=True,
        help="Human-readable label for the log entry.",
    )

    device_id = fields.Many2one(
        comodel_name="trmnl.device",
        string="Device",
        required=True,
        index=True,
        ondelete="cascade",
        help="TRMNL device that emitted the log entry.",
    )

    creation_timestamp = fields.Integer(
        string="Creation Timestamp",
        index=True,
        help="Unix epoch seconds reported by the device.",
    )

    wifi_rssi_level = fields.Integer(
        string="Wi-Fi RSSI Level",
        help="Wi-Fi signal strength at the moment of the error.",
    )

    wifi_status = fields.Char(
        string="Wi-Fi Status",
        help="Wi-Fi status reported by the device.",
    )

    refresh_rate = fields.Integer(
        string="Refresh Rate (s)",
        help="Configured refresh rate reported by the device.",
    )

    time_since_last_sleep_start = fields.Integer(
        string="Time Since Last Sleep Start (s)",
        help="Time elapsed since the last sleep cycle started.",
    )

    current_fw_version = fields.Char(
        string="Current Firmware Version",
        help="Firmware version reported in the log payload.",
    )

    special_function = fields.Char(
        string="Special Function",
        help="Special function active when the error occurred.",
    )

    battery_voltage = fields.Float(
        string="Battery Voltage (V)",
        digits=(16, 2),
        help="Battery voltage reported in the log payload.",
    )

    wakeup_reason = fields.Char(
        string="Wakeup Reason",
        help="Wakeup reason reported by the device.",
    )

    free_heap_size = fields.Integer(
        string="Free Heap Size (bytes)",
        help="Free heap memory reported by the device.",
    )

    max_alloc_size = fields.Integer(
        string="Max Alloc Size (bytes)",
        help="Maximum allocatable heap size reported by the device.",
    )

    log_id = fields.Integer(
        string="Log ID",
        required=True,
        index=True,
        help="Monotonically increasing identifier reported by the device.",
    )

    log_message = fields.Text(
        string="Log Message",
        help="Human-readable error message reported by the device.",
    )

    log_codeline = fields.Integer(
        string="Log Code Line",
        help="Source code line reported by the device.",
    )

    log_sourcefile = fields.Char(
        string="Log Source File",
        help="Source file reported by the device.",
    )

    filename_current = fields.Char(
        string="Current Filename",
        help="Image filename that was active when the error happened.",
    )

    filename_new = fields.Char(
        string="New Filename",
        help="Image filename the device was trying to fetch.",
    )

    retry_attempt = fields.Integer(
        string="Retry Attempt",
        help="Retry counter reported by the device, when present.",
    )

    @api.depends("log_id", "log_message")
    def _compute_name(self):
        for record in self:
            message = (record.log_message or "").strip()
            if len(message) > 60:
                message = f"{message[:57]}..."
            if record.log_id and message:
                record.name = f"#{record.log_id} - {message}"
            elif record.log_id:
                record.name = f"#{record.log_id}"
            else:
                record.name = message or _("TRMNL Log Entry")
