"""TRMNL configuration settings."""

from odoo import fields, models

from .trmnl_device import DISPLAY_POLICY_SELECTION, DISPLAY_POLICY_ERROR


class ResConfigSettings(models.TransientModel):
    """Expose TRMNL runtime configuration to administrators."""

    _inherit = "res.config.settings"

    trmnl_display_unknown_device_policy = fields.Selection(
        string="Default TRMNL display behavior",
        selection=DISPLAY_POLICY_SELECTION,
        default=DISPLAY_POLICY_ERROR,
        required=True,
        config_parameter="trmnl.display_unknown_device_policy",
        help=(
            "Controls how `/api/display` behaves for unknown devices or known devices "
            "with an invalid token. The factory-reset mode is consumed once and then "
            "automatically resets to the default error behavior."
        ),
    )
