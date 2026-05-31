"""Tests for TRMNL image seeding and cleanup lifecycle."""

from odoo.tests import TransactionCase, tagged

from odoo.addons.trmnl.models.trmnl_image import (
    DEFAULT_IMAGE_CONFIG_KEY,
    UNAUTHORIZED_IMAGE_CONFIG_KEY,
)


@tagged("-at_install", "post_install")
class TestTrmnlImageSeederCleanup(TransactionCase):
    """Verify that remove_images() leaves the database in a clean state.

    These tests exercise the cleanup path directly rather than triggering
    a full module uninstall, which is not supported in Odoo's test runner.
    The contract under test is: after remove_images() is called, no seeded
    ir.attachment records and no trmnl.* ir.config_parameter rows remain.
    """

    def setUp(self):
        super().setUp()
        self.seeder = self.env["trmnl.image.seeder"]
        self.config = self.env["ir.config_parameter"].sudo()
        self.attachments = self.env["ir.attachment"].sudo()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _trmnl_config_keys(self):
        """Return all ir.config_parameter rows whose key starts with 'trmnl.'."""
        return self.config.search([("key", "like", "trmnl.%")])

    def _get_seeded_attachment_ids(self):
        """Return the stored attachment IDs for both seed images, as integers."""
        attachment_ids = []
        for config_key in (DEFAULT_IMAGE_CONFIG_KEY, UNAUTHORIZED_IMAGE_CONFIG_KEY):
            raw_value = self.config.get_param(config_key)
            if raw_value:
                attachment_ids.append(int(raw_value))
        return attachment_ids

    # ------------------------------------------------------------------
    # seed → remove round-trip
    # ------------------------------------------------------------------

    def test_remove_images_deletes_all_trmnl_config_parameters(self):
        """remove_images() must delete every ir.config_parameter row under trmnl.*."""
        self.seeder.seed_images()
        self.assertTrue(
            self._trmnl_config_keys(),
            "seed_images() must create at least one trmnl.* config parameter.",
        )

        self.seeder.remove_images()

        remaining_keys = self._trmnl_config_keys()
        self.assertFalse(
            remaining_keys,
            f"Expected no trmnl.* config parameters after remove_images(), "
            f"found: {remaining_keys.mapped('key')}",
        )

    def test_remove_images_deletes_seeded_attachments(self):
        """remove_images() must delete both seeded ir.attachment records."""
        self.seeder.seed_images()
        attachment_ids = self._get_seeded_attachment_ids()
        self.assertEqual(
            len(attachment_ids),
            2,
            "seed_images() must register exactly two attachment IDs in config.",
        )

        self.seeder.remove_images()

        surviving_attachments = self.attachments.browse(attachment_ids).exists()
        self.assertFalse(
            surviving_attachments,
            f"Expected seeded attachments to be deleted, "
            f"but found surviving ids: {surviving_attachments.ids}",
        )

    def test_remove_images_also_removes_display_policy_key(self):
        """remove_images() must remove the display policy config key if present."""
        self.config.set_param("trmnl.display_unknown_device_policy", "error")

        self.seeder.remove_images()

        remaining_value = self.config.get_param("trmnl.display_unknown_device_policy")
        self.assertFalse(
            remaining_value,
            "trmnl.display_unknown_device_policy must be removed by remove_images().",
        )

    # ------------------------------------------------------------------
    # idempotency
    # ------------------------------------------------------------------

    def test_remove_images_is_idempotent(self):
        """Calling remove_images() twice must not raise and must leave no trmnl.* keys."""
        self.seeder.seed_images()
        self.seeder.remove_images()

        try:
            self.seeder.remove_images()
        except Exception as exc:
            self.fail(f"Second call to remove_images() raised unexpectedly: {exc}")

        self.assertFalse(self._trmnl_config_keys())
