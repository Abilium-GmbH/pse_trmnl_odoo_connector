"""Tests for the TRMNL ``/api/display`` endpoint."""

import datetime as dt
from unittest.mock import patch

from odoo.tests import HttpCase, tagged

from odoo.addons.trmnl.models.trmnl_device import (
    DEFAULT_REFRESH_RATE,
    REFRESH_RATE_UNIT_SECONDS,
)

from .test_api_common import (
    APPROVAL_STATE_ACCEPTED,
    APPROVAL_STATE_TOKEN_MISMATCH,
    APPROVAL_STATE_UNKNOWN_DEVICE,
    DISPLAY_POLICY_AUTO_ACCEPT,
    DISPLAY_POLICY_ERROR,
    DISPLAY_POLICY_FACTORY_RESET,
    TrmnlApiHttpCaseMixin,
)


@tagged("-at_install", "post_install")
class TestTrmnlDisplayErrorPolicyApi(HttpCase, TrmnlApiHttpCaseMixin):
    """Verify the default error policy for ``/api/display``."""

    def test_api_display_unknown_device_returns_202_and_creates_stub(self):
        """Unknown devices should receive the error payload and a stub record is created."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)

        display_response = self.url_open(
            "/api/display",
            headers=self._display_unknown_headers(self.UNKNOWN_DEVICE_TOKEN),
        )
        display_payload = self._response_json(display_response)

        self.assertEqual(self._response_status(display_response), 200)
        self.assertEqual(display_payload, {"status": 202})

        stub_device = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", self.UNKNOWN_MAC_ADDRESS)],
            limit=1,
        )
        self.assertTrue(stub_device, "A stub record should be created for unknown devices.")
        self.assertEqual(stub_device.approval_state, APPROVAL_STATE_UNKNOWN_DEVICE)
        self.assertFalse(stub_device.friendly_id)
        self.assertTrue(stub_device.last_presented_token_hash)

    def test_api_display_unknown_device_without_token_returns_202_and_creates_stub(self):
        """Unknown devices without a token receive the error payload; stub has no presented token."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)

        display_response = self.url_open(
            "/api/display",
            headers=self._display_unknown_headers(self.EMPTY_TOKEN),
        )
        display_payload = self._response_json(display_response)

        self.assertEqual(self._response_status(display_response), 200)
        self.assertEqual(display_payload, {"status": 202})

        stub_device = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", self.UNKNOWN_MAC_ADDRESS)],
            limit=1,
        )
        self.assertTrue(stub_device)
        self.assertEqual(stub_device.approval_state, APPROVAL_STATE_UNKNOWN_DEVICE)
        self.assertFalse(stub_device.last_presented_token_hash)

    def test_api_display_known_device_with_invalid_token_returns_202_and_records_mismatch(self):
        """Known devices with a bad token receive the error payload and state becomes token_mismatch."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)

        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]
        api_token = setup_context["api_token"]

        display_response = self.url_open(
            "/api/display",
            headers=self._display_headers(self.BAD_TOKEN, registered_device.mac_address),
        )
        display_payload = self._response_json(display_response)

        self.assertEqual(self._response_status(display_response), 200)
        self.assertEqual(display_payload, {"status": 202})

        refreshed_device = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", registered_device.mac_address)],
            limit=1,
        )

        self.assertTrue(refreshed_device._verify_api_token(api_token))
        self.assertEqual(refreshed_device.approval_state, APPROVAL_STATE_TOKEN_MISMATCH)
        self.assertEqual(refreshed_device.invalid_token_count, 1)
        self.assertEqual(refreshed_device.display_denied_count, 0)
        self.assertEqual(refreshed_device.display_request_count, 0)
        self.assertTrue(refreshed_device.last_presented_token_hash)

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

    def test_api_display_accepted_device_returns_display_payload(self):
        """A registered and accepted device should receive the display payload."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)

        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]
        api_token = setup_context["api_token"]

        fixed_timestamp = dt.datetime(2026, 4, 11, 9, 30, 0)

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

        refreshed_device = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", registered_device.mac_address)],
            limit=1,
        )

        self._assert_display_success_payload(display_payload, refreshed_device.image_url)
        self.assertEqual(refreshed_device.display_request_count, 1)

    def test_api_display_returns_desired_refresh_rate_not_reported_rate(self):
        """The display response must carry the admin-set rate, not the device-reported rate."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)

        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]
        api_token = setup_context["api_token"]

        admin_desired_rate = 900
        registered_device.write({"desired_refresh_rate": admin_desired_rate})

        device_reported_rate = 60
        display_response = self.url_open(
            "/api/display",
            headers=self._display_headers_with_rate(
                api_token,
                registered_device.mac_address,
                device_reported_rate,
            ),
        )
        display_payload = self._response_json(display_response)

        self.assertEqual(self._response_status(display_response), 200)
        self.assertEqual(display_payload["refresh_rate"], admin_desired_rate)

        refreshed_device = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", registered_device.mac_address)],
            limit=1,
        )
        self.assertEqual(refreshed_device.refresh_rate, device_reported_rate)
        self.assertEqual(refreshed_device.desired_refresh_rate, admin_desired_rate)

    def test_api_display_desired_refresh_rate_update_takes_effect_immediately(self):
        """Changing ``desired_refresh_rate`` between polls must be reflected in the next response."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)

        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]
        api_token = setup_context["api_token"]

        first_response = self.url_open(
            "/api/display",
            headers=self._display_headers(api_token, registered_device.mac_address),
        )
        first_payload = self._response_json(first_response)
        self.assertEqual(first_payload["refresh_rate"], DEFAULT_REFRESH_RATE)

        new_rate = 4 * REFRESH_RATE_UNIT_SECONDS["hours"]
        registered_device.write({"desired_refresh_rate": new_rate})

        second_response = self.url_open(
            "/api/display",
            headers=self._display_headers(api_token, registered_device.mac_address),
        )
        second_payload = self._response_json(second_response)
        self.assertEqual(second_payload["refresh_rate"], new_rate)

    def test_api_display_device_reported_rate_does_not_overwrite_desired_rate(self):
        """A display poll must not clobber the admin-configured desired refresh rate."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)

        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]
        api_token = setup_context["api_token"]

        admin_desired_rate = 2 * REFRESH_RATE_UNIT_SECONDS["hours"]
        registered_device.write({"desired_refresh_rate": admin_desired_rate})

        device_reported_rate = DEFAULT_REFRESH_RATE
        self.url_open(
            "/api/display",
            headers=self._display_headers_with_rate(
                api_token,
                registered_device.mac_address,
                device_reported_rate,
            ),
        )

        refreshed_device = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", registered_device.mac_address)],
            limit=1,
        )
        self.assertEqual(
            refreshed_device.desired_refresh_rate,
            admin_desired_rate,
            "A device poll must never overwrite the admin-configured desired refresh rate.",
        )
        self.assertEqual(refreshed_device.refresh_rate, device_reported_rate)


@tagged("-at_install", "post_install")
class TestTrmnlDisplayAutoAcceptPolicyApi(HttpCase, TrmnlApiHttpCaseMixin):
    """Verify the auto-accept policy for ``/api/display``."""

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

        adopted_device = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", self.UNKNOWN_MAC_ADDRESS)],
            limit=1,
        )

        self.assertTrue(adopted_device)
        self.assertEqual(adopted_device.approval_state, APPROVAL_STATE_ACCEPTED)
        self.assertEqual(adopted_device.registration_source, "display")
        self.assertTrue(adopted_device._verify_api_token(self.UNKNOWN_DEVICE_TOKEN))
        self.assertEqual(adopted_device.display_request_count, 1)

        self._assert_display_success_payload(display_payload, adopted_device.image_url)

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

        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]
        api_token = setup_context["api_token"]

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

        refreshed_device = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", registered_device.mac_address)],
            limit=1,
        )

        self.assertTrue(refreshed_device._verify_api_token(self.BAD_TOKEN))
        self.assertFalse(refreshed_device._verify_api_token(api_token))
        self.assertEqual(refreshed_device.registration_source, "display")
        self.assertEqual(refreshed_device.approval_state, APPROVAL_STATE_ACCEPTED)
        self.assertEqual(refreshed_device.display_request_count, 1)
        self.assertEqual(refreshed_device.invalid_token_count, 0)
        self.assertEqual(refreshed_device.display_denied_count, 0)

        self._assert_display_success_payload(display_payload, refreshed_device.image_url)

        log_response = self._call_json_endpoint(
            "/api/log",
            headers=self._log_headers(self.BAD_TOKEN, registered_device.mac_address),
            payload=self._log_payload(),
        )

        self.assertEqual(self._response_status(log_response), 204)
        self.assertEqual(self._response_text(log_response), "")


@tagged("-at_install", "post_install")
class TestTrmnlDisplayFactoryResetPolicyApi(HttpCase, TrmnlApiHttpCaseMixin):
    """Verify the one-shot factory-reset policy for ``/api/display``."""

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

        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]

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
