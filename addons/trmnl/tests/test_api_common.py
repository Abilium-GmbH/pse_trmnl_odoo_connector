"""Shared utilities for TRMNL API HTTP response tests."""

import json

DISPLAY_POLICY_PARAMETER = "trmnl.display_unknown_device_policy"

DISPLAY_POLICY_ERROR = "error"

DISPLAY_POLICY_AUTO_ACCEPT = "auto_accept"

DISPLAY_POLICY_FACTORY_RESET = "factory_reset"


class TrmnlApiHttpCaseMixin:
    """Shared helpers for TRMNL API response tests."""

    DEVICE_MAC_ADDRESS = "AA:BB:CC:DD:EE:FF"
    DEVICE_FIRMWARE_VERSION = "1.5.2"
    DEVICE_REFRESH_RATE = 1800
    DEVICE_BATTERY_VOLTAGE = "4.1"
    DEVICE_RSSI = "-69"
    DEVICE_WIDTH = "800"
    DEVICE_HEIGHT = "480"
    UNKNOWN_MAC_ADDRESS = "11:22:33:44:55:66"
    UNKNOWN_DEVICE_TOKEN = "unknown-device-token"
    BAD_TOKEN = "bad-token"
    EMPTY_TOKEN = ""
    EXPECTED_FILENAME = "abilium_test_screen"

    def _response_status(self, http_response):
        """Return the HTTP status code for a `url_open` response."""

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

    def _log_headers(self, api_token, mac_address=None):
        """Return headers for a TRMNL log request."""

        return {
            "ID": mac_address or self.DEVICE_MAC_ADDRESS,
            "Access-Token": api_token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _log_payload(self, log_message=""):
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
                        "log_message": log_message,
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

    def _empty_log_payload(self):
        """Return a payload that contains no log entries."""

        return {"log": {"logs_array": []}}

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

    def _register_device_through_setup(self, mac_address=None):
        """Register a device through the real `/api/setup` endpoint."""

        setup_mac_address = mac_address or self.DEVICE_MAC_ADDRESS
        setup_response = self.url_open(
            "/api/setup",
            headers=self._setup_headers(setup_mac_address),
        )
        setup_payload = self._response_json(setup_response)

        self.assertEqual(self._response_status(setup_response), 200)

        expected_keys = {"status", "api_key", "friendly_id", "image_url"}
        self.assertEqual(set(setup_payload.keys()), expected_keys)
        self.assertEqual(setup_payload["status"], 200)
        self.assertTrue(setup_payload["api_key"])

        registered_device = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", setup_mac_address)],
            limit=1,
        )

        self.assertTrue(registered_device, "The setup request should register the device.")
        self.assertEqual(registered_device.approval_state, "approved")
        self.assertEqual(registered_device.registration_source, "setup")
        self.assertEqual(registered_device.setup_request_count, 1)
        self.assertEqual(registered_device.friendly_id, setup_payload["friendly_id"])
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
        """Assert the standard successful `/api/display` payload."""

        expected_keys = {"status", "image_url", "filename", "refresh_rate", "special_function", "action"}
        self.assertEqual(set(display_payload.keys()), expected_keys)
        self.assertEqual(
            display_payload,
            {
                "status": 0,
                "image_url": image_url,
                "filename": self.EXPECTED_FILENAME,
                "refresh_rate": self.DEVICE_REFRESH_RATE,
                "special_function": "none",
                "action": "",
            },
        )
