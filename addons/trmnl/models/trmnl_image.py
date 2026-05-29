"""TRMNL image attachment seeding and URL resolution."""

from __future__ import annotations

import base64
import logging
import os

from odoo import api, models

_logger = logging.getLogger(__name__)

# ir.config_parameter keys used to store the attachment IDs of the two
# seed images.  These are the single source of truth for URL resolution at
# runtime; the static files under static/ are only read during
# (re-)installation.
DEFAULT_IMAGE_CONFIG_KEY = "trmnl.default_image_attachment_id"
UNAUTHORIZED_IMAGE_CONFIG_KEY = "trmnl.unauthorized_image_attachment_id"

# Absolute paths to the source image files bundled with the module.
# Constructed at import time so they are independent of the working directory.
_MODULE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_IMAGE_PATH = os.path.join(_MODULE_DIR, "static", "default_screen.bmp")
_UNAUTHORIZED_IMAGE_PATH = os.path.join(_MODULE_DIR, "static", "unauthorized_screen.bmp")

_SEED_IMAGES = [
    {
        "config_key": DEFAULT_IMAGE_CONFIG_KEY,
        "name": "trmnl_default_screen.bmp",
        "mimetype": "image/bmp",
        "path": _DEFAULT_IMAGE_PATH,
    },
    {
        "config_key": UNAUTHORIZED_IMAGE_CONFIG_KEY,
        "name": "trmnl_unauthorized_screen.bmp",
        "mimetype": "image/bmp",
        "path": _UNAUTHORIZED_IMAGE_PATH,
    },
]


class TrmnlImageSeeder(models.AbstractModel):
    """Seed and resolve TRMNL display images as public ``ir.attachment`` records.

    On module installation (or forced upgrade) the two built-in images are
    uploaded as public attachments so that any HTTP client — including a TRMNL
    device on a different network segment — can fetch them via an absolute URL
    derived from ``web.base.url``.  The attachment IDs are persisted in
    ``ir.config_parameter`` so that URL construction never relies on
    hard-coded static paths.

    Serving images through ``/web/image/{id}`` works identically on a local
    Docker installation and on odoo.sh: the ``web.base.url`` system parameter
    provides the correct base in both environments.  On a local Docker setup
    ``web.base.url`` must be set to the externally reachable address of the
    container (e.g. ``http://192.168.x.x:8069``) so that TRMNL devices on
    the same network can reach it; on odoo.sh it is set automatically to the
    public domain.
    """

    _name = "trmnl.image.seeder"
    _description = "TRMNL Image Seeder"

    @api.model
    def seed_images(self):
        """Create or replace the two built-in TRMNL images as public attachments.

        For each image the existing attachment (if any) is deleted and a fresh
        one is created, so that module upgrades always reflect the latest
        source file on disk.  The resulting attachment ID is stored in
        ``ir.config_parameter`` for later URL resolution.
        """
        attachment_model = self.env["ir.attachment"].sudo()
        config_model = self.env["ir.config_parameter"].sudo()

        for image_spec in _SEED_IMAGES:
            if not os.path.isfile(image_spec["path"]):
                _logger.warning(
                    "TRMNL image seed file not found, skipping: %s", image_spec["path"]
                )
                continue

            # Remove any previously seeded attachment so upgrades stay in sync.
            existing_id = config_model.get_param(image_spec["config_key"])
            if existing_id:
                existing_attachment = attachment_model.browse(int(existing_id))
                if existing_attachment.exists():
                    existing_attachment.unlink()

            with open(image_spec["path"], "rb") as image_file:
                image_data = base64.b64encode(image_file.read()).decode("ascii")

            new_attachment = attachment_model.create({
                "name": image_spec["name"],
                "type": "binary",
                "datas": image_data,
                "mimetype": image_spec["mimetype"],
                "public": True,
            })

            config_model.set_param(image_spec["config_key"], str(new_attachment.id))
            _logger.info(
                "TRMNL seeded image '%s' as attachment id=%s",
                image_spec["name"],
                new_attachment.id,
            )

    @api.model
    def remove_images(self):
        """Delete the seeded attachments and all trmnl.* config parameter entries.

        Called from the module ``uninstall_hook`` to leave the database in a
        clean state after removal. Deletes both seeded ir.attachment records
        and all ir.config_parameter keys under the trmnl.* namespace, including
        the display policy key written by _set_display_request_policy.
        """
        attachment_model = self.env["ir.attachment"].sudo()
        config_model = self.env["ir.config_parameter"].sudo()

        for image_spec in _SEED_IMAGES:
            existing_id = config_model.get_param(image_spec["config_key"])
            if existing_id:
                existing_attachment = attachment_model.browse(int(existing_id))
                if existing_attachment.exists():
                    existing_attachment.unlink()

        config_model.search([("key", "like", "trmnl.%")]).unlink()

    @api.model
    def get_image_url(self, config_key):
        """Return the absolute URL for a seeded image identified by ``config_key``.

        Combines ``web.base.url`` with the ``/web/image/{id}`` route so the
        URL is reachable by the TRMNL device regardless of the deployment
        environment.  Returns ``False`` when the attachment has not been seeded
        yet (e.g. during the very first install before ``post_init_hook`` runs)
        or when ``web.base.url`` has not been configured.
        """
        config_model = self.env["ir.config_parameter"].sudo()

        attachment_id = config_model.get_param(config_key)
        if not attachment_id:
            return False

        base_url = config_model.get_param("web.base.url", "").rstrip("/")
        if not base_url:
            return False

        return f"{base_url}/web/image/{attachment_id}"
