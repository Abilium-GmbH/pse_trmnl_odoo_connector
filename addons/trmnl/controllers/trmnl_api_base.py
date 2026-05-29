"""Shared controller helpers for the TRMNL API."""

from __future__ import annotations

import json
import logging

from odoo.exceptions import UserError, ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)


class TrmnlApiControllerMixin:
    """Provide response helpers shared by the TRMNL controller classes."""

    @staticmethod
    def _mask_identifier(value):
        """Return a partially masked identifier for log output."""
        if value in (None, ""):
            return "missing"

        value_text = str(value).strip()
        if len(value_text) <= 8:
            return "***"

        return f"{value_text[:4]}…{value_text[-4:]}"

    @staticmethod
    def _json_response(payload, status=200):
        """Serialize a payload and return a JSON HTTP response."""
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

    @staticmethod
    def _handle_api_exception(endpoint, masked_mac, exc, error_response):
        """Log API failures; map validation errors to protocol errors.

        Programming errors are always logged with a traceback.  When
        ``trmnl.api_debug`` is enabled, unexpected exceptions are re-raised
        so developers see the root cause immediately.
        """
        if isinstance(exc, (ValidationError, UserError)):
            _logger.info(
                "TRMNL %s rejected mac=%s: %s",
                endpoint,
                masked_mac,
                exc,
            )
            return error_response

        _logger.error(
            "TRMNL %s failed for mac=%s: %s",
            endpoint,
            masked_mac,
            exc,
            exc_info=True,
        )
        device_model = request.env["trmnl.device"].sudo()
        if device_model._is_trmnl_api_debug_enabled():
            raise
        return error_response
