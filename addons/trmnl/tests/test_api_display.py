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
    """Verify the persistent factory-reset policy for ``/api/display``."""

    def test_api_display_factory_reset_policy_returns_500_for_every_unknown_device(self):
        """Factory reset policy should return 500 for every unknown device poll."""
        self._set_display_policy(DISPLAY_POLICY_FACTORY_RESET)

        first_response = self.url_open(
            "/api/display",
            headers=self._display_unknown_headers(self.UNKNOWN_DEVICE_TOKEN),
        )
        first_payload = self._response_json(first_response)

        self.assertEqual(self._response_status(first_response), 200)
        self.assertEqual(first_payload, {"status": 500})
        self.assertEqual(self._get_display_policy(), DISPLAY_POLICY_FACTORY_RESET)

        second_response = self.url_open(
            "/api/display",
            headers=self._display_unknown_headers(self.UNKNOWN_DEVICE_TOKEN),
        )
        second_payload = self._response_json(second_response)

        self.assertEqual(self._response_status(second_response), 200)
        self.assertEqual(second_payload, {"status": 500})
        self.assertEqual(self._get_display_policy(), DISPLAY_POLICY_FACTORY_RESET)

    def test_api_display_factory_reset_policy_returns_500_for_every_token_mismatch(self):
        """Factory reset policy should return 500 for token mismatch and delete the record.

        The first poll deletes the device record after responding with 500.
        A subsequent poll from the same MAC is treated as an unknown device
        and continues to receive 500 under the factory-reset policy.
        """
        self._set_display_policy(DISPLAY_POLICY_FACTORY_RESET)

        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]
        mac_address = registered_device.mac_address

        first_response = self.url_open(
            "/api/display",
            headers=self._display_headers(self.BAD_TOKEN, mac_address),
        )
        first_payload = self._response_json(first_response)

        self.assertEqual(self._response_status(first_response), 200)
        self.assertEqual(first_payload, {"status": 500})
        self.assertEqual(self._get_display_policy(), DISPLAY_POLICY_FACTORY_RESET)

        device_after_first = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", mac_address)],
            limit=1,
        )
        self.assertFalse(
            device_after_first,
            "The device record must be deleted after the factory-reset response.",
        )

        second_response = self.url_open(
            "/api/display",
            headers=self._display_headers(self.BAD_TOKEN, mac_address),
        )
        second_payload = self._response_json(second_response)

        self.assertEqual(self._response_status(second_response), 200)
        self.assertEqual(second_payload, {"status": 500})
        self.assertEqual(self._get_display_policy(), DISPLAY_POLICY_FACTORY_RESET)


