"""Public HTTP endpoint for serving TRMNL profile preview images."""
from __future__ import annotations

import base64
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class ProfileImageController(http.Controller):
    """Serve the stored preview PNG for a profile so TRMNL devices can download it."""

    @http.route(
        "/api/profile/image/<int:profile_id>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        sitemap=False,
    )
    def profile_image(self, profile_id, **kwargs):
        """Return the profile preview PNG or 404 if not found / not rendered."""
        try:
            profile = request.env["trmnl.profile"].sudo().browse(profile_id)

            if not profile.exists():
                _logger.warning("TRMNL profile image 404: profile_id=%s not found", profile_id)
                return request.make_response("", status=404)

            if not profile.preview_image:
                _logger.warning(
                    "TRMNL profile image 404: profile_id=%s name=%r has no preview image",
                    profile_id, profile.name,
                )
                return request.make_response("", status=404)

            png_bytes = base64.b64decode(profile.preview_image)
            digest = profile._preview_png_digest()
            _logger.info(
                "TRMNL profile image GET profile_id=%s bytes=%s digest=%s cache=no-store",
                profile_id,
                len(png_bytes),
                digest,
            )
            headers = [
                ("Content-Type", "image/png"),
                ("Content-Length", str(len(png_bytes))),
                ("Cache-Control", "no-store, max-age=0"),
            ]
            if digest:
                headers.append(("ETag", f'"{digest}"'))
            return request.make_response(png_bytes, headers=headers)
        except Exception as exc:
            _logger.warning(
                "TRMNL profile image serve failed profile_id=%s: %s", profile_id, exc,
                exc_info=True,
            )
            return request.make_response("", status=404)
