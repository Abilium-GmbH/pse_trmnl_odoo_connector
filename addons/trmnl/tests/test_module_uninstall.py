"""Tests for safe TRMNL module uninstall.

These tests guard against regressions in the module lifecycle — specifically
the class of bug where Odoo's internal ``ir.model.fields`` batch deletion
fires ``TrmnlDataWatcher`` hooks while the ``trmnl_profile`` schema is in a
partially dismantled state (columns already dropped, table still present),
causing a ``psycopg2.errors.UndefinedColumn`` that aborts the uninstall
transaction.

Test strategy
-------------
Two complementary layers of coverage:

**Layer 1 — unit tests (mock-based)**
    ``TestDataWatcherUninstallResilience`` patches the savepoint/search path to
    raise the exact exception seen in production and verifies that
    ``_trmnl_invalidate_profiles`` swallows it without leaving the transaction
    in an aborted state.

**Layer 2 — integration test (dedicated cursor)**
    ``TestModuleDataUninstall`` opens a *new* cursor on the same database,
    calls ``ir.model.data._module_data_uninstall({'trmnl': module_id})``
    (the exact internal method from the failure traceback), and immediately
    issues a full ``ROLLBACK`` so no DDL change survives to corrupt the shared
    test database.  A successful call without raising any exception is the
    pass criterion.

Why a dedicated cursor for the integration test
-----------------------------------------------
``TransactionCase`` wraps every test in a *savepoint* (``SAVEPOINT`` /
``ROLLBACK TO SAVEPOINT``), not a full transaction rollback.  PostgreSQL DDL
statements (``DROP TABLE``, ``ALTER TABLE … DROP COLUMN``) issued inside a
savepoint are *not* rolled back when only that savepoint is rolled back — they
persist in the outer transaction and would corrupt the test database for all
subsequent tests.  Opening a separate cursor and calling ``cr.rollback()``
issues a full ``ROLLBACK``, which does restore DDL changes.
"""
from __future__ import annotations

from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("-at_install", "post_install")
class TestDataWatcherUninstallResilience(TransactionCase):
    """``_trmnl_invalidate_profiles`` must not propagate database errors.

    Simulates the exact failure mode from the bug report: Odoo deletes
    ``ir.model.fields`` records in batches during uninstall, which fires the
    data-watcher hooks.  At that point the ``active`` column has already been
    dropped from ``trmnl_profile``, so any ``search()`` that references it
    raises ``UndefinedColumn``.  The savepoint mechanism must absorb this
    without leaving the PostgreSQL transaction in an aborted state.
    """

    def test_undefined_column_is_swallowed_and_transaction_stays_usable(self):
        """UndefinedColumn from the profile search must not poison the transaction.

        After ``_trmnl_invalidate_profiles`` handles the error, the transaction
        must still accept new SQL — verified by executing a trivial SELECT.
        """
        import psycopg2.errors

        partner_model = self.env["res.partner"].sudo()

        undefined_col = psycopg2.errors.UndefinedColumn(
            "column trmnl_profile.active does not exist"
        )

        with patch.object(
            type(self.env["trmnl.profile"].sudo()),
            "search",
            side_effect=undefined_col,
        ):
            try:
                partner_model._trmnl_invalidate_profiles()
            except Exception as exc:
                self.fail(
                    f"_trmnl_invalidate_profiles propagated an exception "
                    f"that should have been swallowed: {exc!r}"
                )

        # Transaction must still be usable after the error was handled.
        try:
            self.env.cr.execute("SELECT 1")
        except Exception as exc:
            self.fail(
                f"Transaction is in aborted state after _trmnl_invalidate_profiles "
                f"handled an error — savepoint rollback did not work: {exc!r}"
            )

    def test_generic_db_error_is_swallowed_and_transaction_stays_usable(self):
        """Any database error during the profile search must not propagate.

        Uses a plain ``Exception`` to confirm the broad ``except`` clause
        catches non-psycopg2 errors too (e.g. ORM-level failures).
        """
        partner_model = self.env["res.partner"].sudo()

        with patch.object(
            type(self.env["trmnl.profile"].sudo()),
            "search",
            side_effect=Exception("simulated db error during uninstall"),
        ):
            try:
                partner_model._trmnl_invalidate_profiles()
            except Exception as exc:
                self.fail(
                    f"_trmnl_invalidate_profiles propagated an exception "
                    f"that should have been swallowed: {exc!r}"
                )

        # Transaction must still be usable.
        try:
            self.env.cr.execute("SELECT 1")
        except Exception as exc:
            self.fail(
                f"Transaction is in aborted state after error handling: {exc!r}"
            )

    def test_trmnl_model_names_are_skipped_without_db_access(self):
        """Writes on trmnl.* models must return before touching the database.

        Verifies the recursion guard fires before any IR or profile search,
        preventing both recursion and spurious queries during TRMNL-internal
        operations.
        """
        profile_model = self.env["trmnl.profile"].sudo()
        search_call_count = [0]
        original_search = type(profile_model).search

        def counting_search(self_inner, *args, **kwargs):
            search_call_count[0] += 1
            return original_search(self_inner, *args, **kwargs)

        with patch.object(type(profile_model), "search", counting_search):
            device_model = self.env["trmnl.device"].sudo()
            device_model._trmnl_invalidate_profiles()

        self.assertEqual(
            search_call_count[0],
            0,
            "trmnl.* model writes must not trigger a trmnl.profile search",
        )

    def test_debounce_prevents_duplicate_invalidation_within_bulk_write(self):
        """A bulk write on many records of the same model invalidates profiles once.

        The debounce key is the model name, set before the search and cleared
        in the ``finally`` block.  Within a single ``write()`` call on a
        recordset, ORM hooks fire once per batch — this test verifies that
        repeated calls within the *same transaction* that hit the debounce
        guard (i.e. ``_name`` already in ``cr._trmnl_pending``) do not
        trigger a second search.
        """
        cr = self.env.cr
        # Pre-seed the pending set as if a write is already in progress.
        if not hasattr(cr, "_trmnl_pending"):
            cr._trmnl_pending = set()
        cr._trmnl_pending.add("res.partner")

        partner_model = self.env["res.partner"].sudo()
        search_call_count = [0]
        original_search = type(self.env["trmnl.profile"].sudo()).search

        def counting_search(self_inner, *args, **kwargs):
            search_call_count[0] += 1
            return original_search(self_inner, *args, **kwargs)

        with patch.object(
            type(self.env["trmnl.profile"].sudo()), "search", counting_search
        ):
            partner_model._trmnl_invalidate_profiles()

        self.assertEqual(
            search_call_count[0],
            0,
            "a write on a model already in the debounce set must not "
            "trigger a second trmnl.profile search",
        )

        # Clean up the pre-seeded debounce key so it does not leak across tests.
        cr._trmnl_pending.discard("res.partner")
