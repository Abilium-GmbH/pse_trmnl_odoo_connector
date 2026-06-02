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

        if device_model._is_trmnl_api_debug_enabled():
            _logger.info(
                "TRMNL API DEBUG request path=%s method=%s host=%r secure=%s fw=%r id_header_masked=%s",
                request.httprequest.path,
                request.httprequest.method,
                headers.get("Host"),
                request.httprequest.is_secure,
                headers.get("FW-Version"),
                masked_mac_address,
            )

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
            if device_model._is_trmnl_api_debug_enabled():
                safe = {k: ("***" if k == "api_key" else v) for k, v in payload.items()}
                _logger.info("TRMNL API DEBUG /api/setup payload=%s", safe)
            return self._json_response(payload, status=200)
        except Exception as exc:
            debug = device_model._is_trmnl_api_debug_enabled()
            return self._handle_api_exception(
                "/api/setup",
                masked_mac_address,
                exc,
                self._json_response(device_model.build_setup_error_response(), status=200),
                debug=debug,
            )
