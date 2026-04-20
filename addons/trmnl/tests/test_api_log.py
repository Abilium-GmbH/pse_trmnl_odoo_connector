"""Tests for the TRMNL `/api/log` endpoint."""

from odoo.tests import HttpCase, tagged

from .test_api_common import TrmnlApiHttpCaseMixin


@tagged("-at_install", "post_install")
class TestTrmnlLogApi(HttpCase, TrmnlApiHttpCaseMixin):
    """Verify the `/api/log` endpoint stores and rejects requests correctly."""

    def test_api_log_success_stores_batched_logs_and_updates_device_summary(self):
        """A valid batched log submission should store both entries."""
        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]
        api_token = setup_context["api_token"]

        payload = self._log_payload(
            [
                self._log_entry(
                    log_id=42,
                    created_at=1745000000,
                    message="Image render failed: unexpected EOF",
                    source_line=318,
                    source_path="src/bl.cpp",
                    wifi_signal=-67,
                    wifi_status="Connected",
                    refresh_rate=1800,
                    sleep_duration=145,
                    firmware_version="1.5.2",
                    special_function="None",
                    battery_voltage=3.95,
                    wake_reason="Timer",
                    free_heap_size=48320,
                    max_alloc_size=38912,
                ),
                self._log_entry(
                    log_id=43,
                    created_at=1745000001,
                    message="Retry succeeded",
                    source_line=319,
                    source_path="src/bl.cpp",
                    wifi_signal=-67,
                    wifi_status="Connected",
                    refresh_rate=1800,
                    sleep_duration=145,
                    firmware_version="1.5.2",
                    special_function="None",
                    battery_voltage=3.95,
                    wake_reason="Timer",
                    free_heap_size=48320,
                    max_alloc_size=38912,
                    retry=1,
                ),
            ]
        )

        log_response = self._call_json_endpoint(
            "/api/log",
            headers=self._log_headers(api_token, registered_device.mac_address),
            payload=payload,
        )

        self.assertEqual(self._response_status(log_response), 204)
        self.assertEqual(self._response_text(log_response), "")

        refreshed_device = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", registered_device.mac_address)],
            limit=1,
        )

        log_entries = self.env["trmnl.device.log"].sudo().search(
            [("device_id", "=", refreshed_device.id)],
            order="log_id asc",
        )

        self.assertEqual(len(log_entries), 2)

        first_log_entry, second_log_entry = log_entries

        self.assertEqual(first_log_entry.log_id, 42)
        self.assertEqual(first_log_entry.name, "42: Image render failed: unexpected EOF")
        self.assertEqual(first_log_entry.log_message, "Image render failed: unexpected EOF")
        self.assertEqual(first_log_entry.log_sourcefile, "src/bl.cpp")
        self.assertEqual(first_log_entry.log_codeline, 318)
        self.assertEqual(first_log_entry.creation_timestamp, 1745000000)
        self.assertEqual(first_log_entry.wifi_status, "Connected")
        self.assertEqual(first_log_entry.wifi_rssi_level, -67)
        self.assertEqual(first_log_entry.time_since_last_sleep_start, 145)
        self.assertEqual(first_log_entry.current_fw_version, "1.5.2")
        self.assertFalse(first_log_entry.retry_attempt)

        self.assertEqual(second_log_entry.log_id, 43)
        self.assertEqual(second_log_entry.retry_attempt, 1)

        self.assertEqual(refreshed_device.log_entry_count, 2)
        self.assertTrue(refreshed_device.last_log_at)

    def test_api_log_empty_payload_returns_204_without_body(self):
        """An empty log payload should still return HTTP 204."""
        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]
        api_token = setup_context["api_token"]

        log_response = self._call_json_endpoint(
            "/api/log",
            headers=self._log_headers(api_token, registered_device.mac_address),
            payload=self._empty_log_payload(),
        )

        self.assertEqual(self._response_status(log_response), 204)
        self.assertEqual(self._response_text(log_response), "")

        refreshed_device = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", registered_device.mac_address)],
            limit=1,
        )

        self.assertEqual(refreshed_device.log_entry_count, 0)

    def test_api_log_missing_identity_returns_401_without_body(self):
        """A log submission without a device identity should return HTTP 401."""
        setup_context = self._register_device_through_setup()
        api_token = setup_context["api_token"]

        log_response = self._call_json_endpoint(
            "/api/log",
            headers={
                "Access-Token": api_token,
                "Accept": "application/json, */*",
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
        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]

        log_response = self._call_json_endpoint(
            "/api/log",
            headers={
                "ID": registered_device.mac_address,
                "Accept": "application/json, */*",
                "Content-Type": "application/json",
            },
            payload=self._log_payload(),
        )

        self.assertEqual(self._response_status(log_response), 401)
        self.assertEqual(self._response_text(log_response), "")

    def test_api_log_invalid_token_returns_401_without_body(self):
        """A log submission with a bad token should return HTTP 401."""
        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]

        log_response = self._call_json_endpoint(
            "/api/log",
            headers=self._log_headers(self.BAD_TOKEN, registered_device.mac_address),
            payload=self._log_payload(),
        )

        self.assertEqual(self._response_status(log_response), 401)
        self.assertEqual(self._response_text(log_response), "")
