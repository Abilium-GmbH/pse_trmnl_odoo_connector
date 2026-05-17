"""Pure-Pillow month-view calendar renderer for TRMNL e-ink.

No Odoo ORM imports. Receives plain Python data, returns PNG bytes. The Odoo
profile model handles all data loading and passes pre-processed event dicts here.

Defaults to 800×CONTENT_HEIGHT (standard TRMNL device). Pass ``width`` and
``content_height`` to ``render_calendar_preview`` to render at the device's
actual reported resolution; the server composites the result into a full frame
with a footer strip.
"""
from __future__ import annotations

import calendar
import io
from datetime import date

from PIL import Image, ImageDraw

from . import trmnl_display_canvas as _canvas


# ── Canvas constants (geometry fixed for tests: GRID_TOP = HEADER_H + DOW_H) ─

WIDTH = _canvas.DISPLAY_WIDTH
HEIGHT = _canvas.CONTENT_HEIGHT
HEADER_H = 36
DOW_H = 24
COLS = 7
MAX_ROWS = 6
COL_W = WIDTH // COLS
GRID_TOP = HEADER_H + DOW_H

# Grid lines must stay at 180 for pixel-based tests (test_calendar_month_renderer).
GRAY_GRID = 180

WHITE = _canvas.EINK_WHITE
BLACK = _canvas.EINK_BLACK
GRAY_MUTED = _canvas.EINK_INK_SOFT
DOW_BAND = 252
TITLE_RULE = _canvas.EINK_RULE_FAINT

# Out-of-month padding cells (QWeb-style muted background on e-ink).
_OUT_FILL = 232
_OUT_LINE = 188
_OUT_HATCH_STEP = 4

TODAY_FILL = 242
TODAY_OUTLINE = _canvas.EINK_INK

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


_FONTS: tuple | None = None


