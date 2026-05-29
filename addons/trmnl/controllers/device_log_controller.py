"""HTTP endpoint for TRMNL device log ingestion requests."""

from __future__ import annotations

import logging

from odoo import http
from odoo.http import request

from .trmnl_api_base import TrmnlApiControllerMixin

_logger = logging.getLogger(__name__)


class DeviceLogController(TrmnlApiControllerMixin, http.Controller):
    """Serve the `/api/log` endpoint used by TRMNL devices."""

    @http.route(
        "/api/log",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        sitemap=False,
    )
    def api_log(self, **kwargs):
        """Persist the raw log payload sent by a device."""
        device_model = request.env["trmnl.device"].sudo()
        headers = request.httprequest.headers
        masked_mac_address = self._mask_identifier(headers.get("ID"))

        if device_model._is_trmnl_api_debug_enabled():
            _logger.info(
                "TRMNL API DEBUG request path=%s method=%s host=%r secure=%s id_header_masked=%s",
                request.httprequest.path,
                request.httprequest.method,
                headers.get("Host"),
                request.httprequest.is_secure,
                masked_mac_address,
            )

        _logger.info(
            "TRMNL request endpoint=/api/log method=%s mac=%s",
            request.httprequest.method,
            masked_mac_address,
        )

        try:
            payload = request.httprequest.get_json(silent=True) or {}
            created_count, record_status = device_model.ingest_logs_from_payload(
                headers,
                payload,
            )

            _logger.info(
                "TRMNL record status endpoint=/api/log mac=%s status=%s created=%s",
                masked_mac_address,
                record_status,
                created_count,
            )
            if record_status in {"missing_identity", "unauthorized"}:
                return request.make_response("", status=401)
            return request.make_response("", status=204)
        except Exception as exc:
            response = self._handle_api_exception(
                "/api/log",
                masked_mac_address,
                exc,
                request.make_response("", status=401),
            )
            return response
