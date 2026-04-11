"""TRMNL configuration settings."""
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    """Expose TRMNL runtime configuration to administrators."""

    _inherit = "res.config.settings"

    trmnl_display_error_status = fields.Selection(
        string="Default Display Error Status",
        selection=[
            ("202", "Return 202"),
            ("500", "Return 500"),
        ],
        default="202",
        required=True,
        config_parameter="trmnl.display_error_status",
        help="Default status returned by /api/display when a device is unknown or unauthorized.",
    )
