"""Public HTTP endpoint for serving TRMNL profile preview images."""
from __future__ import annotations

import base64
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class ProfileImageController(http.Controller):
    """Serve the stored preview PNG for a profile so TRMNL devices can download it."""

    @staticmethod
    def _access_token_from_request():
        """Read device API token from query string or Access-Token header."""
        token = request.params.get("access_token") or request.httprequest.headers.get(
            "Access-Token"
        )
        return (token or "").strip()

    @staticmethod
    def _user_may_preview_without_token():
        """Allow Odoo backend users (Settings) to load the form preview image."""
        user = request.env.user
        return bool(user and not user._is_public() and user.has_group("base.group_system"))

    def _authorize_profile_image(self, profile, access_token):
        """Return True when the caller may download this profile's PNG."""
        if self._user_may_preview_without_token():
            return True
        if not access_token or not profile.device_id:
            return False
        return bool(profile.device_id._verify_api_token(access_token))

    @http.route(
        "/api/profile/image/<int:profile_id>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        sitemap=False,
    )
    def profile_image(self, profile_id, **kwargs):
        """Return the profile preview PNG or 404 if not found / not authorized."""
        access_token = self._access_token_from_request()
        try:
            profile = request.env["trmnl.profile"].sudo().browse(profile_id)

            if not profile.exists():
                _logger.warning("TRMNL profile image 404: profile_id=%s not found", profile_id)
                return request.make_response("", status=404)

            if not self._authorize_profile_image(profile, access_token):
                _logger.warning(
                    "TRMNL profile image 403: profile_id=%s unauthorized (no valid token)",
                    profile_id,
                )
                return request.make_response("", status=404)

            if not profile.preview_image:
                _logger.warning(
                    "TRMNL profile image 404: profile_id=%s name=%r has no preview image",
                    profile_id,
                    profile.name,
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
                "TRMNL profile image serve failed profile_id=%s: %s",
                profile_id,
                exc,
                exc_info=True,
            )
            return request.make_response("", status=404)
