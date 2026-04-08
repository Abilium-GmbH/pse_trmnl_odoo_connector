import json
import logging

from odoo import _, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class DeviceController(http.Controller):
    @staticmethod
    def _mask_identifier(value):
        if value in (None, ""):
            return "missing"

        value = str(value).strip()
        if len(value) <= 8:
            return "***"
        return f"{value[:4]}…{value[-4:]}"

    @staticmethod
    def _json_response(payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return request.make_response(
            body,
            headers=[
                ("Content-Type", "application/json; charset=utf-8"),
                ("Cache-Control", "no-store, max-age=0"),
                ("Pragma", "no-cache"),
            ],
            status=status,
        )

    @http.route(
        "/api/setup",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        sitemap=False,
    )
    def api_setup(self, **kwargs):
        Device = request.env["trmnl.device"].sudo()
        headers = request.httprequest.headers
        masked_mac = self._mask_identifier(headers.get("ID"))

        _logger.info(
            "TRMNL request endpoint=/api/setup method=%s mac=%s",
            request.httprequest.method,
            masked_mac,
        )

        try:
            device, raw_token, record_status = Device.upsert_from_setup_headers(headers)
            payload = device.build_setup_response(api_token=raw_token)

            _logger.info(
                "TRMNL record status endpoint=/api/setup mac=%s status=%s",
                masked_mac,
                record_status,
            )
            return self._json_response(payload, status=200)
        except Exception as exc:
            _logger.warning(
                "TRMNL /api/setup failed for mac=%s: %s",
                masked_mac,
                exc,
            )
            return self._json_response(
                Device.build_setup_error_response(
                    _("TRMNL setup request could not be processed.")
                ),
                status=200,
            )

    @http.route(
        "/api/display",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
        sitemap=False,
    )
    def api_display(self, **kwargs):
        Device = request.env["trmnl.device"].sudo()
        headers = request.httprequest.headers
        masked_mac = self._mask_identifier(headers.get("ID"))

        _logger.info(
            "TRMNL request endpoint=/api/display method=%s mac=%s",
            request.httprequest.method,
            masked_mac,
        )

        try:
            device, payload, record_status = Device.resolve_display_request(headers)

            _logger.info(
                "TRMNL record status endpoint=/api/display mac=%s status=%s",
                masked_mac,
                record_status,
            )
            return self._json_response(payload, status=200)
        except Exception as exc:
            _logger.warning(
                "TRMNL /api/display failed for mac=%s: %s",
                masked_mac,
                exc,
            )
            return self._json_response(
                Device.build_display_error_response(status=404),
                status=200,
            )

    @http.route(
        "/api/log",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        sitemap=False,
    )
    def api_log(self, **kwargs):
        Device = request.env["trmnl.device"].sudo()
        headers = request.httprequest.headers
        masked_mac = self._mask_identifier(headers.get("ID"))

        _logger.info(
            "TRMNL request endpoint=/api/log method=%s mac=%s",
            request.httprequest.method,
            masked_mac,
        )

        try:
            payload = request.httprequest.get_json(silent=True) or {}
            device, created_count, record_status = Device.ingest_logs_from_payload(
                headers,
                payload,
            )

            _logger.info(
                "TRMNL record status endpoint=/api/log mac=%s status=%s created=%s",
                masked_mac,
                record_status,
                created_count,
            )
        except Exception as exc:
            _logger.warning(
                "TRMNL /api/log failed for mac=%s: %s",
                masked_mac,
                exc,
            )

        return request.make_response("", status=204)
