"""Pure-Pillow week-view calendar renderer for TRMNL e-ink.

No Odoo ORM imports. Receives plain Python data, returns PNG bytes. The Odoo
profile model handles all data loading and passes pre-processed event dicts here.

Defaults to 800×CONTENT_HEIGHT (standard TRMNL device). Pass ``width`` and
``content_height`` to ``render_calendar_week_preview`` to render at the device's
actual reported resolution; the server composites the result into a full frame
with a footer strip.
"""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta

from PIL import Image, ImageDraw

from . import trmnl_display_canvas as _canvas


WIDTH = _canvas.DISPLAY_WIDTH
HEIGHT = _canvas.CONTENT_HEIGHT
TIME_COL_W = 54
WEEK_HDR_H = 26
DAY_HDR_H = 32
HEADER_H = WEEK_HDR_H + DAY_HDR_H

GRID_TOP = HEADER_H
GRID_H = HEIGHT - GRID_TOP

HOUR_START = 7
HOUR_END = 19
HOURS = HOUR_END - HOUR_START
HOUR_H_F = GRID_H / HOURS

WHITE = _canvas.EINK_WHITE
BLACK = _canvas.EINK_BLACK
GRAY_BAND = 250
GRAY_GRID = _canvas.EINK_RULE
GRAY_MUTED = _canvas.EINK_INK_SOFT
GRAY_EVENT = 68
GRAY_EVENT_OUTLINE = _canvas.EINK_INK
TITLE_BAND = 252
TITLE_RULE = _canvas.EINK_RULE_FAINT
TODAY_HDR_FILL = 240

DAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


_FONTS: tuple | None = None


def _get_fonts() -> tuple:
    global _FONTS
    if _FONTS is None:
        _FONTS = (
            _canvas.load_font(16, bold=True),
            _canvas.load_font(12),
            _canvas.load_font(9),
            _canvas.load_font(10),
        )
    return _FONTS


def _trunc(draw: ImageDraw.ImageDraw, text: str, font, max_px: int) -> str:
    if _canvas.text_width(draw, text, font) <= max_px:
        return text
    while text and _canvas.text_width(draw, text + "…", font) > max_px:
        text = text[:-1]
    return (text + "…") if text else ""


def _col_x(col: int, col_w: int) -> int:
    return TIME_COL_W + col * col_w


def _col_right(col: int, col_w: int, num_days: int, width: int) -> int:
    return width if col == num_days - 1 else TIME_COL_W + (col + 1) * col_w


def _y_for_time(hour: int, minute: int, grid_top: int, hour_h_f: float) -> int:
    frac = max(0.0, min(float(HOURS), (hour - HOUR_START) + minute / 60.0))
    return grid_top + int(frac * hour_h_f)


