from odoo import models, fields

class TrmnlDevice(models.Model):
    _name = "trmnl.device"
    _description = "TRMNL Display"

    name = fields.Char(string="Display Name", required=True)
    device_id = fields.Char(string="Device ID")
    last_sync = fields.Datetime(string="Last Sync")
    active = fields.Boolean(string="Active", default=True)