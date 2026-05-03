"""Tests for the TRMNL ``/api/setup`` endpoint."""

from odoo.tests import HttpCase, tagged

from .test_api_common import APPROVAL_STATE_ACCEPTED, TrmnlApiHttpCaseMixin


@tagged("-at_install", "post_install")
class TestTrmnlSetupApi(HttpCase, TrmnlApiHttpCaseMixin):
    """Verify the ``/api/setup`` endpoint behavior."""

    def test_api_setup_success_returns_only_expected_keys(self):
        """A valid setup call should return only the required keys."""
        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]
        api_token = setup_context["api_token"]
        setup_payload = setup_context["payload"]

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
        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]
        api_token = setup_context["api_token"]

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
        self.assertEqual(stored_device.approval_state, APPROVAL_STATE_ACCEPTED)
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

    def test_api_setup_with_reset_pending_reregisters_device(self):
        """A setup call from a MAC with reset_pending True should clear the flag and issue a fresh registration."""
        setup_context = self._register_device_through_setup()
        registered_device = setup_context["device"]
        old_device_id = registered_device.id
        old_token = setup_context["api_token"]

        registered_device.with_context(trmnl_allow_identity_update=True).write(
            {"reset_pending": True}
        )

        second_setup_response = self.url_open(
            "/api/setup",
            headers=self._setup_headers(),
        )
        setup_payload = self._response_json(second_setup_response)

        self.assertEqual(self._response_status(second_setup_response), 200)
        self.assertEqual(setup_payload["status"], 200)
        self.assertTrue(setup_payload["api_key"])
        self.assertNotEqual(setup_payload["api_key"], old_token)

        found_device = self.env["trmnl.device"].sudo().search(
            [("mac_address", "=", self.DEVICE_MAC_ADDRESS)],
            limit=1,
        )

        self.assertTrue(found_device)
        self.assertNotEqual(found_device.id, old_device_id)
        self.assertFalse(found_device.reset_pending)
        self.assertEqual(found_device.approval_state, APPROVAL_STATE_ACCEPTED)
        self.assertTrue(found_device._verify_api_token(setup_payload["api_key"]))
