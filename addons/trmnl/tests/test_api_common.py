"""Shared utilities for TRMNL API HTTP response tests."""

import json

from odoo.addons.trmnl.models.trmnl_device import (
    APPROVAL_STATE_ACCEPTED,
    APPROVAL_STATE_TOKEN_MISMATCH,
    APPROVAL_STATE_UNKNOWN_DEVICE,
    DEFAULT_FILENAME,
    DEFAULT_REFRESH_RATE,
    DISPLAY_POLICY_AUTO_ACCEPT,
    DISPLAY_POLICY_ERROR,
    DISPLAY_POLICY_FACTORY_RESET,
    TRMNL_POLICY_PARAM,
    UNAUTHORIZED_IMAGE_FILENAME,
)

# Backward-compatible aliases for tests that import these names from here.
DISPLAY_POLICY_PARAMETER = TRMNL_POLICY_PARAM


class TrmnlApiHttpCaseMixin:
    """Shared helpers for TRMNL API response tests."""

    DEVICE_MAC_ADDRESS = "AA:BB:CC:DD:EE:FF"
    DEVICE_FIRMWARE_VERSION = "1.5.2"
    DEVICE_REFRESH_RATE = 60    # 1 minute — matches DEFAULT_REFRESH_RATE
    DEVICE_BATTERY_VOLTAGE = "4.1"
    DEVICE_RSSI = "-69"
    DEVICE_WIDTH = "800"
    DEVICE_HEIGHT = "480"
    UNKNOWN_MAC_ADDRESS = "11:22:33:44:55:66"
    UNKNOWN_DEVICE_TOKEN = "unknown-device-token"
    BAD_TOKEN = "bad-token"
    EMPTY_TOKEN = ""
    EXPECTED_FILENAME = DEFAULT_FILENAME

    def _response_status(self, http_response):
        """Return the HTTP status code for a ``url_open`` response."""
        for attribute_name in ("status_code", "status", "code"):
            status_value = getattr(http_response, attribute_name, None)
            if status_value is not None:
                return status_value

        if hasattr(http_response, "getcode"):
            return http_response.getcode()

        raise AttributeError("Unable to determine the HTTP status code.")

    def _response_text(self, http_response):
        """Return the HTTP response body as text."""
        response_body = getattr(http_response, "content", None)
        if response_body is None and hasattr(http_response, "read"):
            response_body = http_response.read()
        if response_body is None and hasattr(http_response, "text"):
            response_body = http_response.text

        if isinstance(response_body, bytes):
            return response_body.decode("utf-8")

        return response_body or ""

    def _response_json(self, http_response):
        """Return the response body decoded as JSON."""
        return json.loads(self._response_text(http_response))

    def _setup_headers(self, mac_address=None, firmware_version=None):
        """Return headers for a TRMNL setup request."""
        return {
            "ID": mac_address or self.DEVICE_MAC_ADDRESS,
            "FW-Version": firmware_version or self.DEVICE_FIRMWARE_VERSION,
        }

    def _display_headers(self, api_token, mac_address=None):
        """Return headers for a TRMNL display request."""
        return {
            "ID": mac_address or self.DEVICE_MAC_ADDRESS,
            "Access-Token": api_token,
            "Refresh-Rate": str(self.DEVICE_REFRESH_RATE),
            "Battery-Voltage": self.DEVICE_BATTERY_VOLTAGE,
            "FW-Version": self.DEVICE_FIRMWARE_VERSION,
            "RSSI": self.DEVICE_RSSI,
            "Width": self.DEVICE_WIDTH,
            "Height": self.DEVICE_HEIGHT,
        }

    def _display_headers_with_rate(self, token, mac, refresh_rate):
        """Return display request headers with the device-reported refresh rate."""
        headers = self._display_headers(token, mac)
        headers["Refresh-Rate"] = str(refresh_rate)
        return headers

    def _log_headers(self, api_token, mac_address=None):
        """Return headers for a TRMNL log request."""
        return {
            "ID": mac_address or self.DEVICE_MAC_ADDRESS,
            "Access-Token": api_token,
            "Accept": "application/json, */*",
            "Content-Type": "application/json",
        }

    def _log_entry(
        self,
        *,
        log_id=1,
        created_at=1745000000,
        message="Test log message",
        source_line=123,
        source_path="src/bl.cpp",
        wifi_signal=-67,
        wifi_status="Connected",
        refresh_rate=None,
        sleep_duration=145,
        firmware_version=None,
        special_function="None",
        battery_voltage=3.95,
        wake_reason="Timer",
        free_heap_size=48320,
        max_alloc_size=38912,
        retry=None,
    ):
        """Return one TRMNL log entry using the current device contract."""
        log_entry = {
            "created_at": created_at,
            "id": log_id,
            "message": message,
            "source_line": source_line,
            "source_path": source_path,
            "wifi_signal": wifi_signal,
            "wifi_status": wifi_status,
            "refresh_rate": refresh_rate if refresh_rate is not None else self.DEVICE_REFRESH_RATE,
            "sleep_duration": sleep_duration,
            "firmware_version": firmware_version if firmware_version is not None else self.DEVICE_FIRMWARE_VERSION,
            "special_function": special_function,
            "battery_voltage": battery_voltage,
            "wake_reason": wake_reason,
            "free_heap_size": free_heap_size,
            "max_alloc_size": max_alloc_size,
        }

        if retry is not None:
            log_entry["retry"] = retry

        return log_entry

    def _log_payload(self, log_entries=None):
        """Return a realistic TRMNL log payload."""
        if log_entries is None:
            log_entries = [self._log_entry()]

        return {"logs": list(log_entries)}

    def _empty_log_payload(self):
        """Return a payload that contains no log entries."""
        return {"logs": []}

    def _call_json_endpoint(self, path, headers=None, payload=None):
        """Call an HTTP endpoint and return the raw response object."""
        request_headers = dict(headers or {})
        request_payload = None

        if payload is not None:
            request_payload = json.dumps(payload).encode("utf-8")

        return self.url_open(path, data=request_payload, headers=request_headers)

    def _set_display_policy(self, policy):
        """Persist the default display policy for unresolved devices."""
        self.env["ir.config_parameter"].sudo().set_param(
            DISPLAY_POLICY_PARAMETER,
            policy,
        )

    def _get_display_policy(self):
        """Return the current default display policy."""
        return self.env["ir.config_parameter"].sudo().get_param(
            DISPLAY_POLICY_PARAMETER,
            DISPLAY_POLICY_ERROR,
        )

    def _get_unauthorized_image_url(self):
        """Return the absolute unauthorized image URL as the server would produce it."""
        from odoo.addons.trmnl.models.trmnl_image import UNAUTHORIZED_IMAGE_CONFIG_KEY
        return self.env["trmnl.image.seeder"].get_image_url(UNAUTHORIZED_IMAGE_CONFIG_KEY)

    def _register_device_through_setup(self, mac_address=None):
        """Register a device through the real ``/api/setup`` endpoint."""
        setup_mac_address = mac_address or self.DEVICE_MAC_ADDRESS
        setup_response = self.url_open(
            "/api/setup",
            headers=self._setup_headers(setup_mac_address),
        )
        setup_payload = self._response_json(setup_response)

        self.assertEqual(self._response_status(setup_response), 200)

        expected_keys = {"status", "api_key", "image_url"}
        self.assertEqual(set(setup_payload.keys()), expected_keys)
        self.assertEqual(setup_payload["status"], 200)
        self.assertTrue(setup_payload["api_key"])

        registered_device = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", setup_mac_address)],
            limit=1,
        )

        self.assertTrue(registered_device, "The setup request should register the device.")
        self.assertEqual(registered_device.approval_state, APPROVAL_STATE_ACCEPTED)
        self.assertEqual(registered_device.image_url, setup_payload["image_url"])

        verify_token_method = getattr(registered_device, "_verify_api_token", None)

        if callable(verify_token_method):
            self.assertTrue(
                verify_token_method(setup_payload["api_key"]),
                "The returned API key should match the stored hash.",
            )

        return {
            "device": registered_device,
            "api_token": setup_payload["api_key"],
            "payload": setup_payload,
        }

    def _display_unknown_headers(self, api_token, mac_address=None):
        """Return headers for an unknown device display request."""
        return self._display_headers(api_token, mac_address or self.UNKNOWN_MAC_ADDRESS)

    def _assert_display_success_payload(self, display_payload, image_url):
        """Assert the standard successful ``/api/display`` payload.

        ``refresh_rate`` in the response reflects the server-configured
        ``desired_refresh_rate``, which defaults to ``DEFAULT_REFRESH_RATE``
        (60 s = 1 min) for freshly registered devices.
        """
        expected_keys = {
            "status",
            "image_url",
            "filename",
            "refresh_rate",
        }
        self.assertEqual(set(display_payload.keys()), expected_keys)
        self.assertEqual(
            display_payload,
            {
                "status": 0,
                "image_url": image_url,
                "filename": self.EXPECTED_FILENAME,
                "refresh_rate": self.DEVICE_REFRESH_RATE,
            },
        )

    def _assert_display_unauthorized_payload(self, display_payload):
        """Assert the unauthorized-image ``/api/display`` payload.

        Returned to unknown devices and token-mismatched devices under the
        error policy so the device always has something to render.  The
        payload has the same shape as a normal display response but carries
        the seeded unauthorized image URL (absolute, built from web.base.url) and
        the unauthorized image filename.
        """
        unauthorized_image_url = self._get_unauthorized_image_url()
        self.assertEqual(
            display_payload,
            {
                "status": 0,
                "filename": UNAUTHORIZED_IMAGE_FILENAME,
                "image_url": unauthorized_image_url,
                "refresh_rate": DEFAULT_REFRESH_RATE,
            },
        )
