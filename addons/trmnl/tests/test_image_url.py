"""Tests for device-reachable URL detection, image URL generation, and warning logic."""

from __future__ import annotations

import base64

from odoo.tests import TransactionCase, tagged

from odoo.addons.trmnl.models.trmnl_device import client_can_reach_host


@tagged("-at_install", "post_install")
class TestDeviceReachableUrl(TransactionCase):
    """_is_device_reachable_base_url: LAN IPs accepted, loopback rejected."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Profile = cls.env["trmnl.profile"]

    def _ok(self, url):
        return self.Profile._is_device_reachable_base_url(url)

    def test_lan_192_168_accepted(self):
        self.assertTrue(self._ok("http://192.168.1.127:8069"))

    def test_lan_10_x_accepted(self):
        self.assertTrue(self._ok("http://10.0.0.5:8069"))

    def test_lan_172_20_accepted(self):
        """172.20.x.x is a common corporate LAN range — must not be blocked."""
        self.assertTrue(self._ok("http://172.20.1.5:8069"))

    def test_lan_172_16_accepted(self):
        self.assertTrue(self._ok("http://172.16.0.10:8069"))

    def test_localhost_rejected(self):
        self.assertFalse(self._ok("http://localhost:8069"))

    def test_127_0_0_1_rejected(self):
        self.assertFalse(self._ok("http://127.0.0.1:8069"))

    def test_0_0_0_0_rejected(self):
        self.assertFalse(self._ok("http://0.0.0.0:8069"))

    def test_ipv6_loopback_rejected(self):
        self.assertFalse(self._ok("http://[::1]:8069"))

    def test_libvirt_virbr0_rejected(self):
        """192.168.122.x is the libvirt KVM virbr0 bridge — VM-internal."""
        self.assertFalse(self._ok("http://192.168.122.1:8069"))

    def test_empty_url_rejected(self):
        self.assertFalse(self._ok(""))


@tagged("-at_install", "post_install")
class TestClientCanReachHost(TransactionCase):
    """LAN reachability heuristic used during /api/display polls."""

    def test_same_192_168_subnet(self):
        self.assertTrue(client_can_reach_host("192.168.1.239", "192.168.1.127"))

    def test_different_private_networks(self):
        self.assertFalse(client_can_reach_host("192.168.1.239", "10.55.200.220"))

    def test_hostname_treated_as_reachable(self):
        self.assertTrue(client_can_reach_host("192.168.1.239", "odoo.local"))


@tagged("-at_install", "post_install")
class TestImageUrlGeneration(TransactionCase):
    """_get_display_image_url resolves the correct base URL for the device."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._device = cls.env["trmnl.device"].sudo().create({
            "mac_address": "AA:BB:CC:DD:EE:11",
            "approval_state": "accepted",
            "registration_source": "setup",
        })
        cls._partner_model = cls.env["ir.model"].sudo().search(
            [("model", "=", "res.partner")], limit=1
        )

    def _profile(self):
        p = self.env["trmnl.profile"].sudo().create({
            "name": "URL test profile",
            "device_id": self._device.id,
            "app_model_id": self._partner_model.id,
            "trmnl_layout": "list",
            "display_limit": 1,
            "filter_preset": "none",
        })
        # Write a minimal fake preview so _get_display_image_url doesn't bail early.
        p.write({"preview_image": base64.b64encode(b"\x89PNG"), "preview_generated_at": "2026-01-01 00:00:00"})
        return p

    def _set_params(self, public_base_url="", web_base_url=""):
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("trmnl.public_base_url", public_base_url)
        params.set_param("web.base.url", web_base_url)

    # ------------------------------------------------------------------

    def test_web_base_url_lan_is_used(self):
        """web.base.url set to a LAN IP is used without needing trmnl.public_base_url."""
        self._set_params(web_base_url="http://192.168.1.127:8069")
        profile = self._profile()
        url = profile._get_display_image_url()
        self.assertIsNotNone(url)
        self.assertIn("192.168.1.127", url)
        self.assertIn(f"/api/profile/image/{profile.id}", url)
        self.assertIn("?v=", url, "device URL must cache-bust when PNG bytes change")

    def test_web_base_url_localhost_is_rejected(self):
        """web.base.url=localhost yields no URL (device cannot reach it)."""
        self._set_params(web_base_url="http://localhost:8069")
        profile = self._profile()
        self.assertFalse(profile._get_display_image_url())

    def test_web_base_url_127_is_rejected(self):
        """web.base.url=127.0.0.1 yields no URL."""
        self._set_params(web_base_url="http://127.0.0.1:8069")
        profile = self._profile()
        self.assertFalse(profile._get_display_image_url())

    def test_public_base_url_overrides_web_base_url(self):
        """trmnl.public_base_url takes priority over web.base.url (no poll context)."""
        self._set_params(
            public_base_url="http://10.0.0.99:8069",
            web_base_url="http://192.168.1.127:8069",
        )
        profile = self._profile()
        url = profile._get_display_image_url()
        self.assertIn("10.0.0.99", url)
        self.assertNotIn("192.168.1.127", url)

    def test_poll_context_prefers_same_lan_over_stale_public_base_url(self):
        """Device on 192.168.x must not get image URLs on an unreachable 10.x host."""
        self._set_params(
            public_base_url="http://10.55.200.220:8069",
            web_base_url="http://192.168.1.127:8069",
        )
        profile = self._profile()
        url = profile.with_context(
            trmnl_poll_base_url="http://10.55.200.220:8069",
            trmnl_client_ip="192.168.1.239",
        )._get_display_image_url()
        self.assertIn("192.168.1.127", url)
        self.assertNotIn("10.55.200.220", url)

    def test_poll_host_used_when_on_same_lan_as_device(self):
        self._set_params(
            public_base_url="http://10.55.200.220:8069",
            web_base_url="http://192.168.1.127:8069",
        )
        profile = self._profile()
        url = profile.with_context(
            trmnl_poll_base_url="http://192.168.1.127:8069",
            trmnl_client_ip="192.168.1.239",
        )._get_display_image_url()
        self.assertIn("192.168.1.127", url)

    def test_sync_public_base_url_fixes_stale_value_on_poll(self):
        self._set_params(
            public_base_url="http://10.55.200.220:8069",
            web_base_url="http://192.168.1.127:8069",
        )
        self.env["trmnl.device"]._sync_public_base_url_from_poll(
            "http://10.55.200.220:8069",
            "192.168.1.239",
        )
        synced = self.env["ir.config_parameter"].sudo().get_param("trmnl.public_base_url")
        self.assertEqual(synced, "http://192.168.1.127:8069")

    # ------------------------------------------------------------------

    def test_no_warning_when_web_base_url_is_lan(self):
        """url_warning is empty when web.base.url is a device-reachable LAN address."""
        self._set_params(web_base_url="http://192.168.1.127:8069")
        profile = self._profile()
        profile._compute_url_warning()
        self.assertFalse(profile.url_warning)

    def test_warning_when_both_urls_unusable(self):
        """url_warning appears when web.base.url is loopback and public_base_url is unset."""
        self._set_params(web_base_url="http://localhost:8069")
        profile = self._profile()
        profile._compute_url_warning()
        self.assertTrue(profile.url_warning)
        self.assertIn("192.168.1", profile.url_warning)

    def test_no_warning_when_public_base_url_set(self):
        """url_warning is empty when trmnl.public_base_url is configured."""
        self._set_params(
            public_base_url="http://10.0.0.1:8069",
            web_base_url="http://localhost:8069",
        )
        profile = self._profile()
        profile._compute_url_warning()
        self.assertFalse(profile.url_warning)
