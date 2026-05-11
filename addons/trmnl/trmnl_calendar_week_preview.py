"""Pure-Pillow week-view calendar renderer for TRMNL (800×480 e-ink).

No Odoo imports. Receives plain Python data, returns PNG bytes.
"""
from __future__ import annotations

import io
from datetime import date, datetime, timedelta

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:
    raise ImportError("Pillow is required: pip install Pillow") from exc


# ── Canvas constants ─────────────────────────────────────────────────────────

WIDTH, HEIGHT = 800, 480
TIME_COL_W    = 48           # left column: hour labels
WEEK_HDR_H    = 22           # "Week N · Month Year" title strip
DAY_HDR_H     = 28           # per-day column headers (day name + date)
HEADER_H      = WEEK_HDR_H + DAY_HDR_H   # 50 px total

GRID_TOP      = HEADER_H
GRID_H        = HEIGHT - GRID_TOP         # 430 px

# Visible time range
HOUR_START    = 7             # 07:00
HOUR_END      = 19            # 19:00
HOURS         = HOUR_END - HOUR_START     # 12
HOUR_H_F      = GRID_H / HOURS           # ≈ 35.8 px per hour (float for precision)

# Grayscale palette
WHITE      = 255
BLACK      = 0
GRAY_BAND  = 242   # alternating even-hour band fill
GRAY_GRID  = 180   # grid lines
GRAY_MUTED = 110   # hour labels / secondary text
GRAY_EVENT = 60    # event box fill (dark → white text on top)

DAY_ABBR = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


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
            _load_font(13, bold=True),   # f_title – "Week N · Month Year"
            _load_font(11),              # f_day   – "Mon 11"
            _load_font(9),               # f_time  – "07:00"
            _load_font(10),              # f_event – event text
        )
    return _FONTS


# ── Drawing helpers ───────────────────────────────────────────────────────────

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


def _col_x(col: int, col_w: int) -> int:
    return TIME_COL_W + col * col_w


def _col_right(col: int, col_w: int, num_days: int) -> int:
    """Right edge — last column absorbs any rounding remainder."""
    return WIDTH if col == num_days - 1 else TIME_COL_W + (col + 1) * col_w


def _y_for_time(hour: int, minute: int = 0) -> int:
    """Pixel Y for a time, clamped to the visible grid range."""
    frac = max(0.0, min(float(HOURS), (hour - HOUR_START) + minute / 60.0))
    return GRID_TOP + int(frac * HOUR_H_F)


# ── Renderer ─────────────────────────────────────────────────────────────────

