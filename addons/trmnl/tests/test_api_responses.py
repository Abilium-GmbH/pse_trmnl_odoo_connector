"""HTTP response tests for the TRMNL API endpoints."""

from __future__ import annotations

import datetime as dt
import json
from unittest.mock import patch

from odoo.tests.common import HttpCase, tagged

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
        request_headers = headers or {}
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
        setup_response = self.url_open("/api/setup", headers=self._setup_headers(setup_mac_address))
        setup_payload = self._response_json(setup_response)

        self.assertEqual(self._response_status(setup_response), 200)
        self.assertEqual(
            set(setup_payload.keys()),
            {"status", "api_key", "friendly_id", "image_url"},
        )
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

        return registered_device, setup_payload["api_key"], setup_payload

    def _display_unknown_headers(self, api_token, mac_address=None):
        """Return headers for an unknown device display request."""
        return self._display_headers(api_token, mac_address or self.UNKNOWN_MAC_ADDRESS)


@tagged("post_install", "-at_install")
class TestTrmnlSetupApi(HttpCase, TrmnlApiHttpCaseMixin):
    """Verify the `/api/setup` endpoint behavior."""

    def test_api_setup_success_returns_only_expected_keys(self):
        """A valid setup call should return only the required keys."""
        registered_device, api_token, setup_payload = self._register_device_through_setup()

        self.assertEqual(
            setup_payload,
            {
                "status": 200,
                "api_key": api_token,
                "friendly_id": registered_device.friendly_id,
                "image_url": registered_device.image_url,
            },
        )

    def test_api_setup_rejects_existing_mac_address(self):
        """A second setup request for the same MAC address should be rejected."""
        registered_device, api_token, setup_payload = self._register_device_through_setup()
        self.assertEqual(setup_payload["status"], 200)

        duplicate_response = self.url_open("/api/setup", headers=self._setup_headers())
        duplicate_payload = self._response_json(duplicate_response)

        self.assertEqual(self._response_status(duplicate_response), 200)
        self.assertEqual(duplicate_payload, {"status": 404})

        stored_device = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", registered_device.mac_address)],
            limit=1,
        )
        self.assertTrue(stored_device)
        self.assertTrue(stored_device._verify_api_token(api_token))
        self.assertEqual(stored_device.approval_state, "approved")
        self.assertEqual(stored_device.setup_request_count, 1)

    def test_api_setup_missing_id_returns_404(self):
        """Missing device identity should return the setup error payload."""
        setup_response = self.url_open(
            "/api/setup",
            headers={"FW-Version": self.DEVICE_FIRMWARE_VERSION},
        )
        setup_payload = self._response_json(setup_response)

        self.assertEqual(self._response_status(setup_response), 200)
        self.assertEqual(setup_payload, {"status": 404})

    def test_api_setup_invalid_mac_returns_404(self):
        """A malformed MAC address should return the setup error payload."""
        setup_response = self.url_open(
            "/api/setup",
            headers={
                "ID": "not-a-mac",
                "FW-Version": self.DEVICE_FIRMWARE_VERSION,
            },
        )
        setup_payload = self._response_json(setup_response)

        self.assertEqual(self._response_status(setup_response), 200)
        self.assertEqual(setup_payload, {"status": 404})


