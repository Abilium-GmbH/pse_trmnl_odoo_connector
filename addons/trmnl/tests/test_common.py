"""Shared helpers for TRMNL profile and renderer tests."""

from __future__ import annotations


def make_trmnl_device(env, mac_address, **extra):
    """Create an accepted TRMNL device for tests."""
    values = {
        "mac_address": mac_address,
        "approval_state": "accepted",
        "registration_source": "setup",
    }
    values.update(extra)
    return env["trmnl.device"].sudo().create(values)


def partner_ir_model(env):
    """Return the ``ir.model`` record for ``res.partner``."""
    return env["ir.model"].sudo().search([("model", "=", "res.partner")], limit=1)


def ir_model_field(env, model_name, field_name):
    """Return an ``ir.model.fields`` record by model and field name."""
    return env["ir.model.fields"].sudo().search(
        [("model", "=", model_name), ("name", "=", field_name)],
        limit=1,
    )


def model_has_graph_view(env):
    """Return whether *model_name* has a graph view in this database."""
    return bool(
        env["ir.ui.view"].sudo().search_count(
            [("model", "=", "res.partner"), ("type", "=", "graph")]
        )
    )
