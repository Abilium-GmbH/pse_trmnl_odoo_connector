"""HTTP endpoint for TRMNL display polling requests."""

from __future__ import annotations

import logging

from odoo import http
from odoo.http import request

from .trmnl_api_base import TrmnlApiControllerMixin

_logger = logging.getLogger(__name__)


class DeviceDisplayController(TrmnlApiControllerMixin, http.Controller):
    """Serve the `/api/display` endpoint used by TRMNL devices."""

    @http.route(
        "/api/display",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        sitemap=False,
    )
    def api_display(self, **kwargs):
        """Return the image payload that should be displayed on the device."""
        device_model = request.env["trmnl.device"].sudo()
        headers = request.httprequest.headers
        masked_mac_address = self._mask_identifier(headers.get("ID"))

        _logger.info(
            "TRMNL request endpoint=/api/display method=%s mac=%s",
            request.httprequest.method,
            masked_mac_address,
        )

        try:
            host_header = headers.get("Host", "")
            if host_header:
                scheme = "https" if request.httprequest.is_secure else "http"
                device_model._maybe_auto_set_public_base_url(f"{scheme}://{host_header}")

            device, payload, record_status = device_model.resolve_display_request(headers)

            _logger.info(
                "TRMNL record status endpoint=/api/display mac=%s status=%s",
                masked_mac_address,
                record_status,
            )
            return self._json_response(payload, status=200)
        except Exception as exc:  # keep protocol responses stable
            _logger.warning(
                "TRMNL /api/display failed for mac=%s: %s",
                masked_mac_address,
                exc,
            )
            return self._json_response(device_model.build_display_error_response(), status=200)
