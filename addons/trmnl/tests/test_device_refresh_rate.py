"""Unit tests for TRMNL device refresh rate configuration.

These tests exercise the model layer directly (no HTTP stack) and cover:

- ``desired_refresh_rate_value`` / ``desired_refresh_rate_unit`` compute logic
  (i.e. what the UI *displays* for a given stored second value).
- The inverse direction: writing a value/unit pair through the UI fields
  and asserting the correct second count is persisted.
- The ``_check_desired_refresh_rate_bounds`` constraint for values below,
  at, and above each boundary.
- Round-trip integrity: compute → inverse → compute produces a stable result.
"""

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.trmnl.models.trmnl_device import (
    DEFAULT_REFRESH_RATE,
    REFRESH_RATE_MAX_SECONDS,
    REFRESH_RATE_MIN_SECONDS,
    REFRESH_RATE_UNIT_SECONDS,
)


@tagged("-at_install", "post_install")
class TestDeviceRefreshRateCompute(TransactionCase):
    """Verify that ``desired_refresh_rate`` is decomposed correctly for the UI.

    Each test stores a raw second value and asserts the expected
    (value, unit) pair that the compute method produces.
    """

    def _create_device(self, desired_refresh_rate):
        """Return a new device record with the given desired refresh rate."""
        return self.env["trmnl.device"].sudo().create({
            "mac_address": f"AA:BB:CC:DD:EE:{self._mac_suffix()}",
            "desired_refresh_rate": desired_refresh_rate,
        })

    _mac_counter = 0

    def _mac_suffix(self):
        """Return a unique two-hex-digit suffix for test MAC addresses."""
        TestDeviceRefreshRateCompute._mac_counter += 1
        return f"{TestDeviceRefreshRateCompute._mac_counter:02X}"

    # ------------------------------------------------------------------
    # minutes
    # ------------------------------------------------------------------

    def test_compute_displays_minutes_for_non_round_values(self):
        """Values that are only divisible by minutes should display as minutes."""
        device = self._create_device(300)  # 5 minutes, not divisible by 3600
        self.assertEqual(device.desired_refresh_rate_value, 5)
        self.assertEqual(device.desired_refresh_rate_unit, "minutes")

    def test_compute_displays_minutes_for_default_rate(self):
        """The default rate (1800 seconds = 30 minutes) should display as 30 minutes."""
        device = self._create_device(DEFAULT_REFRESH_RATE)
        self.assertEqual(device.desired_refresh_rate_value, 30)
        self.assertEqual(device.desired_refresh_rate_unit, "minutes")

    def test_compute_displays_minutes_for_minimum_rate(self):
        """The minimum allowed rate (60 seconds = 1 minutes) should display as 1 minute."""
        device = self._create_device(REFRESH_RATE_MIN_SECONDS)
        self.assertEqual(device.desired_refresh_rate_value, 1)
        self.assertEqual(device.desired_refresh_rate_unit, "minutes")

    # ------------------------------------------------------------------
    # hours
    # ------------------------------------------------------------------

    def test_compute_displays_hours_for_exact_hour(self):
        """3600 seconds should display as 1 hour."""
        device = self._create_device(3_600)
        self.assertEqual(device.desired_refresh_rate_value, 1)
        self.assertEqual(device.desired_refresh_rate_unit, "hours")

    def test_compute_displays_hours_for_multiple_hours(self):
        """7200 seconds should display as 2 hours."""
        device = self._create_device(7_200)
        self.assertEqual(device.desired_refresh_rate_value, 2)
        self.assertEqual(device.desired_refresh_rate_unit, "hours")

    # ------------------------------------------------------------------
    # days
    # ------------------------------------------------------------------

    def test_compute_displays_days_for_exact_day(self):
        """86400 seconds should display as 1 day."""
        device = self._create_device(86_400)
        self.assertEqual(device.desired_refresh_rate_value, 1)
        self.assertEqual(device.desired_refresh_rate_unit, "days")

    def test_compute_displays_days_for_multiple_days(self):
        """172800 seconds should display as 2 days."""
        device = self._create_device(172_800)
        self.assertEqual(device.desired_refresh_rate_value, 2)
        self.assertEqual(device.desired_refresh_rate_unit, "days")
    
    # ------------------------------------------------------------------
    # weeks
    # ------------------------------------------------------------------

    def test_compute_displays_weeks_for_exact_week(self):
        """604800 seconds (7 days) should display as 1 week."""
        device = self._create_device(REFRESH_RATE_UNIT_SECONDS["weeks"])
        self.assertEqual(device.desired_refresh_rate_value, 1)
        self.assertEqual(device.desired_refresh_rate_unit, "weeks")

    def test_compute_displays_weeks_for_multiple_weeks(self):
        """3 weeks should display as 3 weeks, not as days."""
        device = self._create_device(3 * REFRESH_RATE_UNIT_SECONDS["weeks"])
        self.assertEqual(device.desired_refresh_rate_value, 3)
        self.assertEqual(device.desired_refresh_rate_unit, "weeks")
    
    # ------------------------------------------------------------------
    # months
    # ------------------------------------------------------------------

    def test_compute_displays_months_for_exact_month(self):
        """2592000 seconds (30 days) should display as 1 month."""
        device = self._create_device(REFRESH_RATE_UNIT_SECONDS["months"])
        self.assertEqual(device.desired_refresh_rate_value, 1)
        self.assertEqual(device.desired_refresh_rate_unit, "months")

    def test_compute_displays_months_for_multiple_months(self):
        """6 months (6 * 2592000 seconds) should display as 6 months, not as days."""
        device = self._create_device(6 * REFRESH_RATE_UNIT_SECONDS["months"])
        self.assertEqual(device.desired_refresh_rate_value, 6)
        self.assertEqual(device.desired_refresh_rate_unit, "months")

    # ------------------------------------------------------------------
    # years
    # ------------------------------------------------------------------

    def test_compute_displays_years_for_exact_year(self):
        """31536000 seconds should display as 1 year."""
        device = self._create_device(REFRESH_RATE_UNIT_SECONDS["years"])
        self.assertEqual(device.desired_refresh_rate_value, 1)
        self.assertEqual(device.desired_refresh_rate_unit, "years")

    def test_compute_displays_years_for_multiple_years(self):
        """10 years should display as 10 years, not as months."""
        device = self._create_device(10 * REFRESH_RATE_UNIT_SECONDS["years"])
        self.assertEqual(device.desired_refresh_rate_value, 10)
        self.assertEqual(device.desired_refresh_rate_unit, "years")

    def test_compute_years_takes_priority_over_months_for_exact_year_multiples(self):
        """A value that is divisible by both months and years should display as years.

        31536000 seconds is exactly 12.166... months (not a whole number), so in
        practice a year-exact value is never also a whole number of months.
        This test makes the ordering contract explicit regardless.
        """
        year_seconds = REFRESH_RATE_UNIT_SECONDS["years"]
        month_seconds = REFRESH_RATE_UNIT_SECONDS["months"]
        # Confirm the assumption: 1 year is not a whole number of months
        self.assertNotEqual(year_seconds % month_seconds, 0)

        device = self._create_device(year_seconds)
        self.assertEqual(device.desired_refresh_rate_unit, "years")

    def test_compute_displays_years_for_maximum_rate(self):
        """The maximum allowed rate (10 years) should display as 10 years."""
        device = self._create_device(REFRESH_RATE_MAX_SECONDS)
        self.assertEqual(device.desired_refresh_rate_value, 10)
        self.assertEqual(device.desired_refresh_rate_unit, "years")


