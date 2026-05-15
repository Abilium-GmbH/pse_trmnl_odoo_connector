"""TRMNL profile rendering orchestration — Odoo-native model layer.

Architecture
------------
This module is one half of the two-layer rendering design:

**Layer 1 — Odoo model (this file, TrmnlProfileRenderMixin)**

  Extends ``trmnl.profile`` and is therefore a first-class Odoo model.
  All Odoo concerns live here: ORM record access, ``sudo()`` context,
  device-dimension lookup, domain application, calendar record loading,
  ORM-record → plain-dict conversion, PNG compositing, persistence via
  ``write()``, and auto-refresh timing.

**Layer 2 — Pure Python drawing utilities (addon root level)**

  ``trmnl_preview``, ``trmnl_calendar_preview``,
  ``trmnl_calendar_week_preview``, ``trmnl_display_canvas``.

  These are stateless functions that accept plain Python data structures
  (lists of strings, dicts) and return PNG bytes.  They carry no Odoo
  imports and have no side-effects.  This isolation keeps PIL rendering
  logic independently testable and free of ORM coupling.

Call flow on a device poll
--------------------------
::

  /api/display  (device_display_controller.py)
    ↓ device.build_display_response()          trmnl_device_display
        ↓ profile._is_auto_refresh_due()       here — timing check
        ↓ profile._render_and_store_preview()  here — full pipeline
            ↓ _load_records()                  trmnl_profile — generic ORM search
            ↓ _load_calendar_records()         here  — calendar-specific ORM search
            ↓ _prepare_calendar_data()         here  — ORM records → plain dicts
            ↓ _dispatch_renderer()             here  — selects Layer 2 renderer
                ↓ render_list_preview()        Layer 2 (pure Python)
                ↓ render_calendar_preview()    Layer 2 (pure Python)
            ↓ _finalize_display_image()        here  — composites footer band
        ↓ profile._get_display_image_url()     trmnl_profile — URL computation
"""
from __future__ import annotations

import base64
import io
import logging
from calendar import monthrange
from datetime import date, timedelta, timezone
from zoneinfo import ZoneInfo

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain

_logger = logging.getLogger(__name__)


