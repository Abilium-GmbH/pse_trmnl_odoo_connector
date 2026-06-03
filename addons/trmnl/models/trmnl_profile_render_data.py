"""TRMNL profile — data loading layer for the rendering pipeline.

Extracted from ``trmnl_profile_render`` as a focused ``_inherit`` mixin.
Contains all ORM queries and ORM-record → plain-dict conversion needed by the
three PIL renderer mixins (list, calendar, graph).  No PIL code lives here.

Responsibilities
----------------
- User-timezone resolution (``_user_timezone``).
- Calendar ORM loading (``_load_calendar_records``, ``_load_calendar_week_records``).
- Calendar ORM → plain-dict conversion (``_prepare_calendar_data``,
  ``_prepare_calendar_week_data``).
- Line and graph aggregate data loading via ``read_group``
  (``_load_line_data``, ``_load_graph_data``).
- Device canvas dimension lookup (``_device_canvas_dimensions``).
- Custom-domain merging for calendar queries (``_merge_custom_filter_domain``).
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from odoo import _, models
from odoo.exceptions import UserError
from odoo.fields import Domain

from odoo.addons.trmnl.lib.display_canvas import(
    DISPLAY_HEIGHT as _DEFAULT_H,
    DISPLAY_WIDTH as _DEFAULT_W,
)


class TrmnlProfileRenderDataMixin(models.Model):
    """ORM data-loading helpers for the TRMNL rendering pipeline."""

    _inherit = "trmnl.profile"

    # ------------------------------------------------------------------
    # timezone and calendar data extraction (ORM records → plain Python dicts)
    # ------------------------------------------------------------------

    def _user_timezone(self):
        """Return the timezone to render in, falling back to UTC.

        Device polls hit /api/display as the public user (no tz configured), so the
        timezone is taken from the profile's creator (create_uid) rather than
        self.env.user.  The backend preview path resolves the same way, so both
        contexts agree and the device matches what the user configured.
        """
        tz_name = (self.create_uid.tz or self.env.user.tz or "UTC")
        try:
            return ZoneInfo(tz_name)
        except Exception:
            return ZoneInfo("UTC")

    def _prepare_calendar_data(self, records) -> list[dict]:
        """Extract plain event dicts from calendar.event ORM records.

        All ORM access is isolated in this method so the Layer 2 renderer
        receives only plain Python dicts with no ORM references.  Odoo stores
        datetimes as naive UTC; timed events are converted to the user's
        configured timezone so rendered times match the user's calendar.
        All-day events carry a date/midnight marker and are left unshifted.
        """
        user_tz = self._user_timezone()
        utc = ZoneInfo("UTC")
        events = []
        for rec in records:
            try:
                start = rec.start
                if not start:
                    continue
                if getattr(rec, "allday", False):
                    # All-day: start is a date/midnight marker — do not tz-shift.
                    start_date = start.date() if hasattr(start, "date") and callable(start.date) else start
                    time_str = ""
                else:
                    start_local = start.replace(tzinfo=utc).astimezone(user_tz).replace(tzinfo=None)
                    start_date = start_local.date()
                    time_str = start_local.strftime("%H:%M")
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
        Odoo stores datetimes as naive UTC; they are converted to the user's
        configured timezone here so the renderer works with local times throughout.
        All ORM access is isolated here so the Layer 2 renderer receives only
        plain Python dicts with naive local-time datetimes.
        """
        user_tz = self._user_timezone()
        utc = ZoneInfo("UTC")

        events = []
        for rec in records:
            try:
                start = rec.start
                if not start:
                    continue
                if getattr(rec, "allday", False):
                    continue
                stop = rec.stop or (start + timedelta(hours=1))
                # Convert naive UTC → aware UTC → aware local → naive local.
                start_local = start.replace(tzinfo=utc).astimezone(user_tz).replace(tzinfo=None)
                stop_local = stop.replace(tzinfo=utc).astimezone(user_tz).replace(tzinfo=None)
                events.append({
                    "title":          rec.display_name or "",
                    "start_datetime": start_local,
                    "end_datetime":   stop_local,
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

    def _resolve_local_today(self) -> date:
        """Return today's date in the user's configured timezone."""
        try:
            return datetime.now(self._user_timezone()).date()
        except Exception:
            return date.today()

    def _resolve_calendar_week_start(self) -> date:
        """Return the Monday of the target week in the user's local timezone."""
        if self.calendar_reference_mode == "custom" and self.calendar_reference_date:
            ref = self.calendar_reference_date
            return ref - timedelta(days=ref.weekday())
        # Use the user's timezone so "today" matches what the user actually sees.
        # date.today() returns the server date (UTC on most hosts), which can be
        # one day behind/ahead of the user's local date near midnight.
        local_today = self._resolve_local_today()
        return local_today - timedelta(days=local_today.weekday())

    # ------------------------------------------------------------------
    # calendar ORM loading
    # ------------------------------------------------------------------

    def _append_calendar_my_records_domain(self, domain: list) -> None:
        """Append ``user_id`` filter when ``filter_preset`` is ``my_records``."""
        if self.filter_preset != "my_records":
            return
        if self.user_ids:
            domain.append(("user_id", "in", self.user_ids.ids))
        else:
            domain.append(("user_id", "=", self.env.uid))

    def _merge_custom_filter_domain(self, domain: list) -> list:
        """AND the profile's ``filter_domain`` onto *domain* when configured."""
        raw_custom = (self.filter_domain or "").strip()
        if not raw_custom or raw_custom == "[]":
            return domain
        try:
            custom_domain = self._eval_filter_domain(raw_custom)
            if custom_domain:
                return list(Domain.AND([domain, custom_domain]))
        except Exception as exc:
            raise UserError(
                _("Custom Domain is invalid and could not be applied: %s") % exc
            ) from exc
        return domain

    def _calendar_event_search(self, domain: list):
        """Search ``calendar.event`` with profile archive and limit settings."""
        limit = self.display_limit or 200
        env = self.env["calendar.event"].sudo()
        if self.include_archived:
            env = env.with_context(active_test=False)
        return env.search(domain, limit=limit, order="start asc")

    @staticmethod
    def _measure_field_label(field) -> str:
        """Human-readable label for a graph/line measure field, or ``Count``."""
        if field:
            return field.field_description or field.name
        return "Count"

    def _device_canvas_dimensions(self) -> tuple[int, int]:
        """Return (width, height) for the linked device or TRMNL defaults."""
        self.ensure_one()
        dev = self.device_id
        width = (dev.display_width if dev and dev.display_width > 0 else None) or _DEFAULT_W
        height = (dev.display_height if dev and dev.display_height > 0 else None) or _DEFAULT_H
        return width, height

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
        self._append_calendar_my_records_domain(domain)
        domain = self._merge_custom_filter_domain(domain)
        return self._calendar_event_search(domain)

    def _load_calendar_week_records(self, week_start: date):
        """Load calendar.event records for the displayed week.

        Always loads the full 7 days regardless of week_mode so the renderer
        can decide which columns to draw.  Respects my_records filter and
        applies filter_domain on top.

        The query window is expanded by ±1 day around the Mon–Sun range so
        that events which fall within the displayed week after UTC→local
        timezone conversion are never missed.  The renderer filters to the
        correct columns using local-time dates.

        Note: Odoo interprets a bare date value in a Datetime domain as
        midnight of that date (UTC), so ``<= Sunday`` silently drops all
        Sunday events after 00:00 UTC.  Using ``< Monday-next-week`` (i.e.
        the strict-less-than form with the following day) is the correct way
        to include the full last day of the range.
        """
        query_start = week_start - timedelta(days=1)
        query_end = week_start + timedelta(days=8)  # Mon next week + 1 → strict <
        domain = [("start", ">=", query_start), ("start", "<", query_end)]
        self._append_calendar_my_records_domain(domain)
        domain = self._merge_custom_filter_domain(domain)
        return self._calendar_event_search(domain)

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
        for token in domain:
            if not isinstance(token, (list, tuple)) or len(token) != 3:
                continue
            f, op, val = token
            if f != field_name or op not in (">=", ">"):
                continue
            if isinstance(val, datetime):
                return val.date()
            if isinstance(val, date):
                return val
            if isinstance(val, str):
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(val, fmt).date()
                    except ValueError:
                        pass
        return None

    @staticmethod
    def _generate_line_date_buckets(min_date, max_date, granularity: str):
        """Yield every expected bucket start-date from *min_date* to *max_date*.

        Buckets are contiguous and non-overlapping.  *granularity* must be
        one of ``"day"``, ``"week"``, or ``"month"``.
        """
        current = min_date
        while current <= max_date:
            yield current
            if granularity == "day":
                current = current + timedelta(days=1)
            elif granularity == "week":
                current = current + timedelta(weeks=1)
            else:  # month
                m, y = current.month, current.year
                current = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)

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
        return self._measure_field_label(self.line_measure_field_id)

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
        """Return a human-readable measure label for the graph renderer."""
        return self._measure_field_label(self.graph_measure_field_id)

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
