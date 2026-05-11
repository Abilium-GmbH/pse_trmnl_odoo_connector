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


# ── Canvas constants ─────────────────────────────────────────────────────────

WIDTH = _canvas.DISPLAY_WIDTH
HEIGHT = _canvas.CONTENT_HEIGHT
HEADER_H      = 36                      # "Month Year" title strip
DOW_H         = 24                      # Mon–Sun label row
COLS          = 7
MAX_ROWS      = 6                       # upper bound; actual row count is dynamic
COL_W         = WIDTH // COLS           # 114 px (last col absorbs 2px remainder)
GRID_TOP      = HEADER_H + DOW_H        # 60 px from top
# ROW_H is computed dynamically inside render_calendar_preview based on n_rows

# Grayscale palette
WHITE      = 255
BLACK      = 0
GRAY_GRID  = 180   # grid lines
GRAY_MUTED = 110   # day-of-week labels and "+N more" text

# Out-of-month cells: light gray base + tighter diagonal crosshatch (e-ink).
_OUT_BASE   = 247
_OUT_HATCH1 = 9   # primary diagonal tone step
_OUT_HATCH2 = 6   # secondary diagonal (kariert)
_OUT_SPACING = 6  # line spacing (smaller = denser, more “muted”)
_OUT_FLOOR  = 216  # keep floor light enough for readability if lines intersect

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ── Fonts ────────────────────────────────────────────────────────────────────

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
            _load_font(20, bold=True),   # month+year header
            _load_font(12),              # Mon/Tue/... day-of-week labels
            _load_font(13, bold=True),   # day number in each cell
            _load_font(11),              # event text
        )
    return _FONTS


# ── Drawing helpers ───────────────────────────────────────────────────────────

def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    """Text pixel width, compatible with Pillow ≥ 9 and older."""
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
    """Right edge — last column absorbs the 2px width remainder."""
    return WIDTH if col == COLS - 1 else (col + 1) * COL_W


def _fill_out_of_month_cell(img: Image.Image, x0: int, y0: int, x1: int, y1: int) -> None:
    """Tighter diagonal crosshatch than in-month white (muted / disabled look on e-ink)."""
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


# ── Renderer ─────────────────────────────────────────────────────────────────

def render_calendar_preview(
    events: list[dict],
    year: int,
    month: int,
) -> bytes:
    """Render a month-view calendar as an 800×CONTENT_HEIGHT grayscale PNG.

    Args:
        events:      List of dicts. Each must contain:
                       "start"    – datetime.date of the event day
                       "title"    – str event title
                       "time_str" – "HH:MM" string or empty string
        year, month: The month to display. Events outside the month are ignored.

    Returns:
        Raw PNG bytes.
    """
    f_title, f_dow, f_daynum, f_event = _get_fonts()

    img  = Image.new("L", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)

    today = date.today()

    # Index events by their start date for O(1) per-cell lookup.
    by_date: dict[date, list[dict]] = {}
    for ev in events:
        d = ev.get("start")
        if isinstance(d, date):
            by_date.setdefault(d, []).append(ev)

    # ── Month/year title ─────────────────────────────────────────────────
    title_text = date(year, month, 1).strftime("%B %Y")
    tw = _text_w(draw, title_text, f_title)
    draw.text(((WIDTH - tw) // 2, (HEADER_H - 20) // 2), title_text,
              fill=BLACK, font=f_title)

    # ── Day-of-week header row ───────────────────────────────────────────
    for col, label in enumerate(DAY_NAMES):
        cx = _col_x(col)
        cw = _col_right(col) - cx
        lw = _text_w(draw, label, f_dow)
        draw.text((cx + (cw - lw) // 2, HEADER_H + 5), label,
                  fill=GRAY_MUTED, font=f_dow)

    # ── Day cells ────────────────────────────────────────────────────────
    # monthcalendar() returns Mon–Sun weeks as lists of 7 ints; 0 means outside
    # the displayed month. Python already returns 4–6 rows with no trailing
    # all-zero week for real months; we still strip any trailing [0,…,0] rows
    # defensively so row height is shared only across real week rows.
    weeks = calendar.monthcalendar(year, month)
    while weeks and not any(weeks[-1]):
        weeks.pop()
    n_rows = len(weeks)              # 4, 5, or 6 depending on the month
    row_h  = (HEIGHT - GRID_TOP) // n_rows

    for row_i, week in enumerate(weeks):
        for col_i, day_num in enumerate(week):
            cx     = _col_x(col_i)
            cright = _col_right(col_i)
            cw     = cright - cx
            cy     = GRID_TOP + row_i * row_h

            out_of_month = (day_num == 0)
            is_today     = (not out_of_month and date(year, month, day_num) == today)

            if out_of_month:
                _fill_out_of_month_cell(img, cx, cy, cright - 1, cy + row_h - 1)
                continue

            # Current-month cell: clean white
            draw.rectangle(
                [cx, cy, cright - 1, cy + row_h - 1],
                fill=WHITE,
            )

            # Today: solid black strip behind the day number
            if is_today:
                draw.rectangle([cx, cy, cright - 1, cy + 17], fill=BLACK)

            draw.text(
                (cx + 4, cy + 2), str(day_num),
                fill=WHITE if is_today else BLACK, font=f_daynum,
            )

            # Events for this day
            d = date(year, month, day_num)
            day_events = by_date.get(d, [])
            if not day_events:
                continue

            # day number strip ≈ 19 px; each event line is 13 px
            max_ev  = (row_h - 20) // 13
            ev_y    = cy + 19
            max_lbl = cw - 8

            for i, ev in enumerate(day_events[:max_ev]):
                time_str = ev.get("time_str", "")
                ev_title = ev.get("title", "")
                label = f"{time_str} {ev_title}".strip() if time_str else ev_title
                draw.text(
                    (cx + 4, ev_y + i * 13),
                    _trunc(draw, label, f_event, max_lbl),
                    fill=BLACK, font=f_event,
                )

            overflow = len(day_events) - max_ev
            if overflow > 0:
                more = _trunc(draw, f"+{overflow} more", f_event, max_lbl)
                draw.text((cx + 4, ev_y + max_ev * 13), more,
                          fill=GRAY_MUTED, font=f_event)

    # ── Grid lines (drawn last so they sit on top of all fills) ──────────
    for r in range(n_rows + 1):
        y = GRID_TOP + r * row_h
        draw.line([(0, y), (WIDTH - 1, y)], fill=GRAY_GRID, width=1)
    for c in range(1, COLS):
        x = _col_x(c)
        draw.line([(x, GRID_TOP), (x, GRID_TOP + n_rows * row_h)],
                  fill=GRAY_GRID, width=1)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
