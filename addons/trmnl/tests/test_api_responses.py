"""HTTP response tests for the TRMNL API endpoints."""

from __future__ import annotations

import datetime as dt
import json
from unittest.mock import patch

from odoo.tests.common import HttpCase, tagged


class TrmnlApiHttpCaseMixin:
    """Shared helpers for TRMNL API response tests."""

    DEVICE_MAC_ADDRESS = "AA:BB:CC:DD:EE:FF"
    DEVICE_FIRMWARE_VERSION = "1.5.2"
    DEVICE_REFRESH_RATE = 1800
    DEVICE_BATTERY_VOLTAGE = "4.1"
    DEVICE_RSSI = "-69"
    DEVICE_WIDTH = "800"
    DEVICE_HEIGHT = "480"
    DEVICE_IMAGE_URL = "https://example.invalid/trmnl-device.png"
    DEVICE_FRIENDLY_ID = "TRMNL1"

    def _response_status(self, http_response):
        """Return the HTTP status code for a `url_open` response."""
        for attribute_name in ("status_code", "status", "code"):
            status_value = getattr(http_response, attribute_name, None)
            if status_value is not None:
                return status_value
        if hasattr(http_response, "getcode"):
            return http_response.getcode()
        raise AssertionError("Unable to determine the HTTP status code.")

    def _response_text(self, http_response):
        """Return the response body as text."""
        if hasattr(http_response, "get_data"):
            return http_response.get_data(as_text=True)

        if hasattr(http_response, "read"):
            response_body = http_response.read()
            if isinstance(response_body, bytes):
                return response_body.decode("utf-8")
            return response_body or ""

        response_body = getattr(http_response, "content", b"")
        if isinstance(response_body, bytes):
            return response_body.decode("utf-8")
        return response_body or ""

    def _response_json(self, http_response):
        """Return the response body decoded as JSON."""
        return json.loads(self._response_text(http_response))

    def _setup_headers(self):
        """Return headers for a TRMNL setup request."""
        return {
            "ID": self.DEVICE_MAC_ADDRESS,
            "FW-Version": self.DEVICE_FIRMWARE_VERSION,
        }

    def _display_headers(self, api_token):
        """Return headers for a TRMNL display request."""
        return {
            "ID": self.DEVICE_MAC_ADDRESS,
            "Access-Token": api_token,
            "Refresh-Rate": str(self.DEVICE_REFRESH_RATE),
            "Battery-Voltage": self.DEVICE_BATTERY_VOLTAGE,
            "FW-Version": self.DEVICE_FIRMWARE_VERSION,
            "RSSI": self.DEVICE_RSSI,
            "Width": self.DEVICE_WIDTH,
            "Height": self.DEVICE_HEIGHT,
        }

    def _log_headers(self, api_token):
        """Return headers for a TRMNL log request."""
        return {
            "ID": self.DEVICE_MAC_ADDRESS,
            "Access-Token": api_token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _log_payload(self):
        """Return a realistic TRMNL log payload."""
        return {
            "log": {
                "logs_array": [
                    {
                        "creation_timestamp": 1234567890,
                        "device_status_stamp": {
                            "wifi_rssi_level": -69,
                            "wifi_status": "WL_CONNECTED",
                            "refresh_rate": self.DEVICE_REFRESH_RATE,
                            "time_since_last_sleep_start": 12345,
                            "current_fw_version": self.DEVICE_FIRMWARE_VERSION,
                            "special_function": "SF_NONE",
                            "battery_voltage": 4.1,
                            "wakeup_reason": "TIMER",
                            "free_heap_size": 123456,
                            "max_alloc_size": 98765,
                        },
                        "log_id": 1,
                        "log_message": "",
                        "log_codeline": 256,
                        "log_sourcefile": "src/bl.cpp",
                        "additional_info": {
                            "filename_current": "2024-09-20T00:00:00",
                            "filename_new": "new-image",
                        },
                    }
                ]
            }
        }

    def _seed_device_for_setup(self):
        """Create a device record so setup and display tests can run end-to-end."""
        return self.env["trmnl.device"].sudo().create(
            {
                "mac_address": self.DEVICE_MAC_ADDRESS,
                "friendly_id": self.DEVICE_FRIENDLY_ID,
                "image_url": self.DEVICE_IMAGE_URL,
                "refresh_rate": self.DEVICE_REFRESH_RATE,
                "special_function": "none",
            }
        )

    def _register_device_through_setup(self):
        """Register the seeded device via the real `/api/setup` endpoint."""
        seeded_device = self._seed_device_for_setup()

        setup_response = self.url_open("/api/setup", headers=self._setup_headers())
        self.assertEqual(self._response_status(setup_response), 200)

        setup_payload = self._response_json(setup_response)
        registered_device = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", self.DEVICE_MAC_ADDRESS)],
            limit=1,
        )

        self.assertTrue(registered_device, "The setup request should register the device.")
        self.assertEqual(registered_device.approval_state, "approved")
        self.assertEqual(registered_device.friendly_id, seeded_device.friendly_id)
        self.assertEqual(setup_payload["friendly_id"], registered_device.friendly_id)
        self.assertEqual(setup_payload["image_url"], registered_device.image_url)
        self.assertTrue(setup_payload["api_key"])

        verify_token_method = getattr(registered_device, "_verify_api_token", None)
        if callable(verify_token_method):
            self.assertTrue(
                verify_token_method(setup_payload["api_key"]),
                "The returned API key should match the stored hash.",
            )

        return registered_device, setup_payload["api_key"], setup_payload

    def _set_display_error_status_500(self, device_record=None):
        """Configure the code path that should return HTTP 500 for display failures."""
        config_parameters = self.env["ir.config_parameter"].sudo()
        config_parameters.set_param("trmnl.display_error_status", "500")

        if device_record is not None and "display_error_status_override" in device_record._fields:
            device_record.sudo().write({"display_error_status_override": "500"})

    def _call_json_endpoint(self, path, headers=None, payload=None):
        """Call an HTTP endpoint and return the raw response object."""
        request_headers = headers or {}
        request_payload = None
        if payload is not None:
            request_payload = json.dumps(payload).encode("utf-8")
        return self.url_open(path, data=request_payload, headers=request_headers)


