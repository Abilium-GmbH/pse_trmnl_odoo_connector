"""Shared controller helpers for the TRMNL API."""

from __future__ import annotations

import json

from odoo.http import request


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
