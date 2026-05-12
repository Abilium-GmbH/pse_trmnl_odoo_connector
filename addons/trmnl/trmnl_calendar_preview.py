"""Pure-Pillow month-view calendar renderer for TRMNL e-ink.

Renders into the profile content strip (800×CONTENT_HEIGHT). The server
composites a footer to produce the final 800×480 device image.

No Odoo ORM imports. Receives plain Python data, returns PNG bytes.
"""
from __future__ import annotations

import calendar
import io
from datetime import date

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:
    raise ImportError("Pillow is required: pip install Pillow") from exc

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

# Out-of-month: tight diagonal hatch (clearly muted vs in-month white).
_OUT_BASE = 249
_OUT_HATCH1 = 10
_OUT_HATCH2 = 7
_OUT_SPACING = 3
_OUT_FLOOR = 210

TODAY_FILL = 242
TODAY_OUTLINE = _canvas.EINK_INK

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    suffix = "-Bold" if bold else ""
    candidates = [
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{suffix}.ttf",
        f"/usr/share/fonts/truetype/liberation/LiberationSans{suffix}.ttf",
        f"/usr/share/fonts/truetype/freefont/FreeSans{'Bold' if bold else ''}.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


_FONTS: tuple | None = None


def _get_fonts() -> tuple:
    global _FONTS
    if _FONTS is None:
        _FONTS = (
            _load_font(23, bold=True),
            _load_font(10),
            _load_font(14, bold=True),
            _load_font(10),
        )
    return _FONTS


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    try:
        return int(draw.textlength(text, font=font))
    except AttributeError:
        return draw.textsize(text, font=font)[0]


def _trunc(draw: ImageDraw.ImageDraw, text: str, font, max_px: int) -> str:
    if _text_w(draw, text, font) <= max_px:
        return text
    while text and _text_w(draw, text + "…", font) > max_px:
        text = text[:-1]
    return (text + "…") if text else ""


def _col_x(col: int) -> int:
    return col * COL_W


def _col_right(col: int) -> int:
    return WIDTH if col == COLS - 1 else (col + 1) * COL_W


def _fill_out_of_month_cell(img: Image.Image, x0: int, y0: int, x1: int, y1: int) -> None:
    """Dense diagonal crosshatch — clearly muted vs in-month cells on e-ink."""
    px = img.load()
    s = _OUT_SPACING
    for yy in range(y0, y1 + 1):
        for xx in range(x0, x1 + 1):
            v = _OUT_BASE
            dx, dy = xx - x0, yy - y0
            if (dx + dy) % s == 0:
                v -= _OUT_HATCH1
            if (dx - dy) % s == 0:
                v -= _OUT_HATCH2
            if v < _OUT_FLOOR:
                v = _OUT_FLOOR
            px[xx, yy] = v


def render_calendar_preview(
    events: list[dict],
    year: int,
    month: int,
) -> bytes:
    """Render a month-view calendar as an 800×CONTENT_HEIGHT grayscale PNG."""
    f_title, f_dow, f_daynum, f_event = _get_fonts()

    img = Image.new("L", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)

    today = date.today()

    by_date: dict[date, list[dict]] = {}
    for ev in events:
        d = ev.get("start")
        if isinstance(d, date):
            by_date.setdefault(d, []).append(ev)

    # Month/year title
    title_text = date(year, month, 1).strftime("%B %Y")
    tw = _text_w(draw, title_text, f_title)
    tb = draw.textbbox((0, 0), title_text, font=f_title)
    th = tb[3] - tb[1]
    draw.text(
        ((WIDTH - tw) // 2, (HEADER_H - th) // 2 - tb[1]),
        title_text,
        fill=BLACK,
        font=f_title,
    )
    draw.line([(0, HEADER_H - 1), (WIDTH - 1, HEADER_H - 1)], fill=TITLE_RULE, width=1)

    # DOW band (metadata hierarchy — lighter than main grid)
    draw.rectangle([0, HEADER_H, WIDTH - 1, GRID_TOP - 1], fill=DOW_BAND)
    for col, label in enumerate(DAY_NAMES):
        cx = _col_x(col)
        cw = _col_right(col) - cx
        lw = _text_w(draw, label, f_dow)
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
    row_h = (HEIGHT - GRID_TOP) // n_rows

    cell_pad_x = 6
    day_num_top_pad = 3

    for row_i, week in enumerate(weeks):
        for col_i, day_num in enumerate(week):
            cx = _col_x(col_i)
            cright = _col_right(col_i)
            cw = cright - cx
            cy = GRID_TOP + row_i * row_h

            out_of_month = day_num == 0
            is_today = not out_of_month and date(year, month, day_num) == today

            if out_of_month:
                _fill_out_of_month_cell(img, cx, cy, cright - 1, cy + row_h - 1)
                continue

            draw.rectangle([cx, cy, cright - 1, cy + row_h - 1], fill=WHITE)

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
        draw.line([(0, y), (WIDTH - 1, y)], fill=GRAY_GRID, width=1)
    for c in range(1, COLS):
        x = _col_x(c)
        draw.line([(x, GRID_TOP), (x, GRID_TOP + n_rows * row_h)], fill=GRAY_GRID, width=1)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
