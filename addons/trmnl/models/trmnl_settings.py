"""TRMNL configuration settings."""

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Expose TRMNL runtime configuration to administrators."""

    _inherit = "res.config.settings"

    trmnl_unknown_device_policy = fields.Selection(
        string="Unknown Device Policy",
        selection=[
            ("error", "Return error response"),
            ("reset_firmware", "Send reset_firmware"),
            ("auto_accept", "Auto-approve and serve"),
        ],
        default="error",
        required=True,
        config_parameter="trmnl.unknown_device_policy",
        help="How /api/display should respond when an unregistered device contacts Odoo.",
    )