class TrmnlProfileRenderMixin(models.Model):
    """Odoo-native rendering orchestration layer for TRMNL profiles.

    Extends ``trmnl.profile`` using the same ``_inherit`` mixin pattern used
    throughout the device model (lifecycle, security, telemetry, display, UI).
    Methods defined here are therefore fully part of the ``trmnl.profile`` ORM
    model: they can call ``self.env``, respect access rules, and use ``write()``
    to persist results.

    Responsibilities
    ----------------
    - Render-interval timing (``_is_auto_refresh_due``).
    - Calendar-specific ORM queries (``_load_calendar_*``).
    - ORM-record → plain-Python-dict conversion (``_prepare_calendar_*``).
    - Renderer selection and dispatch (``_dispatch_renderer``).
    - Content-strip + footer compositing (``_finalize_display_image``).
    - Top-level pipeline entry points (``_render_and_store_preview``,
      ``action_render_preview``).

    The pure-Python renderer modules are **not** imported at module level to
    avoid potential circular references during Odoo addon loading; they are
    imported lazily inside the methods that call them.
    """

    _inherit = "trmnl.profile"

    # ------------------------------------------------------------------
    # render timing
    # ------------------------------------------------------------------

    def _is_auto_refresh_due(self):
        """Return True if the profile preview should be re-rendered now.

        True when no preview has ever been generated (``preview_generated_at``
        is unset).  Otherwise True when the elapsed time since the last render
        exceeds the configured interval.  Zero or negative interval defaults to
        10 minutes.
        """
        self.ensure_one()
        if not self.preview_generated_at:
            return True
        interval = self.auto_refresh_interval_minutes
        if not interval or interval <= 0:
            interval = 10
        threshold = self.preview_generated_at + timedelta(minutes=interval)
        now = fields.Datetime.now()
        due = now >= threshold
        _logger.debug(
            "TRMNL render-interval: profile id=%s generated_at=%s interval=%smin "
            "threshold=%s now=%s due=%s",
            self.id, self.preview_generated_at, interval, threshold, now, due,
        )
        return due

    # ------------------------------------------------------------------
    # calendar data extraction (ORM records → plain Python dicts)
    # ------------------------------------------------------------------

    def _prepare_calendar_data(self, records) -> list[dict]:
        """Extract plain event dicts from calendar.event ORM records.

        All ORM access is isolated in this method so the Layer 2 renderer
        receives only plain Python dicts with no ORM references.
        Times are in the server timezone (UTC).
        """
        events = []
        for rec in records:
            try:
                start = rec.start
                if not start:
                    continue
                start_date = start.date() if hasattr(start, "date") and callable(start.date) else start
                time_str = start.strftime("%H:%M") if hasattr(start, "hour") else ""
                events.append({
                    "title":    rec.display_name or "",
                    "start":    start_date,
                    "time_str": time_str,
                })
            except Exception:
                pass
        return events

    def _prepare_calendar_week_data(self, records) -> list[dict]:
        """Extract timed event dicts from calendar.event ORM records for week view.

        All-day events are excluded.  Missing stop defaults to start + 1 hour.
        Times are in server timezone (UTC); no conversion applied.
        All ORM access is isolated here so the Layer 2 renderer receives only
        plain Python dicts.
        """
        events = []
        for rec in records:
            try:
                start = rec.start
                if not start:
                    continue
                if getattr(rec, "allday", False):
                    continue
                stop = rec.stop or (start + timedelta(hours=1))
                events.append({
                    "title":          rec.display_name or "",
                    "start_datetime": start,
                    "end_datetime":   stop,
                })
            except Exception:
                pass
        return events

    def _resolve_calendar_date(self) -> tuple[int, int]:
        """Return (year, month) for month view based on reference settings."""
        if self.calendar_reference_mode == "custom" and self.calendar_reference_date:
            ref = self.calendar_reference_date
            return ref.year, ref.month
        today = date.today()
        return today.year, today.month

    def _resolve_calendar_week_start(self) -> date:
        """Return the Monday of the target week based on reference settings."""
        if self.calendar_reference_mode == "custom" and self.calendar_reference_date:
            ref = self.calendar_reference_date
            return ref - timedelta(days=ref.weekday())
        today = date.today()
        return today - timedelta(days=today.weekday())

    # ------------------------------------------------------------------
    # calendar ORM loading
    # ------------------------------------------------------------------

    def _load_calendar_records(self, year: int, month: int):
        """Load calendar.event records for the displayed month.

        Bypasses filter_preset date ranges (the month window overrides them)
        but still respects my_records so personal calendars work correctly.
        Applies filter_domain on top.
        """
        _, last_day = monthrange(year, month)
        month_start = date(year, month, 1)
        month_end   = date(year, month, last_day)
        domain = [("start", ">=", month_start), ("start", "<=", month_end)]

        if self.filter_preset == "my_records":
            domain.append(("user_id", "=", self.env.uid))

        raw_custom = (self.filter_domain or "").strip()
        if raw_custom and raw_custom != "[]":
            try:
                custom_domain = self._eval_filter_domain(raw_custom)
                if custom_domain:
                    domain = list(Domain.AND([domain, custom_domain]))
            except Exception as exc:
                raise UserError(
                    _("Custom Domain is invalid and could not be applied: %s") % exc
                ) from exc

        limit = self.display_limit or 200
        env = self.env["calendar.event"].sudo()
        if self.include_archived:
            env = env.with_context(active_test=False)
        return env.search(domain, limit=limit, order="start asc")

    def _load_calendar_week_records(self, week_start: date):
        """Load calendar.event records for the full Mon–Sun week window.

        Always loads the full 7 days regardless of week_mode so the renderer
        can decide which columns to draw.  Respects my_records filter and
        applies filter_domain on top.
        """
        week_end = week_start + timedelta(days=6)
        domain = [("start", ">=", week_start), ("start", "<=", week_end)]
        if self.filter_preset == "my_records":
            domain.append(("user_id", "=", self.env.uid))

        raw_custom = (self.filter_domain or "").strip()
        if raw_custom and raw_custom != "[]":
            try:
                custom_domain = self._eval_filter_domain(raw_custom)
                if custom_domain:
                    domain = list(Domain.AND([domain, custom_domain]))
            except Exception as exc:
                raise UserError(
                    _("Custom Domain is invalid and could not be applied: %s") % exc
                ) from exc

        limit = self.display_limit or 200
        env = self.env["calendar.event"].sudo()
        if self.include_archived:
            env = env.with_context(active_test=False)
        return env.search(domain, limit=limit, order="start asc")

    # ------------------------------------------------------------------
    # renderer dispatch  (Odoo model layer → pure Python drawing layer)
    # ------------------------------------------------------------------

    def _dispatch_renderer(
        self,
        model_name,
        field_names,
        field_labels,
        records,
        *,
        width=None,
        content_height=None,
    ) -> bytes:
        """Select and call the correct Layer 2 renderer; fall back to list on failure.

        This method is the **explicit boundary** between the Odoo model layer
        and the pure-Python drawing layer.  All arguments passed to the renderer
        are plain Python values — strings, lists of strings, dicts.  No ORM
        records cross this call.  The imported renderer functions are stateless
        PIL utilities that return PNG bytes with no Odoo dependencies.
        """
        if self.trmnl_layout == "calendar" and model_name == "calendar.event":
            try:
                if self.calendar_view_mode == "week":
                    week_start = self._resolve_calendar_week_start()
                    week_events = self._prepare_calendar_week_data(
                        self._load_calendar_week_records(week_start)
                    )
                    from odoo.addons.trmnl.trmnl_calendar_week_preview import (
                        render_calendar_week_preview,
                    )
                    return render_calendar_week_preview(
                        week_events, week_start, self.calendar_week_mode,
                        width=width, content_height=content_height,
                    )
                else:
                    year, month = self._resolve_calendar_date()
                    events = self._prepare_calendar_data(
                        self._load_calendar_records(year, month)
                    )
                    from odoo.addons.trmnl.trmnl_calendar_preview import render_calendar_preview
                    return render_calendar_preview(
                        events, year, month,
                        width=width, content_height=content_height,
                    )
            except UserError:
                raise
            except Exception as exc:
                _logger.warning(
                    "TRMNL calendar renderer failed for profile id=%s — falling back to list: %s",
                    self.id, exc, exc_info=True,
                )

        rows = [
            [self._extract_field_value(rec, fname) for fname in field_names]
            for rec in records
        ]
        from odoo.addons.trmnl.trmnl_preview import render_list_preview
        return render_list_preview(rows, field_labels, width=width, content_height=content_height)

    # ------------------------------------------------------------------
    # display footer compositing
    # ------------------------------------------------------------------

    @staticmethod
    def _format_poll_timestamp(device_label, poll_at):
        """Return the footer label string in Europe/Zurich local time."""
        zurich = ZoneInfo("Europe/Zurich")
        local_dt = poll_at.replace(tzinfo=timezone.utc).astimezone(zurich)
        return f"{device_label} · Last poll: {local_dt.strftime('%Y-%m-%d %H:%M')}"

    def _get_footer_device_label(self):
        """Human-readable device label for the footer.

        Priority: admin ``device_name``, then ``friendly_id``, then
        ``mac_address``.
        """
        self.ensure_one()
        device = self.device_id
        name = (device.device_name or "").strip()
        if name:
            return name
        if device.friendly_id:
            return device.friendly_id
        return device.mac_address or "TRMNL"

    def _finalize_display_image(self, png_bytes):
        """Paste content-sized PNG onto the device frame and draw the poll footer strip.

        Layout renderers produce ``(device_w, content_h)`` bytes.  This method
        composites them into a full device frame with a separator line and
        optional centered poll metadata in the footer band.

        Uses device telemetry ``display_width``/``display_height`` when
        available, falling back to the canvas constants (800×480).
        """
        self.ensure_one()
        from odoo.addons.trmnl.trmnl_display_canvas import (
            DISPLAY_HEIGHT,
            DISPLAY_WIDTH,
            FOOTER_BAND_FILL,
            FOOTER_BAND_HEIGHT,
            FOOTER_SEPARATOR_GRAY,
            draw_poll_footer_strip,
            load_font as _lf,
            text_width as _tw,
        )

        dev = self.device_id
        device_w = (dev.display_width if dev and dev.display_width > 0 else None) or DISPLAY_WIDTH
        device_h = (dev.display_height if dev and dev.display_height > 0 else None) or DISPLAY_HEIGHT
        content_h = device_h - FOOTER_BAND_HEIGHT

        try:
            from PIL import Image, ImageDraw
        except ImportError:
            return png_bytes

        try:
            content = Image.open(io.BytesIO(png_bytes)).convert("L")
        except Exception:
            _logger.debug(
                "TRMNL profile id=%s: invalid content PNG for finalize", self.id, exc_info=True
            )
            return png_bytes

        cw, ch = content.size
        if cw != device_w:
            _logger.debug(
                "TRMNL profile id=%s: unexpected content width %s (expected %s)",
                self.id, cw, device_w,
            )
            return png_bytes
        if ch == device_h:
            content = content.crop((0, 0, device_w, content_h))
            ch = content_h
        elif ch != content_h:
            _logger.debug(
                "TRMNL profile id=%s: unexpected content height %s (expected %s)",
                self.id, ch, content_h,
            )
            return png_bytes

        out = Image.new("L", (device_w, device_h), 255)
        out.paste(content, (0, 0))
        draw = ImageDraw.Draw(out)

        poll_at = self.device_id.last_poll_at
        label = None
        font = None
        if poll_at:
            font = _lf(11)
            label = self._format_poll_timestamp(self._get_footer_device_label(), poll_at)
            max_text_w = device_w - 16
            while len(label) > 8 and _tw(draw, label + "…", font) > max_text_w:
                label = label[:-1]
            if _tw(draw, label, font) > max_text_w:
                label = (label[: max(4, len(label) - 4)] + "…") if label else ""

        separator_y = content_h
        try:
            draw_poll_footer_strip(draw, label=label, font=font, width=device_w, display_height=device_h)
            buf = io.BytesIO()
            out.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as exc:
            _logger.warning(
                "TRMNL profile id=%s: finalize footer/save failed (%s) — "
                "returning full frame with content + empty footer band",
                self.id,
                exc,
                exc_info=True,
            )
            out2 = Image.new("L", (device_w, device_h), 255)
            out2.paste(content, (0, 0))
            d2 = ImageDraw.Draw(out2)
            d2.line(
                [(0, separator_y), (device_w - 1, separator_y)],
                fill=FOOTER_SEPARATOR_GRAY,
                width=1,
            )
            d2.rectangle(
                [0, separator_y + 1, device_w - 1, device_h - 1],
                fill=FOOTER_BAND_FILL,
            )
            buf2 = io.BytesIO()
            out2.save(buf2, format="PNG")
            return buf2.getvalue()

    # ------------------------------------------------------------------
    # top-level render entry points
    # ------------------------------------------------------------------

    def action_render_preview(self):
        """Trigger a manual preview render from the profile form view."""
        self.ensure_one()
        if not self.app_model_id:
            raise UserError(_("Select an Odoo Model before rendering a preview."))
        self._render_and_store_preview()

        last_poll = self.device_id.last_display_at
        rate = self.device_id.desired_refresh_rate or 1800

        if last_poll:
            next_poll = last_poll + timedelta(seconds=rate)
            msg = (
                f"Preview updated. "
                f"Last poll: {last_poll.strftime('%Y-%m-%d %H:%M')} UTC · "
                f"Next expected poll: {next_poll.strftime('%Y-%m-%d %H:%M')} UTC."
            )
        else:
            msg = _(
                "Preview updated. "
                "The device has not polled yet — power-cycle it to trigger the first poll."
            )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Preview Updated"),
                "message": msg,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def _render_and_store_preview(self):
        """Run the full rendering pipeline and persist the result.

        Orchestration steps:

        1. Resolve field names/labels from ``display_field_ids``.
        2. Read device dimensions (falls back to 800×480 if unreported).
        3. Load ORM records via ``_load_records`` (generic) or the calendar
           loader inside ``_dispatch_renderer``.
        4. Dispatch to the correct Layer 2 renderer via ``_dispatch_renderer``.
        5. Composite the footer band via ``_finalize_display_image``.
        6. Persist PNG bytes and update ``preview_generated_at``.

        Raises ``UserError`` on configuration errors (missing model, bad domain).
        """
        self.ensure_one()

        if not self.app_model_id:
            raise UserError(_("Select an Odoo Model before rendering a preview."))

        model_name = self.app_model_id.model

        if model_name not in self.env:
            raise UserError(
                _("Model '%s' is not available in this environment.") % model_name
            )

        available = self._get_available_view_types()
        if available and self.trmnl_layout not in available:
            label_map = {"list": "List", "kanban": "Kanban", "calendar": "Calendar"}
            label = label_map.get(self.trmnl_layout, self.trmnl_layout)
            raise UserError(
                _("View Type '%s' is not available for the selected model. "
                  "Please update the profile and choose an available view type.")
                % label
            )

        valid_display_fields = self.display_field_ids.filtered(
            lambda f: f.model == model_name
        )
        if valid_display_fields:
            field_names = valid_display_fields.mapped("name")
            field_labels = valid_display_fields.mapped("field_description")
        else:
            field_names = ["display_name"]
            field_labels = [_("Name")]

        from odoo.addons.trmnl.trmnl_display_canvas import (
            DISPLAY_HEIGHT as _DEFAULT_H,
            DISPLAY_WIDTH as _DEFAULT_W,
            FOOTER_BAND_HEIGHT as _FOOTER_H,
        )
        dev = self.device_id
        device_w = (dev.display_width if dev and dev.display_width > 0 else None) or _DEFAULT_W
        device_h = (dev.display_height if dev and dev.display_height > 0 else None) or _DEFAULT_H
        content_h = device_h - _FOOTER_H

        records = self._load_records(model_name, field_names)
        png_bytes = self._dispatch_renderer(
            model_name, field_names, field_labels, records,
            width=device_w, content_height=content_h,
        )
        png_bytes = self._finalize_display_image(png_bytes)

        self.write({
            "preview_image": base64.b64encode(png_bytes),
            "preview_generated_at": fields.Datetime.now(),
        })