@tagged("post_install", "-at_install")
class TestTrmnlDisplayErrorPolicyApi(HttpCase, TrmnlApiHttpCaseMixin):
    """Verify the default error policy for `/api/display`."""

    def test_api_display_unknown_device_returns_202_by_default(self):
        """Unknown devices should receive the default display rejection payload."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)

        display_response = self.url_open(
            "/api/display",
            headers=self._display_unknown_headers(self.UNKNOWN_DEVICE_TOKEN),
        )
        display_payload = self._response_json(display_response)

        self.assertEqual(self._response_status(display_response), 200)
        self.assertEqual(display_payload, {"status": 202})

    def test_api_display_unknown_device_without_token_returns_202_by_default(self):
        """Unknown devices without a token should still get the default rejection payload."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)

        display_response = self.url_open(
            "/api/display",
            headers=self._display_unknown_headers(self.EMPTY_TOKEN),
        )
        display_payload = self._response_json(display_response)

        self.assertEqual(self._response_status(display_response), 200)
        self.assertEqual(display_payload, {"status": 202})

    def test_api_display_known_device_with_invalid_token_returns_202_by_default(self):
        """Known devices with a bad token should receive the default rejection payload."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)
        registered_device, api_token, setup_payload = self._register_device_through_setup()
        self.assertEqual(setup_payload["status"], 200)

        display_response = self.url_open(
            "/api/display",
            headers=self._display_headers(self.BAD_TOKEN, registered_device.mac_address),
        )
        display_payload = self._response_json(display_response)

        refreshed_device = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", registered_device.mac_address)],
            limit=1,
        )

        self.assertEqual(self._response_status(display_response), 200)
        self.assertEqual(display_payload, {"status": 202})
        self.assertTrue(refreshed_device._verify_api_token(api_token))
        self.assertEqual(refreshed_device.invalid_token_count, 1)
        self.assertEqual(refreshed_device.display_denied_count, 0)
        self.assertEqual(refreshed_device.display_request_count, 0)

    def test_api_display_missing_id_returns_202(self):
        """A display request without a MAC address should return the default rejection payload."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)

        display_response = self.url_open(
            "/api/display",
            headers={
                "Access-Token": self.BAD_TOKEN,
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

    def test_api_display_approved_device_returns_display_payload(self):
        """A registered and approved device should receive the display payload."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)
        registered_device, api_token, setup_payload = self._register_device_through_setup()
        self.assertEqual(setup_payload["status"], 200)

        fixed_timestamp = dt.datetime(2026, 4, 11, 9, 30, 0)
        expected_filename = "abilium_test_screen"

        with patch(
            "odoo.addons.trmnl.models.trmnl_device.TrmnlDevice._utc_now",
            return_value=fixed_timestamp,
        ):
            display_response = self.url_open(
                "/api/display",
                headers=self._display_headers(api_token, registered_device.mac_address),
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
                "image_url": registered_device.image_url,
                "filename": expected_filename,
                "refresh_rate": self.DEVICE_REFRESH_RATE,
                "special_function": "none",
                "action": "",
            },
        )
        self.assertEqual(registered_device.display_request_count, 1)


@tagged("post_install", "-at_install")
class TestTrmnlDisplayAutoAcceptPolicyApi(HttpCase, TrmnlApiHttpCaseMixin):
    """Verify the auto-accept policy for `/api/display`."""

    def test_api_display_unknown_device_is_registered_and_token_is_adopted(self):
        """Unknown devices should be registered by adopting the presented token."""
        self._set_display_policy(DISPLAY_POLICY_AUTO_ACCEPT)

        fixed_timestamp = dt.datetime(2026, 4, 11, 10, 15, 0)
        with patch(
            "odoo.addons.trmnl.models.trmnl_device.TrmnlDevice._utc_now",
            return_value=fixed_timestamp,
        ):
            display_response = self.url_open(
                "/api/display",
                headers=self._display_unknown_headers(self.UNKNOWN_DEVICE_TOKEN),
            )
        display_payload = self._response_json(display_response)

        self.assertEqual(self._response_status(display_response), 200)
        self.assertEqual(display_payload["status"], 0)

        adopted_device = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", self.UNKNOWN_MAC_ADDRESS)],
            limit=1,
        )
        self.assertTrue(adopted_device)
        self.assertEqual(adopted_device.approval_state, "approved")
        self.assertEqual(adopted_device.registration_source, "display")
        self.assertTrue(adopted_device._verify_api_token(self.UNKNOWN_DEVICE_TOKEN))
        self.assertEqual(adopted_device.display_request_count, 1)

        expected_filename = "abilium_test_screen"
        self.assertEqual(
            display_payload,
            {
                "status": 0,
                "image_url": adopted_device.image_url,
                "filename": expected_filename,
                "refresh_rate": self.DEVICE_REFRESH_RATE,
                "special_function": "none",
                "action": "",
            },
        )

        log_response = self._call_json_endpoint(
            "/api/log",
            headers=self._log_headers(self.UNKNOWN_DEVICE_TOKEN, self.UNKNOWN_MAC_ADDRESS),
            payload=self._empty_log_payload(),
        )
        self.assertEqual(self._response_status(log_response), 204)
        self.assertEqual(self._response_text(log_response), "")

    def test_api_display_known_device_with_invalid_token_is_adopted(self):
        """Known devices with an invalid token should adopt the presented token."""
        self._set_display_policy(DISPLAY_POLICY_AUTO_ACCEPT)
        registered_device, api_token, setup_payload = self._register_device_through_setup()
        self.assertEqual(setup_payload["status"], 200)

        fixed_timestamp = dt.datetime(2026, 4, 11, 11, 45, 0)
        with patch(
            "odoo.addons.trmnl.models.trmnl_device.TrmnlDevice._utc_now",
            return_value=fixed_timestamp,
        ):
            display_response = self.url_open(
                "/api/display",
                headers=self._display_headers(self.BAD_TOKEN, registered_device.mac_address),
            )
        display_payload = self._response_json(display_response)

        self.assertEqual(self._response_status(display_response), 200)
        self.assertEqual(display_payload["status"], 0)
        self.assertTrue(registered_device._verify_api_token(self.BAD_TOKEN))
        self.assertFalse(registered_device._verify_api_token(api_token))
        self.assertEqual(registered_device.registration_source, "display")
        self.assertEqual(registered_device.approval_state, "approved")
        self.assertEqual(registered_device.display_request_count, 1)
        self.assertEqual(registered_device.invalid_token_count, 0)
        self.assertEqual(registered_device.display_denied_count, 0)

        expected_filename = "abilium_test_screen"
        self.assertEqual(
            display_payload,
            {
                "status": 0,
                "image_url": registered_device.image_url,
                "filename": expected_filename,
                "refresh_rate": self.DEVICE_REFRESH_RATE,
                "special_function": "none",
                "action": "",
            },
        )

        log_response = self._call_json_endpoint(
            "/api/log",
            headers=self._log_headers(self.BAD_TOKEN, registered_device.mac_address),
            payload=self._log_payload(),
        )
        self.assertEqual(self._response_status(log_response), 204)
        self.assertEqual(self._response_text(log_response), "")


@tagged("post_install", "-at_install")
class TestTrmnlDisplayFactoryResetPolicyApi(HttpCase, TrmnlApiHttpCaseMixin):
    """Verify the one-shot factory-reset policy for `/api/display`."""

    def test_api_display_unknown_device_triggers_factory_reset_once(self):
        """The factory-reset policy should emit 500 once and then revert to default."""
        self._set_display_policy(DISPLAY_POLICY_FACTORY_RESET)

        first_response = self.url_open(
            "/api/display",
            headers=self._display_unknown_headers(self.UNKNOWN_DEVICE_TOKEN),
        )
        first_payload = self._response_json(first_response)

        self.assertEqual(self._response_status(first_response), 200)
        self.assertEqual(first_payload, {"status": 500})
        self.assertEqual(self._get_display_policy(), DISPLAY_POLICY_ERROR)

        second_response = self.url_open(
            "/api/display",
            headers=self._display_unknown_headers(self.UNKNOWN_DEVICE_TOKEN),
        )
        second_payload = self._response_json(second_response)

        self.assertEqual(self._response_status(second_response), 200)
        self.assertEqual(second_payload, {"status": 202})

    def test_api_display_known_device_with_invalid_token_triggers_factory_reset_once(self):
        """Known devices with a bad token should also get the one-shot reset response."""
        self._set_display_policy(DISPLAY_POLICY_FACTORY_RESET)
        registered_device, api_token, setup_payload = self._register_device_through_setup()
        self.assertEqual(setup_payload["status"], 200)

        first_response = self.url_open(
            "/api/display",
            headers=self._display_headers(self.BAD_TOKEN, registered_device.mac_address),
        )
        first_payload = self._response_json(first_response)

        self.assertEqual(self._response_status(first_response), 200)
        self.assertEqual(first_payload, {"status": 500})
        self.assertEqual(self._get_display_policy(), DISPLAY_POLICY_ERROR)
        self.assertEqual(registered_device.display_request_count, 0)
        self.assertEqual(registered_device.invalid_token_count, 0)

        second_response = self.url_open(
            "/api/display",
            headers=self._display_headers(self.BAD_TOKEN, registered_device.mac_address),
        )
        second_payload = self._response_json(second_response)

        self.assertEqual(self._response_status(second_response), 200)
        self.assertEqual(second_payload, {"status": 202})


@tagged("post_install", "-at_install")
class TestTrmnlLogApi(HttpCase, TrmnlApiHttpCaseMixin):
    """Verify the `/api/log` endpoint accepts and rejects requests correctly."""

    def test_api_log_success_returns_204_without_body(self):
        """A valid log submission should return HTTP 204 with no response body."""
        registered_device, api_token, setup_payload = self._register_device_through_setup()
        self.assertEqual(setup_payload["status"], 200)

        log_response = self._call_json_endpoint(
            "/api/log",
            headers=self._log_headers(api_token, registered_device.mac_address),
            payload=self._log_payload(),
        )

        self.assertEqual(self._response_status(log_response), 204)
        self.assertEqual(self._response_text(log_response), "")

        log_entry = self.env["trmnl.device.log"].sudo().search(
            [("device_id", "=", registered_device.id), ("log_id", "=", 1)],
            limit=1,
        )
        self.assertTrue(log_entry)
        self.assertEqual(log_entry.log_sourcefile, "src/bl.cpp")
        self.assertFalse(log_entry.log_message)
        self.assertEqual(registered_device.log_entry_count, 1)

    def test_api_log_empty_payload_returns_204_without_body(self):
        """An empty log payload should still return HTTP 204."""
        registered_device, api_token, setup_payload = self._register_device_through_setup()
        self.assertEqual(setup_payload["status"], 200)

        log_response = self._call_json_endpoint(
            "/api/log",
            headers=self._log_headers(api_token, registered_device.mac_address),
            payload=self._empty_log_payload(),
        )

        self.assertEqual(self._response_status(log_response), 204)
        self.assertEqual(self._response_text(log_response), "")
        self.assertEqual(registered_device.log_entry_count, 0)

    def test_api_log_missing_identity_returns_401_without_body(self):
        """A log submission without a device identity should return HTTP 401."""
        registered_device, api_token, setup_payload = self._register_device_through_setup()
        self.assertEqual(setup_payload["status"], 200)

        log_response = self._call_json_endpoint(
            "/api/log",
            headers={
                "Access-Token": api_token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            payload=self._log_payload(),
        )

        self.assertEqual(self._response_status(log_response), 401)
        self.assertEqual(self._response_text(log_response), "")

    def test_api_log_unknown_device_returns_401_without_body(self):
        """A log submission from an unknown device should return HTTP 401."""
        log_response = self._call_json_endpoint(
            "/api/log",
            headers=self._log_headers(self.UNKNOWN_DEVICE_TOKEN, self.UNKNOWN_MAC_ADDRESS),
            payload=self._log_payload(),
        )

        self.assertEqual(self._response_status(log_response), 401)
        self.assertEqual(self._response_text(log_response), "")

    def test_api_log_missing_token_returns_401_without_body(self):
        """A log submission without an access token should return HTTP 401."""
        registered_device, api_token, setup_payload = self._register_device_through_setup()
        self.assertEqual(setup_payload["status"], 200)

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
        registered_device, api_token, setup_payload = self._register_device_through_setup()
        self.assertEqual(setup_payload["status"], 200)

        log_response = self._call_json_endpoint(
            "/api/log",
            headers=self._log_headers(self.BAD_TOKEN, registered_device.mac_address),
            payload=self._log_payload(),
        )

        self.assertEqual(self._response_status(log_response), 401)
        self.assertEqual(self._response_text(log_response), "")