def _get_fonts() -> tuple:
    global _FONTS
    if _FONTS is None:
        _FONTS = (
            _canvas.load_font(23, bold=True),
            _canvas.load_font(10),
            _canvas.load_font(14, bold=True),
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
    return col * col_w


def _col_right(col: int, col_w: int, width: int) -> int:
    return width if col == COLS - 1 else (col + 1) * col_w


def _fill_out_of_month_cell(img: Image.Image, x0: int, y0: int, x1: int, y1: int) -> None:
    """Gray cell with tight diagonal crossing lines (leading/trailing month padding)."""
    w = x1 - x0 + 1
    h = y1 - y0 + 1
    patch = Image.new("L", (w, h), _OUT_FILL)
    pdraw = ImageDraw.Draw(patch)
    step = _OUT_HATCH_STEP
    for offset in range(-h, w, step):
        pdraw.line([(offset, 0), (offset + h, h - 1)], fill=_OUT_LINE)
    for offset in range(0, w + h, step):
        pdraw.line([(0, offset), (w - 1, offset - w + 1)], fill=_OUT_LINE)
    img.paste(patch, (x0, y0))


def render_calendar_preview(
    events: list[dict],
    year: int,
    month: int,
    *,
    width: int | None = None,
    content_height: int | None = None,
) -> bytes:
    """Render a month-view calendar as a grayscale PNG.

    Defaults to 800×CONTENT_HEIGHT. Pass *width* and *content_height* from the
    linked device record to render at the device's actual resolution.
    """
    f_title, f_dow, f_daynum, f_event = _get_fonts()

    w = width or WIDTH
    h = content_height or HEIGHT
    col_w = w // COLS

    img = Image.new("L", (w, h), WHITE)
    draw = ImageDraw.Draw(img)

    today = date.today()

    by_date: dict[date, list[dict]] = {}
    for ev in events:
        d = ev.get("start")
        if isinstance(d, date):
            by_date.setdefault(d, []).append(ev)

    # Month/year title
    title_text = date(year, month, 1).strftime("%B %Y")
    tw = _canvas.text_width(draw,title_text, f_title)
    tb = draw.textbbox((0, 0), title_text, font=f_title)
    th = tb[3] - tb[1]
    draw.text(
        ((w - tw) // 2, (HEADER_H - th) // 2 - tb[1]),
        title_text,
        fill=BLACK,
        font=f_title,
    )
    draw.line([(0, HEADER_H - 1), (w - 1, HEADER_H - 1)], fill=TITLE_RULE, width=1)

    # DOW band (metadata hierarchy — lighter than main grid)
    draw.rectangle([0, HEADER_H, w - 1, GRID_TOP - 1], fill=DOW_BAND)
    for col, label in enumerate(DAY_NAMES):
        cx = _col_x(col, col_w)
        cw = _col_right(col, col_w, w) - cx
        lw = _canvas.text_width(draw,label, f_dow)
        db = draw.textbbox((0, 0), label, font=f_dow)
        dh = db[3] - db[1]
        draw.text(
            (cx + (cw - lw) // 2, HEADER_H + (DOW_H - dh) // 2 - db[1]),
            label,
            fill=GRAY_MUTED,
            font=f_dow,
        )

    weeks = calendar.monthcalendar(year, month)
    while weeks and not any(weeks[-1]):
        weeks.pop()
    n_rows = len(weeks)
    row_h = (h - GRID_TOP) // n_rows

    cell_pad_x = 6
    day_num_top_pad = 3
    pad_cells: list[tuple[int, int, int, int]] = []

    for row_i, week in enumerate(weeks):
        for col_i, day_num in enumerate(week):
            cx = _col_x(col_i, col_w)
            cright = _col_right(col_i, col_w, w)
            cw = cright - cx
            cy = GRID_TOP + row_i * row_h
            cell_box = (cx, cy, cright - 1, cy + row_h - 1)

            out_of_month = day_num == 0
            is_today = not out_of_month and date(year, month, day_num) == today

            if out_of_month:
                pad_cells.append(cell_box)
                _fill_out_of_month_cell(img, *cell_box)
                continue

            draw.rectangle([*cell_box], fill=WHITE)

            if is_today:
                pad_x, pad_y = 3, 2
                box = [cx + pad_x, cy + pad_y, cright - 1 - pad_x, cy + 20]
                draw.rectangle(box, fill=TODAY_FILL, outline=TODAY_OUTLINE, width=1)

            dstr = str(day_num)
            dbn = draw.textbbox((0, 0), dstr, font=f_daynum)
            dnh = dbn[3] - dbn[1]
            dnx = cx + cell_pad_x
            dny = cy + day_num_top_pad + max(0, (18 - dnh) // 2) - dbn[1]
            draw.text((dnx, dny), dstr, fill=BLACK, font=f_daynum)

            d = date(year, month, day_num)
            day_events = by_date.get(d, [])
            if not day_events:
                continue

            # Match legacy vertical metrics so event ink lands near (cx+6, cy+22) for tests.
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
                    _trunc(draw, label, f_event, max_lbl_ev),
                    fill=BLACK,
                    font=f_event,
                )

            overflow = len(day_events) - max_ev
            if overflow > 0:
                more = _trunc(draw, f"+{overflow} more", f_event, max_lbl_ev)
                draw.text(
                    (cx + 4, ev_y0 + max_ev * event_line_h),
                    more,
                    fill=GRAY_MUTED,
                    font=f_event,
                )

    for r in range(n_rows + 1):
        y = GRID_TOP + r * row_h
        draw.line([(0, y), (w - 1, y)], fill=GRAY_GRID, width=1)
    for c in range(1, COLS):
        x = _col_x(c, col_w)
        draw.line([(x, GRID_TOP), (x, GRID_TOP + n_rows * row_h)], fill=GRAY_GRID, width=1)

    # Grid lines are drawn on top of cell fills; re-paint padding cells so hatch
    # stays visible on e-ink (matches old QWeb greyed-out out-of-month <td> cells).
    for cell_box in pad_cells:
        _fill_out_of_month_cell(img, *cell_box)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
