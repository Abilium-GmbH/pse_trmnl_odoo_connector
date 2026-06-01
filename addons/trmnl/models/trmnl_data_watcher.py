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

A Python ``except`` block alone is not sufficient: once psycopg2 raises a
database error, PostgreSQL marks the entire transaction as aborted and refuses
all further SQL until an explicit ``ROLLBACK`` (or rollback to a savepoint).
The fix wraps the risky query in a **savepoint** so that a database error can
be caught and the savepoint rolled back, leaving the outer transaction intact
and allowing the uninstall to continue.

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
- The savepoint overhead is negligible: a single ``SAVEPOINT`` / ``RELEASE``
  pair is issued only when the model is not already in the pending set.
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

        Wraps the database search in a cursor savepoint so that any PostgreSQL
        error (most commonly ``UndefinedColumn`` or ``UndefinedTable`` during
        module uninstall) is isolated: the savepoint is rolled back and the
        outer transaction remains usable, allowing the uninstall to proceed.

        A Python ``except`` block alone is insufficient because psycopg2
        transitions the connection into an aborted state on any DB error,
        blocking all subsequent SQL until a rollback.  The savepoint boundary
        provides the required rollback target without aborting the caller's
        transaction.

        In normal (non-uninstall) operation the schema is intact; the savepoint
        is released cleanly with negligible overhead.
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

        savepoint = f"trmnl_watcher_{self._name.replace('.', '_')}"
        try:
            cr.execute(f"SAVEPOINT {savepoint}")
            ir_model = self.env["ir.model"].sudo().search(
                [("model", "=", self._name)],
                limit=1,
            )
            if ir_model:
                profiles = self.env["trmnl.profile"].sudo().search([
                    ("active", "=", True),
                    ("app_model_id", "=", ir_model.id),
                ])
                if profiles:
                    profiles.write({"preview_data_stale": True})
            cr.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception:
            # Roll back to the savepoint so the outer transaction stays intact.
            # This is the critical difference from a plain try/except: psycopg2
            # marks the transaction as aborted on any DB error, and only a
            # ROLLBACK TO SAVEPOINT restores it to a usable state.
            try:
                cr.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            except Exception:
                pass
            _logger.debug(
                "TRMNL data watcher: skipping profile invalidation for model %r "
                "— schema unavailable (module uninstall in progress)",
                self._name,
            )
        finally:
            cr._trmnl_pending.discard(self._name)

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """Create records and mark any watching profiles as stale."""
        records = super().create(vals_list)
        records._trmnl_invalidate_profiles()
        return records

    def write(self, vals):
        """Write to records and mark any watching profiles as stale."""
        result = super().write(vals)
        self._trmnl_invalidate_profiles()
        return result

    def unlink(self):
        """Delete records and mark any watching profiles as stale before deletion."""
        self._trmnl_invalidate_profiles()
        return super().unlink()