@tagged("post_install", "-at_install")
class TestTrmnlSetupApi(HttpCase, TrmnlApiHttpCaseMixin):
    """Verify the `/api/setup` endpoint returns the trimmed setup payload."""

    def test_api_setup_success_returns_only_expected_keys(self):
        """A valid setup call should return only the four required keys."""
        seeded_device = self._seed_device_for_setup()

        setup_response = self.url_open("/api/setup", headers=self._setup_headers())
        setup_payload = self._response_json(setup_response)

        self.assertEqual(self._response_status(setup_response), 200)
        self.assertEqual(
            set(setup_payload.keys()),
            {"status", "api_key", "friendly_id", "image_url"},
        )
        self.assertEqual(
            setup_payload,
            {
                "status": 200,
                "api_key": setup_payload["api_key"],
                "friendly_id": seeded_device.friendly_id,
                "image_url": seeded_device.image_url,
            },
        )
        self.assertTrue(setup_payload["api_key"])

    def test_api_setup_failure_returns_only_404(self):
        """A setup call without a valid device identity should return 404 only."""
        setup_response = self.url_open(
            "/api/setup",
            headers={"FW-Version": self.DEVICE_FIRMWARE_VERSION},
        )
        setup_payload = self._response_json(setup_response)

        self.assertEqual(self._response_status(setup_response), 200)
        self.assertEqual(setup_payload, {"status": 404})