def render_calendar_week_preview(
    events: list[dict],
    week_start: date,
    week_mode: str,
    *,
    width: int | None = None,
    content_height: int | None = None,
) -> bytes:
    """Render a week-view calendar as a grayscale PNG.

    Defaults to 800×CONTENT_HEIGHT. Pass *width* and *content_height* from the
    linked device record to render at the device's actual resolution.
    """
    f_title, f_day, f_time, f_event = _get_fonts()

    w = width or WIDTH
    h = content_height or HEIGHT
    grid_h = h - GRID_TOP
    hour_h_f = grid_h / HOURS

    num_days = 5 if week_mode == "work_week" else 7
    col_w = (w - TIME_COL_W) // num_days

    img = Image.new("L", (w, h), WHITE)
    draw = ImageDraw.Draw(img)

    today = date.today()
    _, iso_week, _ = week_start.isocalendar()

    draw.rectangle([0, 0, w - 1, WEEK_HDR_H - 1], fill=TITLE_BAND)
    title = f"Week {iso_week}  ·  {week_start.strftime('%B %Y')}"
    tw = _canvas.text_width(draw,title, f_title)
    tb = draw.textbbox((0, 0), title, font=f_title)
    th = tb[3] - tb[1]
    draw.text(
        ((w - tw) // 2, (WEEK_HDR_H - th) // 2 - tb[1]),
        title,
        fill=BLACK,
        font=f_title,
    )
    draw.line([(0, WEEK_HDR_H - 1), (w - 1, WEEK_HDR_H - 1)], fill=TITLE_RULE, width=1)

    hdr_y = WEEK_HDR_H
    for col in range(num_days):
        d = week_start + timedelta(days=col)
        cx = _col_x(col, col_w)
        cr = _col_right(col, col_w, num_days, w)
        cw = cr - cx

        is_today = d == today
        label = f"{DAY_ABBR[col]}  {d.day}"
        lw = _canvas.text_width(draw,label, f_day)
        db = draw.textbbox((0, 0), label, font=f_day)
        dh = db[3] - db[1]
        text_x = cx + (cw - lw) // 2
        text_y = hdr_y + (DAY_HDR_H - dh) // 2 - db[1]

        if is_today:
            draw.rectangle(
                [cx + 1, hdr_y + 1, cr - 2, hdr_y + DAY_HDR_H - 2],
                fill=TODAY_HDR_FILL,
                outline=GRAY_EVENT_OUTLINE,
                width=1,
            )
        draw.text((text_x, text_y), label, fill=BLACK, font=f_day)

    for hour_i in range(HOURS):
        actual = HOUR_START + hour_i
        if actual % 2 == 0:
            y = _y_for_time(actual, 0, GRID_TOP, hour_h_f)
            y_next = _y_for_time(actual + 1, 0, GRID_TOP, hour_h_f)
            draw.rectangle([TIME_COL_W, y, w - 1, y_next - 1], fill=GRAY_BAND)

    for hour_i in range(HOURS + 1):
        actual = HOUR_START + hour_i
        y = _y_for_time(actual, 0, GRID_TOP, hour_h_f)
        label = f"{actual:02d}:00"
        lw = _canvas.text_width(draw,label, f_time)
        tb = draw.textbbox((0, 0), label, font=f_time)
        draw.text(
            (TIME_COL_W - lw - 5, y + 2 - tb[1]),
            label,
            fill=GRAY_MUTED,
            font=f_time,
        )
        draw.line([(TIME_COL_W, y), (w - 1, y)], fill=GRAY_GRID, width=1)

    for col in range(num_days + 1):
        x = _col_x(col, col_w) if col < num_days else w - 1
        draw.line([(x, GRID_TOP), (x, GRID_TOP + grid_h)], fill=GRAY_GRID, width=1)

    draw.line([(TIME_COL_W, HEADER_H), (TIME_COL_W, h - 1)], fill=GRAY_GRID, width=1)

    ev_pad = 3
    ev_min_h = 14
    for ev in events:
        start_dt = ev.get("start_datetime")
        end_dt = ev.get("end_datetime")

        if not isinstance(start_dt, datetime) or not isinstance(end_dt, datetime):
            continue

        col_idx = (start_dt.date() - week_start).days
        if col_idx < 0 or col_idx >= num_days:
            continue

        start_min = start_dt.hour * 60 + start_dt.minute
        end_min = end_dt.hour * 60 + end_dt.minute
        if end_min <= HOUR_START * 60 or start_min >= HOUR_END * 60:
            continue

        cx = _col_x(col_idx, col_w) + ev_pad
        cr = _col_right(col_idx, col_w, num_days, w) - ev_pad

        y_top = _y_for_time(start_dt.hour, start_dt.minute, GRID_TOP, hour_h_f)
        y_bot = _y_for_time(end_dt.hour, end_dt.minute, GRID_TOP, hour_h_f)
        y_top = max(y_top, GRID_TOP)
        y_bot = min(y_bot, GRID_TOP + grid_h)
        y_bot = max(y_bot, y_top + ev_min_h)

        draw.rectangle(
            [cx, y_top, cr - 1, y_bot - 1],
            fill=GRAY_EVENT,
            outline=GRAY_EVENT_OUTLINE,
            width=1,
        )
        label = f"{start_dt.strftime('%H:%M')} {ev.get('title', '')}".strip()
        draw.text(
            (cx + 3, y_top + 3),
            _trunc(draw, label, f_event, cr - cx - 8),
            fill=WHITE,
            font=f_event,
        )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
