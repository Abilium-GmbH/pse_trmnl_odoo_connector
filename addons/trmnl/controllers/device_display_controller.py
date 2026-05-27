"""HTTP endpoint for TRMNL display polling requests."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

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

        if device_model._is_trmnl_api_debug_enabled():
            _logger.info(
                "TRMNL API DEBUG request path=%s method=%s host=%r secure=%s "
                "fw=%r token_header=%s id_header_masked=%s",
                request.httprequest.path,
                request.httprequest.method,
                headers.get("Host"),
                request.httprequest.is_secure,
                headers.get("FW-Version"),
                bool(headers.get("Access-Token")),
                masked_mac_address,
            )

        _logger.info(
            "TRMNL request endpoint=/api/display method=%s mac=%s",
            request.httprequest.method,
            masked_mac_address,
        )

        try:
            host_header = headers.get("Host", "")
            poll_base_url = ""
            client_ip = (request.httprequest.remote_addr or "").strip()
            if host_header:
                scheme = "https" if request.httprequest.is_secure else "http"
                poll_base_url = f"{scheme}://{host_header}"
                device_model._maybe_auto_set_public_base_url(poll_base_url, client_ip)
                device_model._sync_public_base_url_from_poll(poll_base_url, client_ip)

            device_model = device_model.with_context(
                trmnl_poll_base_url=poll_base_url,
                trmnl_client_ip=client_ip,
            )

            device, payload, record_status = device_model.resolve_display_request(headers)

            if device_model._is_trmnl_api_debug_enabled():
                _logger.info(
                    "TRMNL API DEBUG response /api/display record_status=%r payload_keys=%s status_field=%r",
                    record_status,
                    sorted(payload.keys()),
                    payload.get("status"),
                )

            _logger.info(
                "TRMNL record status endpoint=/api/display mac=%s status=%s",
                masked_mac_address,
                record_status,
            )
            if isinstance(payload, dict) and payload.get("status") == 0:
                img_url = payload.get("image_url") or ""
                host = urlparse(img_url).hostname or ""
                _logger.info(
                    "TRMNL display JSON: mac=%s refresh_rate=%s filename=%r "
                    "image_host=%s special_function=%s",
                    masked_mac_address,
                    payload.get("refresh_rate"),
                    payload.get("filename"),
                    host,
                    payload.get("special_function"),
                )
            _logger.debug(
                "TRMNL response endpoint=/api/display mac=%s payload=%s",
                masked_mac_address,
                {k: (v[:60] + "…" if isinstance(v, str) and len(v) > 60 else v) for k, v in payload.items()},
            )
            return self._json_response(payload, status=200)
        except Exception as exc:  # keep protocol responses stable
            _logger.warning(
                "TRMNL /api/display failed for mac=%s: %s",
                masked_mac_address,
                exc,
            )
            return self._json_response(device_model.build_display_error_response(), status=200)
