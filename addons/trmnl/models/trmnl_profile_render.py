"""TRMNL profile rendering orchestration — Odoo-native model layer.

Architecture
------------
This module sits at the top of a three-part rendering stack:

**Layer 1a — Render orchestration (this file, TrmnlProfileRenderMixin)**

  Extends ``trmnl.profile``. Owns render *timing* (auto-refresh interval,
  staleness, renderer-version checks), renderer *dispatch*, footer
  *compositing*, PNG *persistence* via ``write()``, and the top-level
  pipeline entry points. It calls into the data and drawing layers but
  contains no ORM queries or PIL code of its own.

**Layer 1b — Data loading (trmnl_profile_render_data.TrmnlProfileRenderDataMixin)**

  Also extends ``trmnl.profile``. Owns all ORM access for the renderers:
  calendar record loading, line/graph aggregation via ``read_group``,
  device-dimension lookup, timezone resolution, and ORM-record → plain-dict
  conversion. The dispatcher below consumes its output and never touches the
  ORM directly when drawing.

**Layer 2 — PIL drawing methods (Odoo model layer)**

  ``trmnl_profile_render_list``, ``trmnl_profile_render_calendar``,
  ``trmnl_profile_render_graph``, ``trmnl_display_canvas``.

  The three render-layout mixins define static methods that accept plain
  Python data structures (row dicts for list, event dicts for calendar,
  value dicts for charts) and return PNG bytes.  They are part of the
  trmnl.profile model (via _inherit) so they live alongside the ORM
  data-loading code and are easy to find for an Odoo project reviewer.

Call flow on a device poll
--------------------------
::

  /api/display  (device_display_controller.py)
    ↓ device.build_display_response()          trmnl_device_display
        ↓ profile._is_auto_refresh_due()       here — timing check
        ↓ profile._render_and_store_preview()  here — full pipeline
            ↓ _load_records()                  trmnl_profile — generic ORM search
            ↓ _load_calendar_records()         render_data — calendar ORM search
            ↓ _prepare_calendar_data()         render_data — ORM records → plain dicts
            ↓ _dispatch_renderer()             here  — selects PIL render method
                ↓ self._render_list_png()      trmnl_profile_render_list
                ↓ self._render_calendar_*_png  trmnl_profile_render_calendar
                ↓ self._render_bar_chart_png() trmnl_profile_render_graph
                ↓ self._render_line_chart_png  trmnl_profile_render_graph
            ↓ _finalize_display_image()        here  — composites footer band
        ↓ profile._get_display_image_url()     trmnl_profile — URL computation
"""
from __future__ import annotations

import base64
import logging
from datetime import timedelta, timezone