@tagged("-at_install", "post_install")
class TestDeviceRefreshRateInverse(TransactionCase):
    """Verify that writing via the UI value/unit fields persists the correct seconds.

    The inverse is triggered when ``desired_refresh_rate_value`` or
    ``desired_refresh_rate_unit`` is written; the underlying
    ``desired_refresh_rate`` (seconds) must reflect the product.
    """

    def _create_device_with_unit(self, value, unit):
        """Return a device created via the raw seconds derived from value * unit."""
        unit_seconds = REFRESH_RATE_UNIT_SECONDS[unit]
        return self.env["trmnl.device"].sudo().create({
            "mac_address": f"BB:CC:DD:EE:FF:{self._mac_suffix()}",
            "desired_refresh_rate": value * unit_seconds,
        })

    _mac_counter = 0

    def _mac_suffix(self):
        TestDeviceRefreshRateInverse._mac_counter += 1
        return f"{TestDeviceRefreshRateInverse._mac_counter:02X}"

    def _write_display_fields(self, device, value, unit):
        """Simulate a UI write of both display fields in one operation."""
        device.write({
            "desired_refresh_rate_value": value,
            "desired_refresh_rate_unit": unit,
        })

    def test_inverse_minutes_persists_correct_seconds(self):
        """Writing 45 minutes should persist 2700 seconds."""
        device = self._create_device_with_unit(30, "minutes")
        self._write_display_fields(device, 45, "minutes")
        self.assertEqual(device.desired_refresh_rate, 45 * 60)

    def test_inverse_hours_persists_correct_seconds(self):
        """Writing 3 hours should persist 10800 seconds."""
        device = self._create_device_with_unit(1, "hours")
        self._write_display_fields(device, 3, "hours")
        self.assertEqual(device.desired_refresh_rate, 3 * 3_600)

    def test_inverse_days_persists_correct_seconds(self):
        """Writing 7 days should persist 604800 seconds."""
        device = self._create_device_with_unit(1, "days")
        self._write_display_fields(device, 7, "days")
        self.assertEqual(device.desired_refresh_rate, 7 * 86_400)

    def test_inverse_months_persists_correct_seconds(self):
        """Writing 3 months should persist 7776000 seconds."""
        device = self._create_device_with_unit(1, "months")
        self._write_display_fields(device, 3, "months")
        self.assertEqual(device.desired_refresh_rate, 3 * REFRESH_RATE_UNIT_SECONDS["months"])

    def test_inverse_years_persists_correct_seconds(self):
        """Writing 2 years should persist 63072000 seconds."""
        device = self._create_device_with_unit(1, "years")
        self._write_display_fields(device, 2, "years")
        self.assertEqual(device.desired_refresh_rate, 2 * REFRESH_RATE_UNIT_SECONDS["years"])

    def test_inverse_round_trip_is_stable(self):
        """Compute → inverse → compute should yield the same value and unit."""
        device = self._create_device_with_unit(6, "hours")

        first_value = device.desired_refresh_rate_value
        first_unit = device.desired_refresh_rate_unit

        self._write_display_fields(device, first_value, first_unit)

        self.assertEqual(device.desired_refresh_rate_value, first_value)
        self.assertEqual(device.desired_refresh_rate_unit, first_unit)
        self.assertEqual(device.desired_refresh_rate, 6 * 3_600)


