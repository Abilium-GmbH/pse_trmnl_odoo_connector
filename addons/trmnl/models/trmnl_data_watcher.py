"""TRMNL data-change watcher — marks profile previews stale on source data changes.

Extends the **abstract** root ``base`` with lightweight ``create``, ``write``,
and ``unlink`` hooks (via ``models.AbstractModel`` — required in Odoo 19).
When a record belonging to a model that is configured as the data source
(``app_model_id``) of one or more active ``trmnl.profile`` records is changed,
those profiles are marked ``preview_data_stale = True``.

Stale → poll render flow
------------------------
1. User edits a ``calendar.event`` / ``sale.order`` / ``project.task`` etc.
2. This module's ``write`` / ``create`` / ``unlink`` hook fires.
3. Matching active profiles get ``preview_data_stale = True`` (one DB write
   per unique source model per transaction — debounced via a cursor-level set).
4. On the next device poll, ``_should_render_for_device`` sees the stale flag
   and returns ``True``, triggering ``_render_and_store_preview``.
5. After a successful render, ``preview_data_stale`` is reset to ``False``.

Performance notes
-----------------
- The fast-path guard (``self._name.startswith("trmnl.")``) exits immediately
  for all TRMNL-internal writes, preventing recursion.
- Transaction-level deduplication ensures at most one search + write on
  ``trmnl.profile`` per source model per database transaction regardless of
  how many records are written in bulk.
- The search on ``trmnl.profile`` is indexed via ``app_model_id`` (M2O to
  ``ir.model``) and returns quickly when no profile watches the model.
"""
from __future__ import annotations

from odoo import api, models


class TrmnlDataWatcher(models.AbstractModel):
    """Mixin on the abstract root ``base`` — hooks every concrete model without a table.

    ``models.Model`` + ``_inherit = 'base'`` is invalid: Odoo rejects turning the
    abstract ``base`` model into a non-abstract model (registry load TypeError).
    """

    _inherit = "base"

    # ------------------------------------------------------------------
    # public hook — called after create/write/unlink
    # ------------------------------------------------------------------

    def _trmnl_invalidate_profiles(self) -> None:
        """Mark active profiles whose source model is ``self._name`` as stale.

        Debounced: at most one search + write per source model name per
        database transaction (tracked via ``env.cr._trmnl_pending``).
        """
        if self._name.startswith("trmnl."):
            return

        cr = self.env.cr
        if not hasattr(cr, "_trmnl_pending"):
            cr._trmnl_pending = set()
        if self._name in cr._trmnl_pending:
            return
        cr._trmnl_pending.add(self._name)

        ir_model = self.env["ir.model"].sudo().search(
            [("model", "=", self._name)],
            limit=1,
        )
        if not ir_model:
            return

        profiles = self.env["trmnl.profile"].sudo().search([
            ("active", "=", True),
            ("app_model_id", "=", ir_model.id),
        ])
        if profiles:
            profiles.write({"preview_data_stale": True})

        # Allow further create/write/unlink on the same model in this transaction
        # (e.g. create a partner, clear stale, then update that partner).
        cr._trmnl_pending.discard(self._name)

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._trmnl_invalidate_profiles()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._trmnl_invalidate_profiles()
        return result

    def unlink(self):
        self._trmnl_invalidate_profiles()
        return super().unlink()
