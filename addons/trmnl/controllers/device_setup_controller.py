"""HTTP endpoint for TRMNL device setup requests."""

from __future__ import annotations

import logging

from odoo import http
from odoo.http import request

from .trmnl_api_base import TrmnlApiControllerMixin

_logger = logging.getLogger(__name__)


class DeviceSetupController(TrmnlApiControllerMixin, http.Controller):
    """Serve the `/api/setup` endpoint used by TRMNL devices."""

    @http.route(
        "/api/setup",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        sitemap=False,
    )
    def api_setup(self, **kwargs):
        """Create a device registration and return the setup payload."""
        device_model = request.env["trmnl.device"].sudo()
        headers = request.httprequest.headers
        masked_mac_address = self._mask_identifier(headers.get("ID"))

        _logger.info(
            "TRMNL request endpoint=/api/setup method=%s mac=%s",
            request.httprequest.method,
            masked_mac_address,
        )

        try:
            device, raw_token, record_status = device_model.upsert_from_setup_headers(headers)
            payload = device.build_setup_response(api_token=raw_token)

            _logger.info(
                "TRMNL record status endpoint=/api/setup mac=%s status=%s",
                masked_mac_address,
                record_status,
            )
            return self._json_response(payload, status=200)
        except Exception as exc:  # keep protocol responses stable
            _logger.warning(
                "TRMNL /api/setup failed for mac=%s: %s",
                masked_mac_address,
                exc,
            )
            return self._json_response(device_model.build_setup_error_response(), status=200)