@tagged("post_install", "-at_install")
class TestTrmnlDisplayApi(HttpCase, TrmnlApiHttpCaseMixin):
    """Verify the `/api/display` endpoint returns the correct display payloads."""

    def test_api_display_success_returns_only_expected_keys(self):
        """A registered device should receive the minimal display payload."""
        registered_device, api_token, _setup_payload = self._register_device_through_setup()

        fixed_timestamp = dt.datetime(2026, 4, 11, 9, 30, 0)
        expected_filename = (
            f"{registered_device.friendly_id}-{fixed_timestamp.strftime('%Y-%m-%dT%H:%M:%S')}"
        )

        with patch.object(type(registered_device), "_utc_now", return_value=fixed_timestamp):
            display_response = self.url_open(
                "/api/display",
                headers=self._display_headers(api_token),
            )

        display_payload = self._response_json(display_response)

        self.assertEqual(self._response_status(display_response), 200)
        self.assertEqual(
            set(display_payload.keys()),
            {"status", "image_url", "filename", "refresh_rate", "special_function", "action"},
        )
        self.assertEqual(
            display_payload,
            {
                "status": 0,
                "image_url": self.DEVICE_IMAGE_URL,
                "filename": expected_filename,
                "refresh_rate": self.DEVICE_REFRESH_RATE,
                "special_function": "none",
                "action": "",
            },
        )

    def test_api_display_unknown_device_returns_202_by_default(self):
        """An unknown device should receive the default display rejection payload."""
        display_response = self.url_open(
            "/api/display",
            headers={
                "ID": "11:22:33:44:55:66",
                "Access-Token": "invalid-token",
                "Refresh-Rate": str(self.DEVICE_REFRESH_RATE),
                "Battery-Voltage": self.DEVICE_BATTERY_VOLTAGE,
                "FW-Version": self.DEVICE_FIRMWARE_VERSION,
                "RSSI": self.DEVICE_RSSI,
                "Width": self.DEVICE_WIDTH,
                "Height": self.DEVICE_HEIGHT,
            },
        )
        display_payload = self._response_json(display_response)

        self.assertEqual(self._response_status(display_response), 200)
        self.assertEqual(display_payload, {"status": 202})

    def test_api_display_invalid_token_returns_202_by_default(self):
        """A known device with a bad token should receive the default rejection payload."""
        _registered_device, api_token, _setup_payload = self._register_device_through_setup()

        display_response = self.url_open(
            "/api/display",
            headers=self._display_headers("bad-token"),
        )
        display_payload = self._response_json(display_response)

        self.assertEqual(self._response_status(display_response), 200)
        self.assertEqual(display_payload, {"status": 202})

    def test_api_display_unknown_device_can_be_forced_to_500(self):
        """An unknown device can be configured to force a reset response."""
        self._set_display_error_status_500()

        display_response = self.url_open(
            "/api/display",
            headers={
                "ID": "11:22:33:44:55:66",
                "Access-Token": "invalid-token",
                "Refresh-Rate": str(self.DEVICE_REFRESH_RATE),
                "Battery-Voltage": self.DEVICE_BATTERY_VOLTAGE,
                "FW-Version": self.DEVICE_FIRMWARE_VERSION,
                "RSSI": self.DEVICE_RSSI,
                "Width": self.DEVICE_WIDTH,
                "Height": self.DEVICE_HEIGHT,
            },
        )
        display_payload = self._response_json(display_response)

        self.assertEqual(self._response_status(display_response), 200)
        self.assertEqual(display_payload, {"status": 500})

    def test_api_display_invalid_token_can_be_forced_to_500(self):
        """A known device can be configured to force a reset response."""
        registered_device, api_token, _setup_payload = self._register_device_through_setup()
        self._set_display_error_status_500(registered_device)

        display_response = self.url_open(
            "/api/display",
            headers=self._display_headers("bad-token"),
        )
        display_payload = self._response_json(display_response)

        self.assertEqual(self._response_status(display_response), 200)
        self.assertEqual(display_payload, {"status": 500})


@tagged("post_install", "-at_install")
class TestTrmnlLogApi(HttpCase, TrmnlApiHttpCaseMixin):
    """Verify the `/api/log` endpoint accepts and rejects requests correctly."""

    def test_api_log_success_returns_204_without_body(self):
        """A valid log submission should return HTTP 204 with no response body."""
        registered_device, api_token, _setup_payload = self._register_device_through_setup()

        log_response = self._call_json_endpoint(
            "/api/log",
            headers=self._log_headers(api_token),
            payload=self._log_payload(),
        )

        self.assertEqual(self._response_status(log_response), 204)
        self.assertEqual(self._response_text(log_response), "")

    def test_api_log_missing_token_returns_401_without_body(self):
        """A log submission without an access token should return HTTP 401."""
        registered_device, _api_token, _setup_payload = self._register_device_through_setup()

        log_response = self._call_json_endpoint(
            "/api/log",
            headers={
                "ID": registered_device.mac_address,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            payload=self._log_payload(),
        )

        self.assertEqual(self._response_status(log_response), 401)
        self.assertEqual(self._response_text(log_response), "")

    def test_api_log_invalid_token_returns_401_without_body(self):
        """A log submission with a bad token should return HTTP 401."""
        _registered_device, _api_token, _setup_payload = self._register_device_through_setup()

        log_response = self._call_json_endpoint(
            "/api/log",
            headers=self._log_headers("bad-token"),
            payload=self._log_payload(),
        )

        self.assertEqual(self._response_status(log_response), 401)
        self.assertEqual(self._response_text(log_response), "")
