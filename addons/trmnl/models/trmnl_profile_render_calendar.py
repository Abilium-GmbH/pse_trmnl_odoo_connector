"""TRMNL profile rendering — calendar (month-view and week-view) drawing methods.

PIL drawing for both calendar views lives here as static methods on the
trmnl.profile mixin.  The ORM data-loading methods (_load_calendar_records,
_load_calendar_week_records, _prepare_calendar_data, _prepare_calendar_week_data)
live in trmnl_profile_render.py; this file only handles the PIL drawing step
that converts pre-processed event lists into PNG bytes.

How calendar rendering reaches the device
------------------------------------------
1. Device polls ``/api/display``.
2. ``TrmnlDeviceDisplayMixin.build_display_response()`` triggers
   ``profile._render_and_store_preview()``.
3. ``_render_and_store_preview`` calls ``_dispatch_renderer``.
4. For ``trmnl_layout == 'calendar'``, ``_dispatch_renderer`` loads ORM
   calendar.event records, converts them to plain dicts, and then calls
   ``self._render_calendar_month_png()`` or ``self._render_calendar_week_png()``
   (defined here) with those plain dicts and the device dimensions.
5. The returned PNG bytes are composited with the footer strip by
   ``_finalize_display_image`` and stored in ``preview_image``.
6. The device downloads the stored PNG from ``/api/profile/image/<id>``.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from PIL import Image, ImageDraw

from odoo import models

from odoo.addons.trmnl.lib import display_canvas as _canvas


class TrmnlProfileRenderCalendarMixin(models.Model):
    """Adds calendar month and week PIL rendering to trmnl.profile."""

    _inherit = "trmnl.profile"

    # ── Month-view renderer ───────────────────────────────────────────────────

    @staticmethod
    def _render_calendar_month_png(
        events: list[dict],
        year: int,
        month: int,
        *,
        width: int | None = None,
        content_height: int | None = None,
    ) -> bytes:
        """Render a month-view calendar grid as a grayscale PNG.

        ``events`` is a list of plain dicts produced by ``_prepare_calendar_data``;
        each dict has ``start`` (date), ``title`` (str), ``time_str`` (str).

        ``width`` / ``content_height`` come from the linked device record so the
        grid scales to the device's reported resolution; falls back to the default
        800×CONTENT_HEIGHT when dimensions have not yet been reported.
        """
        # ── Geometry constants ─────────────────────────────────────────────
        _HEADER_H = 36       # month/year title band
        _DOW_H = 24          # day-of-week label band
        _GRID_TOP = _HEADER_H + _DOW_H   # first pixel row of the day grid (= 60)
        _COLS = 7
        _GRAY_GRID = 180     # horizontal and vertical grid lines
        _DOW_BAND = 252
        _TITLE_RULE = _canvas.EINK_RULE_FAINT
        _OUT_FILL = 232      # out-of-month cell base fill
        _OUT_LINE = 188      # out-of-month hatch colour
        _OUT_HATCH_STEP = 4
        _TODAY_FILL = 242
        _TODAY_OUTLINE = _canvas.EINK_INK
        _DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

        # ── Fonts ──────────────────────────────────────────────────────────
        f_title = _canvas.load_font(23, bold=True)
        f_dow = _canvas.load_font(10)
        f_daynum = _canvas.load_font(14, bold=True)
        f_event = _canvas.load_font(10)

        w, h = _canvas.resolve_canvas_size(width, content_height)
        col_w = w // _COLS

        img = Image.new("L", (w, h), _canvas.EINK_WHITE)
        draw = ImageDraw.Draw(img)

        today = date.today()

        # Index events by date for O(1) lookup per cell.
        by_date: dict[date, list[dict]] = {}
        for ev in events:
            d = ev.get("start")
            if isinstance(d, date):
                by_date.setdefault(d, []).append(ev)

        # ── Month/year title ───────────────────────────────────────────────
        title_text = date(year, month, 1).strftime("%B %Y")
        tw = _canvas.text_width(draw, title_text, f_title)
        tb = draw.textbbox((0, 0), title_text, font=f_title)
        th = tb[3] - tb[1]
        draw.text(
            ((w - tw) // 2, (_HEADER_H - th) // 2 - tb[1]),
            title_text,
            fill=_canvas.EINK_BLACK,
            font=f_title,
        )
        draw.line([(0, _HEADER_H - 1), (w - 1, _HEADER_H - 1)], fill=_TITLE_RULE, width=1)

        # ── Day-of-week header band ────────────────────────────────────────
        draw.rectangle([0, _HEADER_H, w - 1, _GRID_TOP - 1], fill=_DOW_BAND)
        for col, label in enumerate(_DAY_NAMES):
            cx = col * col_w
            cright = w if col == _COLS - 1 else (col + 1) * col_w
            cw = cright - cx
            lw = _canvas.text_width(draw, label, f_dow)
            db = draw.textbbox((0, 0), label, font=f_dow)
            dh = db[3] - db[1]
            draw.text(
                (cx + (cw - lw) // 2, _HEADER_H + (_DOW_H - dh) // 2 - db[1]),
                label,
                fill=_canvas.EINK_INK_SOFT,
                font=f_dow,
            )

        # ── Compute week rows (trim trailing all-zero row) ─────────────────
        weeks = calendar.monthcalendar(year, month)
        while weeks and not any(weeks[-1]):
            weeks.pop()
        n_rows = len(weeks)
        row_h = (h - _GRID_TOP) // n_rows

        cell_pad_x = 6
        day_num_top_pad = 3
        pad_cells: list[tuple] = []

        def _fill_out_of_month(img2: Image.Image, x0: int, y0: int, x1: int, y1: int) -> None:
            """Diagonal hatch on out-of-month padding cells."""
            pw = x1 - x0 + 1
            ph = y1 - y0 + 1
            patch = Image.new("L", (pw, ph), _OUT_FILL)
            pdraw = ImageDraw.Draw(patch)
            step = _OUT_HATCH_STEP
            for offset in range(-ph, pw, step):
                pdraw.line([(offset, 0), (offset + ph, ph - 1)], fill=_OUT_LINE)
            for offset in range(0, pw + ph, step):
                pdraw.line([(0, offset), (pw - 1, offset - pw + 1)], fill=_OUT_LINE)
            img2.paste(patch, (x0, y0))

        # ── Day cells ─────────────────────────────────────────────────────
        for row_i, week in enumerate(weeks):
            for col_i, day_num in enumerate(week):
                cx = col_i * col_w
                cright = w if col_i == _COLS - 1 else (col_i + 1) * col_w
                cw = cright - cx
                cy = _GRID_TOP + row_i * row_h
                cell_box = (cx, cy, cright - 1, cy + row_h - 1)

                out_of_month = day_num == 0
                is_today = not out_of_month and date(year, month, day_num) == today

                if out_of_month:
                    pad_cells.append(cell_box)
                    _fill_out_of_month(img, *cell_box)
                    continue

                draw.rectangle([*cell_box], fill=_canvas.EINK_WHITE)

                if is_today:
                    pad_x, pad_y = 3, 2
                    box = [cx + pad_x, cy + pad_y, cright - 1 - pad_x, cy + 20]
                    draw.rectangle(box, fill=_TODAY_FILL, outline=_TODAY_OUTLINE, width=1)

                dstr = str(day_num)
                dbn = draw.textbbox((0, 0), dstr, font=f_daynum)
                dnh = dbn[3] - dbn[1]
                dnx = cx + cell_pad_x
                dny = cy + day_num_top_pad + max(0, (18 - dnh) // 2) - dbn[1]
                draw.text((dnx, dny), dstr, fill=_canvas.EINK_BLACK, font=f_daynum)

                d = date(year, month, day_num)
                day_events = by_date.get(d, [])
                if not day_events:
                    continue

                # Match legacy vertical metrics so event ink lands near (cx+6, cy+22).
                event_line_h = 13
                ev_y0 = cy + 19
                max_ev = max(0, (row_h - 20) // event_line_h)
                max_lbl_ev = cw - 8

                for i, ev in enumerate(day_events[:max_ev]):
                    time_str = ev.get("time_str", "")
                    ev_title = ev.get("title", "")
                    label = f"{time_str} {ev_title}".strip() if time_str else ev_title
                    draw.text(
                        (cx + 4, ev_y0 + i * event_line_h),
                        _canvas.trunc(draw, label, f_event, max_lbl_ev),
                        fill=_canvas.EINK_BLACK,
                        font=f_event,
                    )

                overflow = len(day_events) - max_ev
                if overflow > 0:
                    draw.text(
                        (cx + 4, ev_y0 + max_ev * event_line_h),
                        _canvas.trunc(draw, f"+{overflow} more", f_event, max_lbl_ev),
                        fill=_canvas.EINK_INK_SOFT,
                        font=f_event,
                    )

        # ── Grid lines (horizontal then vertical) ─────────────────────────
        for r in range(n_rows + 1):
            y = _GRID_TOP + r * row_h
            draw.line([(0, y), (w - 1, y)], fill=_GRAY_GRID, width=1)
        for c in range(1, _COLS):
            x = c * col_w
            draw.line([(x, _GRID_TOP), (x, _GRID_TOP + n_rows * row_h)], fill=_GRAY_GRID, width=1)

        # Re-hatch padding cells so the pattern stays visible over the grid lines.
        for cell_box in pad_cells:
            _fill_out_of_month(img, *cell_box)

        return _canvas.save_png(img)

    # ── Week-view renderer ────────────────────────────────────────────────────

    @staticmethod
    def _render_calendar_week_png(
        events: list[dict],
        week_start: date,
        week_mode: str,
        *,
        width: int | None = None,
        content_height: int | None = None,
        today: date | None = None,
    ) -> bytes:
        """Render a week-view time-grid calendar as a grayscale PNG.

        ``events`` is a list of plain dicts produced by ``_prepare_calendar_week_data``;
        each dict has ``start_datetime`` (datetime) and ``end_datetime`` (datetime).
        All-day events are excluded by the caller.

        ``week_mode`` is ``"work_week"`` (Mon–Fri, 5 columns) or ``"full_week"``
        (Mon–Sun, 7 columns).
        """
        # ── Geometry constants ─────────────────────────────────────────────
        _WEEK_HDR_H = 26      # week number / month banner
        _DAY_HDR_H = 32       # per-column day label band
        _HEADER_H = _WEEK_HDR_H + _DAY_HDR_H
        _TIME_COL_W = 54      # left column for hour labels
        _HOUR_START = 7
        _HOUR_END = 19
        _HOURS = _HOUR_END - _HOUR_START
        _GRAY_BAND = 250      # alternating even-hour background fill
        _GRAY_GRID = _canvas.EINK_RULE
        _GRAY_MUTED = _canvas.EINK_INK_SOFT
        _GRAY_EVENT = 68
        _GRAY_EVENT_OUTLINE = _canvas.EINK_INK
        _TITLE_BAND = 252
        _TITLE_RULE = _canvas.EINK_RULE_FAINT
        _TODAY_HDR_FILL = 240
        _DAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

        # ── Fonts ──────────────────────────────────────────────────────────
        f_title = _canvas.load_font(16, bold=True)
        f_day = _canvas.load_font(12)
        f_time = _canvas.load_font(9)
        f_event = _canvas.load_font(10)

        w, h = _canvas.resolve_canvas_size(width, content_height)
        grid_h = h - _HEADER_H
        hour_h_f = grid_h / _HOURS

        num_days = 5 if week_mode == "work_week" else 7
        col_w = (w - _TIME_COL_W) // num_days

        img = Image.new("L", (w, h), _canvas.EINK_WHITE)
        draw = ImageDraw.Draw(img)

        today = today or date.today()
        _, iso_week, _ = week_start.isocalendar()

        # ── Week banner ────────────────────────────────────────────────────
        draw.rectangle([0, 0, w - 1, _WEEK_HDR_H - 1], fill=_TITLE_BAND)
        title = f"Week {iso_week}  ·  {week_start.strftime('%B %Y')}"
        tw = _canvas.text_width(draw, title, f_title)
        tb = draw.textbbox((0, 0), title, font=f_title)
        th = tb[3] - tb[1]
        draw.text(
            ((w - tw) // 2, (_WEEK_HDR_H - th) // 2 - tb[1]),
            title,
            fill=_canvas.EINK_BLACK,
            font=f_title,
        )
        draw.line([(0, _WEEK_HDR_H - 1), (w - 1, _WEEK_HDR_H - 1)], fill=_TITLE_RULE, width=1)

        # ── Day-column headers ─────────────────────────────────────────────
        hdr_y = _WEEK_HDR_H
        for col in range(num_days):
            d = week_start + timedelta(days=col)
            cx = _TIME_COL_W + col * col_w
            cr = w if col == num_days - 1 else _TIME_COL_W + (col + 1) * col_w
            cw = cr - cx
            is_today = d == today
            label = f"{_DAY_ABBR[col]}  {d.day}"
            lw = _canvas.text_width(draw, label, f_day)
            db = draw.textbbox((0, 0), label, font=f_day)
            dh = db[3] - db[1]
            text_x = cx + (cw - lw) // 2
            text_y = hdr_y + (_DAY_HDR_H - dh) // 2 - db[1]
            if is_today:
                draw.rectangle(
                    [cx + 1, hdr_y + 1, cr - 2, hdr_y + _DAY_HDR_H - 2],
                    fill=_TODAY_HDR_FILL,
                    outline=_GRAY_EVENT_OUTLINE,
                    width=1,
                )
            draw.text((text_x, text_y), label, fill=_canvas.EINK_BLACK, font=f_day)

        grid_top = _HEADER_H

        # ── Alternating even-hour background bands ─────────────────────────
        for hour_i in range(_HOURS):
            actual = _HOUR_START + hour_i
            if actual % 2 == 0:
                y = grid_top + int(hour_i * hour_h_f)
                y_next = grid_top + int((hour_i + 1) * hour_h_f)
                draw.rectangle([_TIME_COL_W, y, w - 1, y_next - 1], fill=_GRAY_BAND)

        # ── Hour labels and horizontal grid lines ──────────────────────────
        for hour_i in range(_HOURS + 1):
            actual = _HOUR_START + hour_i
            y = grid_top + int(hour_i * hour_h_f)
            label = f"{actual:02d}:00"
            lw = _canvas.text_width(draw, label, f_time)
            tb = draw.textbbox((0, 0), label, font=f_time)
            draw.text((_TIME_COL_W - lw - 5, y + 2 - tb[1]), label, fill=_GRAY_MUTED, font=f_time)
            draw.line([(_TIME_COL_W, y), (w - 1, y)], fill=_GRAY_GRID, width=1)

        # ── Vertical column separators ─────────────────────────────────────
        for col in range(num_days + 1):
            x = (_TIME_COL_W + col * col_w) if col < num_days else (w - 1)
            draw.line([(x, grid_top), (x, grid_top + grid_h)], fill=_GRAY_GRID, width=1)
        draw.line([(_TIME_COL_W, _HEADER_H), (_TIME_COL_W, h - 1)], fill=_GRAY_GRID, width=1)

        # ── Events ────────────────────────────────────────────────────────
        ev_pad = 3
        ev_min_h = 14
        for ev in events:
            start_dt = ev.get("start_datetime")
            end_dt = ev.get("end_datetime")
            if not isinstance(start_dt, datetime) or not isinstance(end_dt, datetime):
                continue
            ev_start_date = start_dt.date()
            ev_end_date = end_dt.date()
            # Render one segment per column the event spans (handles multi-day events).
            for col_idx in range(num_days):
                col_date = week_start + timedelta(days=col_idx)
                if col_date < ev_start_date or col_date > ev_end_date:
                    continue
                seg_start_h = (
                    start_dt.hour + start_dt.minute / 60.0
                    if col_date == ev_start_date
                    else float(_HOUR_START)
                )
                seg_end_h = (
                    end_dt.hour + end_dt.minute / 60.0
                    if col_date == ev_end_date
                    else float(_HOUR_END)
                )
                # Skip segments entirely outside the visible hour range.
                if seg_end_h <= _HOUR_START or seg_start_h >= _HOUR_END:
                    continue
                cx = _TIME_COL_W + col_idx * col_w + ev_pad
                cr = (w if col_idx == num_days - 1 else _TIME_COL_W + (col_idx + 1) * col_w) - ev_pad
                frac_start = max(0.0, min(float(_HOURS), seg_start_h - _HOUR_START))
                frac_end = max(0.0, min(float(_HOURS), seg_end_h - _HOUR_START))
                y_top = grid_top + int(frac_start * hour_h_f)
                y_bot = grid_top + int(frac_end * hour_h_f)
                y_top = max(y_top, grid_top)
                y_bot = min(y_bot, grid_top + grid_h)
                y_bot = max(y_bot, y_top + ev_min_h)
                draw.rectangle(
                    [cx, y_top, cr - 1, y_bot - 1],
                    fill=_GRAY_EVENT,
                    outline=_GRAY_EVENT_OUTLINE,
                    width=1,
                )
                # Label only on the first (start) column segment.
                if col_date == ev_start_date:
                    ev_label = f"{start_dt.strftime('%H:%M')} {ev.get('title', '')}".strip()
                    draw.text(
                        (cx + 3, y_top + 3),
                        _canvas.trunc(draw, ev_label, f_event, cr - cx - 8),
                        fill=_canvas.EINK_WHITE,
                        font=f_event,
                    )

        return _canvas.save_png(img)
