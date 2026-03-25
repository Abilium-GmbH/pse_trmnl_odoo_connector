from odoo import models, fields

class TrmnlRenderLog(models.Model):
    _name = "trmnl.render.log"
    _description = "TRMNL Render Log"

    profile_id = fields.Many2one("trmnl.profile")
    device_id = fields.Many2one("trmnl.device")

    status = fields.Selection([
        ("ok", "OK"),
        ("error", "Error"),
    ])

    error_message = fields.Text()
    create_date = fields.Datetime()