def render_calendar_week_preview(
    events: list[dict],
    week_start: date,
    week_mode: str,
) -> bytes:
    """Render a week-view calendar as an 800×480 grayscale PNG.

    Layout:
        - Top strip:  ISO week number + month/year
        - Header row: day abbreviation + day-of-month per column
        - Grid:       time axis (left) × day columns; hours 07:00–19:00
        - Events:     dark boxes with white text, positioned by start/end time

    Args:
        events:     List of dicts, each with:
                      "title"          – str
                      "start_datetime" – datetime (naive, UTC)
                      "end_datetime"   – datetime (naive, UTC)
        week_start: Monday of the target week (datetime.date).
        week_mode:  "work_week" (Mon–Fri, 5 cols) or "full_week" (Mon–Sun, 7 cols).

    Returns:
        Raw PNG bytes.
    """
    f_title, f_day, f_time, f_event = _get_fonts()

    num_days = 5 if week_mode == "work_week" else 7
    col_w    = (WIDTH - TIME_COL_W) // num_days   # 150 px (work) or 107 px (full)

    img  = Image.new("L", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)

    today = date.today()
    _, iso_week, _ = week_start.isocalendar()

    # ── Week title (full-width strip) ────────────────────────────────────
    title = f"Week {iso_week}  ·  {week_start.strftime('%B %Y')}"
    tw = _text_w(draw, title, f_title)
    draw.text(((WIDTH - tw) // 2, (WEEK_HDR_H - 13) // 2), title,
              fill=BLACK, font=f_title)

    # ── Day column headers ───────────────────────────────────────────────
    hdr_y = WEEK_HDR_H
    for col in range(num_days):
        d  = week_start + timedelta(days=col)
        cx = _col_x(col, col_w)
        cr = _col_right(col, col_w, num_days)
        cw = cr - cx

        is_today = (d == today)
        label    = f"{DAY_ABBR[col]}  {d.day}"
        lw       = _text_w(draw, label, f_day)
        text_x   = cx + (cw - lw) // 2
        text_y   = hdr_y + (DAY_HDR_H - 11) // 2

        if is_today:
            draw.rectangle([cx, hdr_y, cr - 1, hdr_y + DAY_HDR_H - 1], fill=BLACK)
            draw.text((text_x, text_y), label, fill=WHITE, font=f_day)
        else:
            draw.text((text_x, text_y), label, fill=BLACK, font=f_day)

    # ── Alternating hour bands ───────────────────────────────────────────
    for h in range(HOURS):
        actual = HOUR_START + h
        if actual % 2 == 0:
            y      = _y_for_time(actual)
            y_next = _y_for_time(actual + 1)
            draw.rectangle([TIME_COL_W, y, WIDTH - 1, y_next - 1], fill=GRAY_BAND)

    # ── Hour grid lines and time labels ─────────────────────────────────
    for h in range(HOURS + 1):
        actual = HOUR_START + h
        y      = _y_for_time(actual)
        label  = f"{actual:02d}:00"
        lw     = _text_w(draw, label, f_time)
        draw.text((TIME_COL_W - lw - 3, y + 2), label, fill=GRAY_MUTED, font=f_time)
        draw.line([(TIME_COL_W, y), (WIDTH - 1, y)], fill=GRAY_GRID, width=1)

    # ── Vertical column separators ───────────────────────────────────────
    for col in range(num_days + 1):
        x = _col_x(col, col_w) if col < num_days else WIDTH - 1
        draw.line([(x, GRID_TOP), (x, GRID_TOP + GRID_H)], fill=GRAY_GRID, width=1)

    # Time-axis separator
    draw.line([(TIME_COL_W, HEADER_H), (TIME_COL_W, HEIGHT - 1)], fill=GRAY_GRID, width=1)

    # ── Events ───────────────────────────────────────────────────────────
    for ev in events:
        start_dt = ev.get("start_datetime")
        end_dt   = ev.get("end_datetime")

        if not isinstance(start_dt, datetime) or not isinstance(end_dt, datetime):
            continue

        # Day column
        col_idx = (start_dt.date() - week_start).days
        if col_idx < 0 or col_idx >= num_days:
            continue

        # Skip events entirely outside the visible time range
        start_min = start_dt.hour * 60 + start_dt.minute
        end_min   = end_dt.hour   * 60 + end_dt.minute
        if end_min <= HOUR_START * 60 or start_min >= HOUR_END * 60:
            continue

        cx = _col_x(col_idx, col_w) + 2
        cr = _col_right(col_idx, col_w, num_days) - 2

        y_top = _y_for_time(start_dt.hour, start_dt.minute)
        y_bot = _y_for_time(end_dt.hour,   end_dt.minute)
        y_top = max(y_top, GRID_TOP)
        y_bot = min(y_bot, GRID_TOP + GRID_H)
        y_bot = max(y_bot, y_top + 12)   # enforce minimum height

        # Event box (dark fill, white text)
        draw.rectangle([cx, y_top, cr - 1, y_bot - 1], fill=GRAY_EVENT)
        label = f"{start_dt.strftime('%H:%M')} {ev.get('title', '')}".strip()
        draw.text(
            (cx + 2, y_top + 2),
            _trunc(draw, label, f_event, cr - cx - 6),
            fill=WHITE, font=f_event,
        )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
