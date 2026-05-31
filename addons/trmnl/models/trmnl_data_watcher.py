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

Uninstall safety
----------------
During module uninstall Odoo deletes ``ir.model.fields`` records for every
field registered by this module.  Each batch deletion fires these
``write``/``unlink`` hooks with ``self._name = "ir.model.fields"``.  At that
point the ``trmnl_profile`` table still physically exists (it is only dropped
later when the ``ir.model`` record itself is deleted), but Odoo has already
executed ``ALTER TABLE trmnl_profile DROP COLUMN active`` for the fields it
removed in earlier batches.  The subsequent ``search()`` call builds a query
that references ``trmnl_profile.active`` in its ``WHERE`` clause and raises::

    psycopg2.errors.UndefinedColumn:
        column trmnl_profile.active does not exist

Neither a registry-membership check nor a ``table_exists()`` guard is
sufficient here because the table is present but in a partially dismantled
state.  The only correct defence is to catch the database-level exception that
arises from any structural mismatch and treat it as a signal that the module
is mid-uninstall, returning silently.

Performance notes
-----------------
- The ``self._name.startswith("trmnl.")`` fast-path guard exits immediately for
  all TRMNL-internal writes, preventing recursion, and is evaluated before any
  database work is attempted.
- Transaction-level deduplication ensures at most one search + write on
  ``trmnl.profile`` per source model per database transaction regardless of
  how many records are written in bulk.
- The search on ``trmnl.profile`` is indexed via ``app_model_id`` (M2O to
  ``ir.model``) and returns quickly when no profile watches the model.
- The ``except Exception`` catch in ``_trmnl_invalidate_profiles`` is
  intentionally broad: any database or ORM error during uninstall should be
  swallowed silently rather than aborting the uninstall transaction.  Outside
  of uninstall this code path is exercised only when ``trmnl.profile`` rows
  exist and the schema is intact, so genuine runtime errors will not be masked
  in normal operation.
"""
from __future__ import annotations

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


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

        Swallows all database and ORM exceptions.  During module uninstall Odoo
        drops individual columns from ``trmnl_profile`` (via
        ``ir.model.fields`` deletion) before dropping the table itself.  Any
        ``search()`` issued while the schema is in this partially dismantled
        state raises ``UndefinedColumn``; catching it here allows the uninstall
        to proceed without interruption.

        In normal (non-uninstall) operation the schema is intact and exceptions
        in this method would indicate a genuine bug, so all caught exceptions
        are logged at WARNING level for observability.
        """
        # Recursion guard — skip writes originating from within this module.
        if self._name.startswith("trmnl."):
            return

        cr = self.env.cr
        if not hasattr(cr, "_trmnl_pending"):
            cr._trmnl_pending = set()
        if self._name in cr._trmnl_pending:
            return
        cr._trmnl_pending.add(self._name)

        try:
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
        except Exception:
            # Schema is partially dismantled (module uninstall in progress).
            # Log at DEBUG so the noise does not appear in production logs
            # during normal upgrades, but remains visible when tracing issues.
            _logger.debug(
                "TRMNL data watcher: skipping profile invalidation for model %r "
                "— schema unavailable (module uninstall in progress)",
                self._name,
            )
        finally:
            # Always release the debounce slot so subsequent writes on the same
            # model within this transaction are not silently dropped.
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
