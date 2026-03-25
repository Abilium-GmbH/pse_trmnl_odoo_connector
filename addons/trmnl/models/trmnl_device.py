from odoo import models, fields

class TrmnlDevice(models.Model):
    _name = "trmnl.device"
    _description = "TRMNL Device"

    name = fields.Char(required=True)
    webhook_url = fields.Char(required=True)
    active = fields.Boolean(default=True)

    last_sync_at = fields.Datetime()
    last_status = fields.Selection([
        ("ok", "OK"),
        ("error", "Error"),
    ])
