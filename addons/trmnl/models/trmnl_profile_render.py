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
            ↓ _load_calendar_records()         here  — calendar-specific ORM search
            ↓ _prepare_calendar_data()         here  — ORM records → plain dicts
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
from calendar import monthrange
from datetime import date, timedelta, timezone
from zoneinfo import ZoneInfo

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain

from odoo.addons.trmnl.trmnl_display_canvas import (
    DISPLAY_HEIGHT as _DEFAULT_H,
    DISPLAY_WIDTH as _DEFAULT_W,
    FOOTER_BAND_HEIGHT as _FOOTER_H,
    composite_with_footer,
)
# PIL drawing is handled by the three render-layout mixins defined in
# trmnl_profile_render_list, trmnl_profile_render_calendar, and
# trmnl_profile_render_graph.  Their methods are available on self because
# all three inherit from trmnl.profile via _inherit.

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
    - Calendar-specific ORM queries (``_load_calendar_*``).
    - ORM-record → plain-Python-dict conversion (``_prepare_calendar_*``).
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
        """Whether the next device poll should re-render before serving the PNG."""
        self.ensure_one()
        return (
            not self.preview_image
            or self._is_auto_refresh_due()
            or self._is_preview_renderer_stale()
        )

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
            if self.user_ids:
                domain.append(("user_id", "in", self.user_ids.ids))
            else:
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
            if self.user_ids:
                domain.append(("user_id", "in", self.user_ids.ids))
            else:
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
    # line chart data loading
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_group_start_date(domain, field_name):
        """Extract the bucket start date from a read_group ``__domain``.

        Each read_group result row carries a ``__domain`` that constrains
        records to that bucket, e.g.
        ``[('create_date', '>=', datetime(2024,5,1)), ...]``.
        We locate the ``>=`` (or ``>``) leaf for *field_name* and return
        its value normalised to a ``datetime.date``.  Returns ``None`` when
        no matching leaf is found.
        """
        from datetime import date as _date, datetime as _datetime
        for token in domain:
            if not isinstance(token, (list, tuple)) or len(token) != 3:
                continue
            f, op, val = token
            if f != field_name or op not in (">=", ">"):
                continue
            if isinstance(val, _datetime):
                return val.date()
            if isinstance(val, _date):
                return val
            if isinstance(val, str):
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        return _datetime.strptime(val, fmt).date()
                    except ValueError:
                        pass
        return None

    @staticmethod
    def _generate_line_date_buckets(min_date, max_date, granularity: str):
        """Yield every expected bucket start-date from *min_date* to *max_date*.

        Buckets are contiguous and non-overlapping.  *granularity* must be
        one of ``"day"``, ``"week"``, or ``"month"``.
        """
        from datetime import date as _date, timedelta
        current = min_date
        while current <= max_date:
            yield current
            if granularity == "day":
                current = current + timedelta(days=1)
            elif granularity == "week":
                current = current + timedelta(weeks=1)
            else:  # month
                m, y = current.month, current.year
                current = _date(y + 1, 1, 1) if m == 12 else _date(y, m + 1, 1)

    @staticmethod
    def _format_line_date_label(d, granularity: str, multi_year: bool) -> str:
        """Format a bucket start-date as a concise x-axis label."""
        if granularity == "day":
            return d.strftime("%d %b %y") if multi_year else d.strftime("%d %b")
        if granularity == "week":
            iso = d.isocalendar()
            return f"W{iso[1]:02d}'{str(iso[0])[2:]}" if multi_year else f"W{iso[1]:02d}"
        # month
        return d.strftime("%b '%y") if multi_year else d.strftime("%b")

    def _line_measure_label(self) -> str:
        """Return a human-readable measure label for the line chart y-axis."""
        if self.line_measure_field_id:
            return self.line_measure_field_id.field_description or self.line_measure_field_id.name
        return "Count"

    def _load_line_data(self, model_name: str) -> list[dict]:
        """Aggregate records into time-series points for the line chart renderer.

        Uses ``read_group()`` with the configured date granularity.  Returns a
        list of ``{"label": str, "value": float}`` dicts sorted chronologically,
        with zero-filled gaps for buckets that have no records, capped at
        ``line_max_points`` (taking the most-recent N points).
        """
        self.ensure_one()
        date_field = self.line_date_field_id
        if not date_field:
            return []

        gb_name = date_field.name
        granularity = self.line_date_groupby or "month"
        gb_spec = f"{gb_name}:{granularity}"

        measure_field = self.line_measure_field_id
        m_name = measure_field.name if measure_field else None

        domain = self._build_effective_domain(model_name)

        # Do NOT include gb_spec in fields — Odoo 19 interprets "field:granularity"
        # as "aggregate granularity on field", which is invalid.  The groupby
        # columns appear in every result row automatically; __domain and __count
        # are always present.
        fields_spec = []
        if m_name:
            fields_spec.append(f"{m_name}:sum")

        model_env = self.env[model_name].sudo()
        if self.include_archived:
            model_env = model_env.with_context(active_test=False)

        try:
            groups = model_env.read_group(
                domain=domain,
                fields=fields_spec,
                groupby=[gb_spec],
                lazy=False,
            )
        except Exception as exc:
            raise UserError(
                _("Line chart data could not be loaded: %s") % exc
            ) from exc

        if not groups:
            return []

        # Extract (start_date, value) from each group; sort chronologically.
        dated = []
        for row in groups:
            start = self._extract_group_start_date(row.get("__domain", []), gb_name)
            if start is None:
                continue
            value = float(row.get(m_name) or 0) if m_name else float(row.get("__count") or 0)
            dated.append((start, value))
        dated.sort(key=lambda x: x[0])

        if not dated:
            return []

        # Build a lookup and fill zero-gaps across the full date range.
        by_date = {d: v for d, v in dated}
        min_date, max_date = dated[0][0], dated[-1][0]
        all_dates = list(self._generate_line_date_buckets(min_date, max_date, granularity))

        # Cap at max_points (most-recent N).
        max_points = min(max(1, self.line_max_points or 12), 52)
        all_dates = all_dates[-max_points:]

        multi_year = len({d.year for d in all_dates}) > 1
        return [
            {
                "label": self._format_line_date_label(d, granularity, multi_year),
                "value": by_date.get(d, 0.0),
            }
            for d in all_dates
        ]

    # ------------------------------------------------------------------
    # graph data loading
    # ------------------------------------------------------------------

    def _graph_measure_label(self) -> str:
        """Return a human-readable measure label for the graph renderer.

        Returns the field description when a measure field is configured,
        otherwise "Count".
        """
        if self.graph_measure_field_id:
            return self.graph_measure_field_id.field_description or self.graph_measure_field_id.name
        return "Count"

    def _load_graph_data(self, model_name: str) -> list[dict]:
        """Aggregate model records and return sorted bar data for the renderer.

        Uses ORM ``read_group()`` to aggregate by ``graph_groupby_field_id``,
        summing ``graph_measure_field_id`` (or counting records when no measure
        is configured). Normalises many2one tuples and selection values to
        display strings. Applies ``_build_effective_domain()`` so preset and
        custom domain filters are respected.

        Returns a list of ``{"label": str, "value": float}`` dicts, sorted
        according to ``graph_sort_order`` and capped at ``graph_max_groups``.
        """
        self.ensure_one()

        groupby_field = self.graph_groupby_field_id
        if not groupby_field:
            return []

        gb_name = groupby_field.name
        measure_field = self.graph_measure_field_id
        m_name = measure_field.name if measure_field else None

        domain = self._build_effective_domain(model_name)

        # Do NOT include gb_name in fields — Odoo 19 treats plain field names
        # in the fields list as aggregation targets, which is invalid for
        # groupby columns.  The groupby field appears in every result row
        # automatically; only aggregated measure fields need to be listed.
        fields_spec = []
        if m_name:
            fields_spec.append(f"{m_name}:sum")

        model_env = self.env[model_name].sudo()
        if self.include_archived:
            model_env = model_env.with_context(active_test=False)

        try:
            groups = model_env.read_group(
                domain=domain,
                fields=fields_spec,
                groupby=[gb_name],
                lazy=False,
            )
        except Exception as exc:
            raise UserError(
                _("Graph data could not be loaded: %s") % exc
            ) from exc

        # Resolve selection labels once for the groupby field.
        selection_map: dict = {}
        if groupby_field.ttype == "selection":
            try:
                fget = model_env.fields_get([gb_name])
                sel = fget.get(gb_name, {}).get("selection", [])
                selection_map = dict(sel)
            except Exception:
                pass

        bars = []
        for row in groups:
            raw_val = row.get(gb_name)

            # Normalise group key to a display string.
            if raw_val is False or raw_val is None:
                label = "(none)"
            elif isinstance(raw_val, tuple):
                # many2one: (id, display_name) or (value, label) for selection
                label = str(raw_val[1]) if len(raw_val) > 1 else str(raw_val[0])
            elif selection_map and raw_val in selection_map:
                label = selection_map[raw_val]
            else:
                label = str(raw_val)

            # Aggregate value: sum field or count.
            if m_name:
                value = float(row.get(m_name) or 0)
            else:
                value = float(row.get("__count") or 0)

            bars.append({"label": label, "value": value})

        # Sort
        sort_order = self.graph_sort_order or "value_desc"
        if sort_order == "value_desc":
            bars.sort(key=lambda b: b["value"], reverse=True)
        elif sort_order == "value_asc":
            bars.sort(key=lambda b: b["value"])
        elif sort_order == "label_asc":
            bars.sort(key=lambda b: b["label"].lower())
        elif sort_order == "label_desc":
            bars.sort(key=lambda b: b["label"].lower(), reverse=True)

        max_groups = min(self.graph_max_groups or 10, 20)
        return bars[:max_groups]

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
        """Composite content PNG with device frame and poll footer strip.

        Resolves device dimensions and poll label from ORM state, then
        delegates all PIL compositing to ``composite_with_footer`` in
        ``trmnl_display_canvas`` (Layer 2).
        """
        self.ensure_one()
        dev = self.device_id
        device_w = (dev.display_width if dev and dev.display_width > 0 else None) or _DEFAULT_W
        device_h = (dev.display_height if dev and dev.display_height > 0 else None) or _DEFAULT_H

        poll_at = dev.last_poll_at
        label = (
            self._format_poll_timestamp(self._get_footer_device_label(), poll_at)
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
        rate = record.device_id.desired_refresh_rate or 1800

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

        dev = self.device_id
        device_w = (dev.display_width if dev and dev.display_width > 0 else None) or _DEFAULT_W
        device_h = (dev.display_height if dev and dev.display_height > 0 else None) or _DEFAULT_H
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