from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.trmnl.lib.display_canvas import (
    FOOTER_BAND_HEIGHT as _FOOTER_H,
    composite_with_footer,
)
from .trmnl_device import DEFAULT_REFRESH_RATE
from .trmnl_profile import _LAYOUT_LABELS

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
    - Renderer selection and dispatch (``_dispatch_renderer``).
    - Content-strip + footer compositing (``_finalize_display_image``).
    - Top-level pipeline entry points (``_render_and_store_preview``,
      ``action_render_preview``).
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

    def _should_render_for_device(self) -> bool:
        """Whether the next device poll should re-render before serving the PNG.

        Returns True when any of the following hold:
        - No preview has ever been generated.
        - ``preview_data_stale`` was set by the data-change watcher (source
          records were created / modified / deleted since the last render).
        - The configured auto-refresh interval has elapsed.
        - The stored renderer version no longer matches the installed module.
        """
        self.ensure_one()
        return (
            not self.preview_image
            or self.preview_data_stale
            or self._is_auto_refresh_due()
            or self._is_preview_renderer_stale()
        )

    # ------------------------------------------------------------------
    # renderer dispatch  (Odoo model layer → pure Python drawing layer)
    # ------------------------------------------------------------------

    def _dispatch_renderer(
        self,
        model_name,
        field_names,
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
                    return self._render_calendar_week_png(
                        week_events, week_start, self.calendar_week_mode,
                        width=width, content_height=content_height,
                        today=self._resolve_local_today(),
                    )
                else:
                    year, month = self._resolve_calendar_date()
                    events = self._prepare_calendar_data(
                        self._load_calendar_records(year, month)
                    )
                    return self._render_calendar_month_png(
                        events, year, month,
                        width=width, content_height=content_height,
                    )
            except UserError:
                raise
            except Exception as exc:
                _logger.warning(
                    "TRMNL calendar renderer failed for profile id=%s: %s",
                    self.id, exc, exc_info=True,
                )
                raise UserError(
                    _("Calendar preview could not be rendered: %s") % exc
                ) from exc

        empty_msg = self._empty_state_message(model_name)
        title = (self.name or "").strip() or model_name

        if self.trmnl_layout == "kanban":
            try:
                columns = self._prepare_kanban_columns(records, model_name, field_names)
                return self._render_kanban_png(
                    columns,
                    width=width,
                    content_height=content_height,
                    title=title,
                    empty_message=empty_msg,
                )
            except Exception as exc:
                _logger.warning(
                    "TRMNL kanban renderer failed for profile id=%s — empty kanban: %s",
                    self.id, exc, exc_info=True,
                )
                return self._render_kanban_png(
                    [],
                    width=width,
                    content_height=content_height,
                    title=title,
                    empty_message=empty_msg,
                )

        if self.trmnl_layout == "graph":
            graph_type = self.graph_type or "bar"
            try:
                if graph_type == "line":
                    points = self._load_line_data(model_name)
                    chart_title = (self.graph_title or "").strip() or (
                        self.line_date_field_id.field_description
                        if self.line_date_field_id
                        else "Line Chart"
                    )
                    measure_label = self._line_measure_label()
                    summary = []
                    if measure_label:
                        summary.append(measure_label)
                    if points:
                        last = points[-1]
                        summary.append(
                            _("Latest: %(val)s (%(label)s)") % {
                                "val": self._format_compact_number(last.get("value") or 0),
                                "label": last.get("label", ""),
                            }
                        )
                    return self._render_line_chart_png(
                        points,
                        chart_title,
                        measure_label,
                        width=width,
                        content_height=content_height,
                        summary_lines=summary[:2] or None,
                        empty_message=empty_msg,
                    )
                bars = self._load_graph_data(model_name)
                chart_title = (self.graph_title or "").strip() or (
                    self.graph_groupby_field_id.field_description
                    if self.graph_groupby_field_id
                    else "Graph"
                )
                measure_label = self._graph_measure_label()
                return self._render_bar_chart_png(
                    bars,
                    chart_title,
                    measure_label,
                    width=width,
                    content_height=content_height,
                    summary_lines=self._bar_chart_summary_lines(bars, measure_label),
                    empty_message=empty_msg,
                )
            except UserError:
                raise
            except Exception as exc:
                _logger.warning(
                    "TRMNL graph renderer (type=%s) failed for profile id=%s: %s",
                    graph_type, self.id, exc, exc_info=True,
                )
                raise UserError(
                    _("Graph preview could not be rendered: %s") % exc
                ) from exc

        items = self._prepare_list_items(records, field_names, model_name)
        total = self._list_total_count(model_name)
        return self._render_list_png(
            items,
            width=width,
            content_height=content_height,
            title=title,
            total_count=total,
            empty_message=empty_msg,
        )

    # ------------------------------------------------------------------
    # display footer compositing
    # ------------------------------------------------------------------

    def _format_last_update_timestamp(self, device_label, updated_at):
        """Return the footer label string in the user's local timezone."""
        user_tz = self._user_timezone()
        local_dt = updated_at.replace(tzinfo=timezone.utc).astimezone(user_tz)
        return f"{device_label} · Last update: {local_dt.strftime('%d.%m.%Y, %H:%M')}"

    def _get_footer_device_label(self):
        """Human-readable device label for the footer.

        Priority: admin ``device_name``, then ``mac_address``.
        """
        self.ensure_one()
        device = self.device_id
        name = (device.device_name or "").strip()
        if name:
            return name
        return device.mac_address or "TRMNL"

    def _finalize_display_image(self, png_bytes):
        """Composite content PNG with device frame and poll footer strip.

        Resolves device dimensions and poll label from ORM state, then
        delegates all PIL compositing to ``composite_with_footer`` in
        ``trmnl_display_canvas`` (Layer 2).
        """
        self.ensure_one()
        device_w, device_h = self._device_canvas_dimensions()
        dev = self.device_id

        poll_at = dev.last_poll_at
        label = (
            self._format_last_update_timestamp(self._get_footer_device_label(), poll_at)
            if poll_at
            else None
        )
        # List: threshold B/W for e-ink parity. Kanban: keep grayscale (column
        # rules, soft +N) — matches kanban_design_sample and device appearance.
        binarize = (self.trmnl_layout or "list") == "list"
        return composite_with_footer(
            png_bytes, device_w, device_h, label=label, binarize=binarize,
        )

    # ------------------------------------------------------------------
    # top-level render entry points
    # ------------------------------------------------------------------

    def action_render_preview(self):
        """Trigger a manual preview render from the profile form view.

        The web client saves the form (webSave) before calling this method.  We
        re-browse the record so the render always uses the persisted field values,
        not a stale in-memory cache from an earlier read in the same request.
        """
        self.ensure_one()
        if not self.app_model_id:
            raise UserError(_("Select an Odoo Model before rendering a preview."))

        self.env.flush_all()
        record = self.browse(self.id)
        record._render_and_store_preview()

        last_poll = record.device_id.last_poll_at
        rate = record.device_id.desired_refresh_rate or DEFAULT_REFRESH_RATE

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

        form_view = self.env.ref("trmnl.trmnl_profile_view_form", raise_if_not_found=False)
        form_view_id = form_view.id if form_view else False

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Preview Updated"),
                "message": msg,
                "type": "success",
                "sticky": False,
                # Re-open the form so preview_image_html (cache-busted by
                # preview_generated_at) and all fields reload in one click.
                "next": {
                    "type": "ir.actions.act_window",
                    "name": record.name,
                    "res_model": "trmnl.profile",
                    "res_id": record.id,
                    "view_mode": "form",
                    "views": [(form_view_id, "form")],
                    "target": "current",
                },
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
            label = _LAYOUT_LABELS.get(self.trmnl_layout, self.trmnl_layout)
            raise UserError(
                _("View Type '%s' is not available for the selected model. "
                  "Please update the profile and choose an available view type.")
                % label
            )

        valid_display_fields = self.display_field_ids.filtered(
            lambda f: f.model == model_name
        )
        if valid_display_fields:
            field_names = list(valid_display_fields.mapped("name"))[: self._LIST_MAX_COLS]
        else:
            field_names = ["display_name"]

        device_w, device_h = self._device_canvas_dimensions()
        content_h = device_h - _FOOTER_H

        # Calendar and graph layouts load their own data inside _dispatch_renderer.
        if self.trmnl_layout in ("calendar", "graph"):
            records = self.env[model_name].sudo().browse()
        else:
            records = self._load_records(model_name, field_names)
        png_bytes = self._dispatch_renderer(
            model_name, field_names, records,
            width=device_w, content_height=content_h,
        )
        png_bytes = self._finalize_display_image(png_bytes)

        self.write({
            "preview_image": base64.b64encode(png_bytes),
            "preview_generated_at": fields.Datetime.now(),
            "preview_renderer_version": self._get_installed_trmnl_version(),
            "preview_data_stale": False,
        })
        self.invalidate_recordset([
            "preview_image_html",
            "display_image_url",
            "preview_image",
        ])
        # Point the device at this PNG immediately (same URL the form preview uses).
        image_url = self._get_display_image_url()
        filename = self._get_display_filename()
        if self.device_id and image_url and filename:
            self.device_id.sudo().write({
                "image_url": image_url,
                "filename": filename,
            })