@tagged("-at_install", "post_install")
class TestTrmnlDisplayIdentifyApi(HttpCase, TrmnlApiHttpCaseMixin):
    """Verify the one-shot identify behavior for /api/display."""

    def test_api_display_identify_one_shot_behavior(self):
        """Identify should be returned once and then reset."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)

        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]
        api_token = setup_context["api_token"]

        registered_device.write({"identify_pending": True})

        first_response = self.url_open(
            "/api/display",
            headers=self._display_headers(api_token, registered_device.mac_address),
        )
        first_payload = self._response_json(first_response)

        self.assertEqual(self._response_status(first_response), 200)

        refreshed_device = self.env["trmnl.device"].sudo().browse(registered_device.id)

        self._assert_identify_payload(first_payload, refreshed_device.image_url)
        self.assertFalse(refreshed_device.identify_pending)

        second_response = self.url_open(
            "/api/display",
            headers=self._display_headers(api_token, registered_device.mac_address),
        )
        second_payload = self._response_json(second_response)

        self.assertEqual(self._response_status(second_response), 200)

        refreshed_device_after_second_call = self.env["trmnl.device"].sudo().browse(
            registered_device.id
        )

        self._assert_display_success_payload(
            second_payload,
            refreshed_device_after_second_call.image_url,
        )

        self.assertFalse(refreshed_device_after_second_call.identify_pending)

    def test_api_display_identify_does_not_persist_across_multiple_requests(self):
        """Identify must not repeat without being re-triggered."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)

        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]
        api_token = setup_context["api_token"]

        registered_device.write({"identify_pending": True})

        self.url_open(
            "/api/display",
            headers=self._display_headers(api_token, registered_device.mac_address),
        )

        for iteration_index in range(3):
            response = self.url_open(
                "/api/display",
                headers=self._display_headers(api_token, registered_device.mac_address),
            )
            payload = self._response_json(response)

            self.assertEqual(self._response_status(response), 200)

            refreshed_device = self.env["trmnl.device"].sudo().browse(
                registered_device.id
            )

            self._assert_display_success_payload(
                payload,
                refreshed_device.image_url,
            )

            self.assertFalse(refreshed_device.identify_pending)

    def test_api_display_identify_only_for_accepted_devices(self):
        """Identify should only work for accepted devices."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)

        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]

        registered_device.write({"approval_state": APPROVAL_STATE_TOKEN_MISMATCH})
        registered_device.write({"identify_pending": True})

        response = self.url_open(
            "/api/display",
            headers=self._display_headers(self.BAD_TOKEN, registered_device.mac_address),
        )
        payload = self._response_json(response)

        self.assertEqual(self._response_status(response), 200)
        self.assertEqual(payload, {"status": 202})


@tagged("-at_install", "post_install")
class TestTrmnlDisplayPerDeviceResetApi(HttpCase, TrmnlApiHttpCaseMixin):
    """Verify per-device factory-reset behaviour via the reset_pending flag."""

    def test_reset_pending_device_receives_reset_firmware_signal_with_correct_token(self):
        """A device with reset_pending True should receive the reset signal on its next poll."""
        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]
        api_token = setup_context["api_token"]

        registered_device.write({"reset_pending": True})

        mac_address = registered_device.mac_address
        filename = registered_device.filename
        image_url = registered_device.image_url
        desired_refresh_rate = registered_device.desired_refresh_rate

        response = self.url_open(
            "/api/display",
            headers=self._display_headers(api_token, mac_address),
        )
        payload = self._response_json(response)

        self.assertEqual(self._response_status(response), 200)
        self.assertEqual(
            payload,
            {
                "status": 0,
                "filename": filename,
                "image_url": image_url,
                "refresh_rate": desired_refresh_rate,
                "special_function": "none",
                "action": "",
                "reset_firmware": True,
            },
        )

        device_after = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", mac_address)],
            limit=1,
        )
        self.assertFalse(device_after)

    def test_reset_pending_device_receives_reset_firmware_signal_with_wrong_token(self):
        """A device with reset_pending True should receive the reset signal regardless of token."""
        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]

        registered_device.write({"reset_pending": True})

        mac_address = registered_device.mac_address

        response = self.url_open(
            "/api/display",
            headers=self._display_headers(self.BAD_TOKEN, mac_address),
        )
        payload = self._response_json(response)

        self.assertEqual(self._response_status(response), 200)
        self.assertIn("reset_firmware", payload)
        self.assertTrue(payload["reset_firmware"])
        self.assertEqual(payload["status"], 0)

        device_after = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", mac_address)],
            limit=1,
        )
        self.assertFalse(device_after)

    def test_reset_pending_device_does_not_affect_other_devices(self):
        """Setting reset_pending on one device must not affect other devices' display polls."""
        setup_context_a = self._register_device_through_setup(
            mac_address=self.DEVICE_MAC_ADDRESS
        )
        device_a = setup_context_a["device"]

        setup_context_b = self._register_device_through_setup(
            mac_address="FF:EE:DD:CC:BB:AA"
        )
        device_b = setup_context_b["device"]
        token_b = setup_context_b["api_token"]

        device_a.write({"reset_pending": True})

        response = self.url_open(
            "/api/display",
            headers=self._display_headers(token_b, device_b.mac_address),
        )
        payload = self._response_json(response)

        self.assertEqual(self._response_status(response), 200)
        self.assertNotIn("reset_firmware", payload)

        device_b_after = self.env["trmnl.device"].sudo().browse(device_b.id)
        self.assertTrue(device_b_after)

        device_a_after = self.env["trmnl.device"].sudo().browse(device_a.id)
        self.assertTrue(device_a_after)

    def test_reset_pending_flag_is_cleared_by_setup_call_and_device_is_reregistered(self):
        """A setup call from a reset_pending device should clear the flag and reregister."""
        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]
        old_device_id = registered_device.id
        old_token = setup_context["api_token"]

        registered_device.write({"reset_pending": True})

        mac_address = registered_device.mac_address

        response = self.url_open(
            "/api/setup",
            headers=self._setup_headers(),
        )
        payload = self._response_json(response)

        self.assertEqual(self._response_status(response), 200)
        self.assertEqual(payload["status"], 200)
        self.assertTrue(payload["api_key"])
        self.assertNotEqual(payload["api_key"], old_token)

        devices = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", mac_address)]
        )
        self.assertEqual(len(devices), 1)

        new_device = devices[0]
        self.assertNotEqual(new_device.id, old_device_id)
        self.assertFalse(new_device.reset_pending)
        self.assertEqual(new_device.approval_state, APPROVAL_STATE_ACCEPTED)
        self.assertTrue(new_device._verify_api_token(payload["api_key"]))