@tagged("-at_install", "post_install")
class TestDeviceRefreshRateBounds(TransactionCase):
    """Verify the ``_check_desired_refresh_rate_bounds`` constraint.

    Tests are grouped into four scenarios:
    - Exactly on the lower boundary (allowed).
    - Below the lower boundary (rejected).
    - Exactly on the upper boundary (allowed).
    - Above the upper boundary (rejected).
    - Representative valid values spanning all units.
    """

    _mac_counter = 0

    def _mac_suffix(self):
        TestDeviceRefreshRateBounds._mac_counter += 1
        return f"{TestDeviceRefreshRateBounds._mac_counter:02X}"

    def _create_device(self, desired_refresh_rate):
        """Attempt to create a device with the given rate; return the record."""
        return self.env["trmnl.device"].sudo().create({
            "mac_address": f"CC:DD:EE:FF:AA:{self._mac_suffix()}",
            "desired_refresh_rate": desired_refresh_rate,
        })

    def _update_device_rate(self, device, desired_refresh_rate):
        """Attempt to write a new rate onto an existing device."""
        device.write({"desired_refresh_rate": desired_refresh_rate})

    # ------------------------------------------------------------------
    # lower boundary
    # ------------------------------------------------------------------

    def test_boundary_lower_exact_is_accepted_on_create(self):
        """Creating a device at exactly the minimum rate should succeed."""
        device = self._create_device(REFRESH_RATE_MIN_SECONDS)
        self.assertEqual(device.desired_refresh_rate, REFRESH_RATE_MIN_SECONDS)

    def test_boundary_lower_exact_is_accepted_on_write(self):
        """Updating to exactly the minimum rate should succeed."""
        device = self._create_device(DEFAULT_REFRESH_RATE)
        self._update_device_rate(device, REFRESH_RATE_MIN_SECONDS)
        self.assertEqual(device.desired_refresh_rate, REFRESH_RATE_MIN_SECONDS)

    def test_boundary_below_lower_is_rejected_on_create(self):
        """Creating a device below the minimum rate should raise ValidationError."""
        with self.assertRaises(ValidationError):
            self._create_device(REFRESH_RATE_MIN_SECONDS - 1)

    def test_boundary_below_lower_is_rejected_on_write(self):
        """Updating below the minimum rate should raise ValidationError."""
        device = self._create_device(DEFAULT_REFRESH_RATE)
        with self.assertRaises(ValidationError):
            self._update_device_rate(device, REFRESH_RATE_MIN_SECONDS - 1)

    def test_boundary_zero_is_rejected(self):
        """Zero seconds is well below the minimum and must be rejected."""
        with self.assertRaises(ValidationError):
            self._create_device(0)

    def test_boundary_negative_is_rejected(self):
        """Negative values must be rejected."""
        with self.assertRaises(ValidationError):
            self._create_device(-1)

    # ------------------------------------------------------------------
    # upper boundary
    # ------------------------------------------------------------------

    def test_boundary_upper_exact_is_accepted_on_create(self):
        """Creating a device at exactly the maximum rate should succeed."""
        device = self._create_device(REFRESH_RATE_MAX_SECONDS)
        self.assertEqual(device.desired_refresh_rate, REFRESH_RATE_MAX_SECONDS)

    def test_boundary_upper_exact_is_accepted_on_write(self):
        """Updating to exactly the maximum rate should succeed."""
        device = self._create_device(DEFAULT_REFRESH_RATE)
        self._update_device_rate(device, REFRESH_RATE_MAX_SECONDS)
        self.assertEqual(device.desired_refresh_rate, REFRESH_RATE_MAX_SECONDS)

    def test_boundary_above_upper_is_rejected_on_create(self):
        """Creating a device above the maximum rate should raise ValidationError."""
        with self.assertRaises(ValidationError):
            self._create_device(REFRESH_RATE_MAX_SECONDS + 1)

    def test_boundary_above_upper_is_rejected_on_write(self):
        """Updating above the maximum rate should raise ValidationError."""
        device = self._create_device(DEFAULT_REFRESH_RATE)
        with self.assertRaises(ValidationError):
            self._update_device_rate(device, REFRESH_RATE_MAX_SECONDS + 1)

    # ------------------------------------------------------------------
    # valid values spanning all units
    # ------------------------------------------------------------------

    def test_valid_rate_in_minutes(self):
        """A typical minute-range rate should be stored without error."""
        device = self._create_device(5 * REFRESH_RATE_UNIT_SECONDS["minutes"])
        self.assertEqual(device.desired_refresh_rate, 300)

    def test_valid_rate_in_hours(self):
        """A typical hour-range rate should be stored without error."""
        device = self._create_device(2 * REFRESH_RATE_UNIT_SECONDS["hours"])
        self.assertEqual(device.desired_refresh_rate, 7_200)

    def test_valid_rate_in_days(self):
        """A typical day-range rate should be stored without error."""
        device = self._create_device(3 * REFRESH_RATE_UNIT_SECONDS["days"])
        self.assertEqual(device.desired_refresh_rate, 259_200)

    def test_valid_rate_in_months(self):
        """A typical month-range rate should be stored without error."""
        device = self._create_device(2 * REFRESH_RATE_UNIT_SECONDS["months"])
        self.assertEqual(device.desired_refresh_rate, 5_184_000)

    def test_valid_rate_in_years(self):
        """A typical year-range rate should be stored without error."""
        device = self._create_device(5 * REFRESH_RATE_UNIT_SECONDS["years"])
        self.assertEqual(device.desired_refresh_rate, 157_680_000)
