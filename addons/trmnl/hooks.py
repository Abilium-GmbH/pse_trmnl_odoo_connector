"""Post-install hook for the TRMNL addon."""

from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Backfill app_model_id on profiles created before the model-first refactor.

    Profiles that were saved with only ``odoo_action_id`` (and no ``app_model_id``)
    are migrated automatically: we derive the model from ``odoo_action_id.res_model``
    and write it back.  The runtime fallback in ``_backfill_model_id()`` covers any
    records that exist on upgraded installations where this hook does not run.
    """
    Profile = env["trmnl.profile"].sudo()
    profiles = Profile.search([("app_model_id", "=", False)])
    if not profiles:
        return

    migrated = 0
    for profile in profiles:
        if not profile.odoo_action_id or not profile.odoo_action_id.res_model:
            continue
        model_name = profile.odoo_action_id.res_model
        ir_model = env["ir.model"].sudo().search(
            [("model", "=", model_name)], limit=1
        )
        if not ir_model:
            _logger.warning(
                "TRMNL post_init_hook: profile id=%s references res_model=%r "
                "but no ir.model record found — skipping.",
                profile.id, model_name,
            )
            continue
        profile.app_model_id = ir_model
        migrated += 1

    if migrated:
        _logger.info(
            "TRMNL post_init_hook: backfilled app_model_id for %d profile(s).",
            migrated,
        )