@tagged("-at_install", "post_install")
class TestTrmnlDisplayPolicyPersistenceApi(HttpCase, TrmnlApiHttpCaseMixin):
    """Verify that all three display policies persist until explicitly changed by an admin."""

    def test_error_policy_persists_across_multiple_unknown_device_polls(self):
        """The error policy should continue returning 202 for every unknown device poll."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)

        for iteration_index in range(3):
            response = self.url_open(
                "/api/display",
                headers=self._display_unknown_headers(self.UNKNOWN_DEVICE_TOKEN),
            )
            payload = self._response_json(response)

            self.assertEqual(self._response_status(response), 200)
            self.assertEqual(payload, {"status": 202})

        self.assertEqual(self._get_display_policy(), DISPLAY_POLICY_ERROR)

    def test_auto_accept_policy_persists_and_accepts_every_new_unknown_device(self):
        """The auto-accept policy should accept every unknown device until manually changed."""
        self._set_display_policy(DISPLAY_POLICY_AUTO_ACCEPT)

        response_a = self.url_open(
            "/api/display",
            headers=self._display_unknown_headers(self.UNKNOWN_DEVICE_TOKEN),
        )
        payload_a = self._response_json(response_a)

        self.assertEqual(self._response_status(response_a), 200)
        self.assertEqual(payload_a["status"], 0)

        device_a = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", self.UNKNOWN_MAC_ADDRESS)],
            limit=1,
        )
        self.assertTrue(device_a)
        self.assertEqual(device_a.approval_state, APPROVAL_STATE_ACCEPTED)

        self.assertEqual(self._get_display_policy(), DISPLAY_POLICY_AUTO_ACCEPT)

        second_mac = "AA:BB:CC:DD:EE:11"
        second_token = "second-unknown-token"

        response_b = self.url_open(
            "/api/display",
            headers=self._display_headers(second_token, second_mac),
        )
        payload_b = self._response_json(response_b)

        self.assertEqual(self._response_status(response_b), 200)
        self.assertEqual(payload_b["status"], 0)

        device_b = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", second_mac)],
            limit=1,
        )
        self.assertTrue(device_b)
        self.assertEqual(device_b.approval_state, APPROVAL_STATE_ACCEPTED)

        self.assertEqual(self._get_display_policy(), DISPLAY_POLICY_AUTO_ACCEPT)

    def test_factory_reset_policy_persists_and_resets_every_unknown_device(self):
        """The factory-reset policy should return 500 for every unknown device until changed."""
        self._set_display_policy(DISPLAY_POLICY_FACTORY_RESET)

        test_cases = [
            ("AA:BB:CC:DD:EE:11", "token-one"),
            ("AA:BB:CC:DD:EE:22", "token-two"),
            ("AA:BB:CC:DD:EE:33", "token-three"),
        ]

        for mac_address, token in test_cases:
            response = self.url_open(
                "/api/display",
                headers=self._display_headers(token, mac_address),
            )
            payload = self._response_json(response)

            self.assertEqual(self._response_status(response), 200)
            self.assertEqual(payload, {"status": 500})

        self.assertEqual(self._get_display_policy(), DISPLAY_POLICY_FACTORY_RESET)

    def test_policy_change_takes_effect_immediately_on_next_poll(self):
        """Changing the policy mid-session must take effect on the very next poll."""
        self._set_display_policy(DISPLAY_POLICY_ERROR)

        first_response = self.url_open(
            "/api/display",
            headers=self._display_unknown_headers(self.UNKNOWN_DEVICE_TOKEN),
        )
        first_payload = self._response_json(first_response)

        self.assertEqual(first_payload, {"status": 202})
        self.assertEqual(self._get_display_policy(), DISPLAY_POLICY_ERROR)

        self._set_display_policy(DISPLAY_POLICY_FACTORY_RESET)

        second_response = self.url_open(
            "/api/display",
            headers=self._display_unknown_headers(self.UNKNOWN_DEVICE_TOKEN),
        )
        second_payload = self._response_json(second_response)

        self.assertEqual(second_payload, {"status": 500})
        self.assertEqual(self._get_display_policy(), DISPLAY_POLICY_FACTORY_RESET)

        self._set_display_policy(DISPLAY_POLICY_ERROR)

        third_response = self.url_open(
            "/api/display",
            headers=self._display_unknown_headers(self.UNKNOWN_DEVICE_TOKEN),
        )
        third_payload = self._response_json(third_response)

        self.assertEqual(third_payload, {"status": 202})
        self.assertEqual(self._get_display_policy(), DISPLAY_POLICY_ERROR)
