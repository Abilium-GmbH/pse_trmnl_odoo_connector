"""Tests for the TRMNL `/api/log` endpoint."""

from odoo.tests import HttpCase, tagged

from .test_api_common import TrmnlApiHttpCaseMixin


@tagged("-at_install", "post_install")
class TestTrmnlLogApi(HttpCase, TrmnlApiHttpCaseMixin):
    """Verify the `/api/log` endpoint accepts and rejects requests correctly."""

    def test_api_log_success_returns_204_without_body(self):
        """A valid log submission should return HTTP 204 with no response body."""

        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]
        api_token = setup_context["api_token"]

        log_response = self._call_json_endpoint(
            "/api/log",
            headers=self._log_headers(api_token, registered_device.mac_address),
            payload=self._log_payload(),
        )

        self.assertEqual(self._response_status(log_response), 204)
        self.assertEqual(self._response_text(log_response), "")

        refreshed_device = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", registered_device.mac_address)],
            limit=1,
        )

        log_entry = self.env["trmnl.device.log"].sudo().search(
            [("device_id", "=", refreshed_device.id), ("log_id", "=", 1)],
            limit=1,
        )

        self.assertTrue(log_entry)
        self.assertEqual(log_entry.log_sourcefile, "src/bl.cpp")
        self.assertFalse(log_entry.log_message)
        self.assertEqual(refreshed_device.log_entry_count, 1)

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
        registered_device = setup_context["device"]
        api_token = setup_context["api_token"]

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

        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]

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

        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]

        log_response = self._call_json_endpoint(
            "/api/log",
            headers=self._log_headers(self.BAD_TOKEN, registered_device.mac_address),
            payload=self._log_payload(),
        )

        self.assertEqual(self._response_status(log_response), 401)
        self.assertEqual(self._response_text(log_response), "")
