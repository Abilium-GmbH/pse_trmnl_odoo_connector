from datetime import datetime, timedelta, date, time
from PIL import Image, ImageDraw, ImageFont
import io


class CalendarProvider:

    def fetch_data(self, env, profile):
        if profile.calendar_view_mode == "month":
            return self._fetch_month_data(env)
        return self._fetch_week_data(env)

    def _fetch_month_data(self, env):
        today = date.today()
        year = today.year
        month = today.month

        month_start = date(year, month, 1)

        # Monday-based calendar grid start
        first_weekday = month_start.weekday()  # Monday = 0
        grid_start = month_start - timedelta(days=first_weekday)

        # 6 weeks x 7 days = 42 cells
        grid_end = grid_start + timedelta(days=41)

        events = env["calendar.event"].search([
            ("start", ">=", datetime.combine(grid_start, time.min)),
            ("start", "<=", datetime.combine(grid_end, time.max)),
        ], order="start asc")

        events_by_day = {}
        for event in events:
            event_start = event.start
            if isinstance(event_start, str):
                continue

            event_date = event_start.date()
            events_by_day.setdefault(event_date, []).append({
                "name": event.name or "",
                "start": event_start,
            })

        weeks = []
        current = grid_start

        for _ in range(6):
            week = []
            for _ in range(7):
                day_events = events_by_day.get(current, [])
                week.append({
                    "date": current,
                    "day": current.day,
                    "in_month": current.month == month,
                    "is_today": current == today,
                    "events": day_events[:2],
                    "extra_count": max(0, len(day_events) - 2),
                })
                current += timedelta(days=1)
            weeks.append(week)

        return {
            "mode": "month",
            "title": today.strftime("%B %Y"),
            "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
            "weeks": weeks,
        }

    def _fetch_week_data(self, env):
        today = date.today()
        week_start = today - timedelta(days=today.weekday())  # Monday
        week_end = week_start + timedelta(days=6)

        events = env["calendar.event"].search([
            ("start", ">=", datetime.combine(week_start, time.min)),
            ("start", "<=", datetime.combine(week_end, time.max)),
        ], order="start asc")

        events_by_day = {}
        for event in events:
            event_start = event.start
            if isinstance(event_start, str):
                continue

            event_date = event_start.date()
            events_by_day.setdefault(event_date, []).append({
                "name": event.name or "",
                "start": event_start,
            })

        days = []
        current = week_start
        weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

        for idx in range(7):
            day_events = events_by_day.get(current, [])
            days.append({
                "date": current,
                "weekday": weekday_labels[idx],
                "day": current.day,
                "is_today": current == today,
                "events": day_events[:5],
                "extra_count": max(0, len(day_events) - 5),
            })
            current += timedelta(days=1)

        return {
            "mode": "week",
            "title": f"Week of {week_start.strftime('%d %b %Y')}",
            "days": days,
        }

    def render(self, data, profile):
        if profile.calendar_view_mode == "month":
            return self._render_month(data)
        return self._render_week(data)

    def _render_month(self, data):
        width, height = 800, 480
        img = Image.new("L", (width, height), 255)
        draw = ImageDraw.Draw(img)

        try:
            title_font = ImageFont.truetype("DejaVuSans.ttf", 24)
            header_font = ImageFont.truetype("DejaVuSans.ttf", 16)
            day_font = ImageFont.truetype("DejaVuSans.ttf", 14)
            event_font = ImageFont.truetype("DejaVuSans.ttf", 11)
        except Exception:
            title_font = ImageFont.load_default()
            header_font = ImageFont.load_default()
            day_font = ImageFont.load_default()
            event_font = ImageFont.load_default()

        margin = 20
        title_h = 32
        weekday_h = 24
        gap_after_weekdays = 8

        grid_left = margin
        grid_top = margin + title_h + weekday_h + gap_after_weekdays
        grid_width = width - (2 * margin)
        grid_height = height - grid_top - margin

        cell_w = grid_width // 7
        cell_h = grid_height // 6

        draw.text((margin, margin), data["title"], fill=0, font=title_font)

        weekday_y = margin + title_h
        for idx, day_name in enumerate(data["weekdays"]):
            x = grid_left + idx * cell_w + 6
            draw.text((x, weekday_y), day_name, fill=0, font=header_font)

        for row in range(7):
            y = grid_top + row * cell_h
            draw.line((grid_left, y, grid_left + 7 * cell_w, y), fill=0, width=1)

        for col in range(8):
            x = grid_left + col * cell_w
            draw.line((x, grid_top, x, grid_top + 6 * cell_h), fill=0, width=1)

        for row_idx, week in enumerate(data["weeks"]):
            for col_idx, day in enumerate(week):
                x = grid_left + col_idx * cell_w
                y = grid_top + row_idx * cell_h

                if day["is_today"]:
                    draw.rectangle(
                        (x + 1, y + 1, x + cell_w - 1, y + cell_h - 1),
                        outline=0,
                        width=2,
                    )

                day_fill = 0 if day["in_month"] else 160
                draw.text((x + 4, y + 2), str(day["day"]), fill=day_fill, font=day_font)

                text_y = y + 20
                for event in day["events"]:
                    start = event["start"]
                    time_text = ""
                    if hasattr(start, "strftime"):
                        time_text = start.strftime("%H:%M ")

                    label = f"{time_text}{event['name']}".strip()
                    if len(label) > 14:
                        label = label[:13] + "…"

                    draw.text((x + 4, text_y), label, fill=0, font=event_font)
                    text_y += 12

                if day["extra_count"] > 0:
                    draw.text(
                        (x + 4, text_y),
                        f"+{day['extra_count']}",
                        fill=0,
                        font=event_font,
                    )

        img = img.point(lambda p: 255 if p > 128 else 0, mode="1")

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()

    def _render_week(self, data):
        width, height = 800, 480
        img = Image.new("L", (width, height), 255)
        draw = ImageDraw.Draw(img)

        try:
            title_font = ImageFont.truetype("DejaVuSans.ttf", 24)
            header_font = ImageFont.truetype("DejaVuSans.ttf", 15)
            day_font = ImageFont.truetype("DejaVuSans.ttf", 13)
            event_font = ImageFont.truetype("DejaVuSans.ttf", 11)
        except Exception:
            title_font = ImageFont.load_default()
            header_font = ImageFont.load_default()
            day_font = ImageFont.load_default()
            event_font = ImageFont.load_default()

        margin = 20
        title_h = 32
        grid_top = margin + title_h + 10
        grid_left = margin
        grid_width = width - (2 * margin)
        grid_height = height - grid_top - margin

        col_w = grid_width // 7

        draw.text((margin, margin), data["title"], fill=0, font=title_font)

        for col in range(8):
            x = grid_left + col * col_w
            draw.line((x, grid_top, x, grid_top + grid_height), fill=0, width=1)

        draw.line((grid_left, grid_top, grid_left + 7 * col_w, grid_top), fill=0, width=1)
        draw.line(
            (grid_left, grid_top + grid_height, grid_left + 7 * col_w, grid_top + grid_height),
            fill=0,
            width=1,
        )

        for idx, day in enumerate(data["days"]):
            x = grid_left + idx * col_w
            y = grid_top

            if day["is_today"]:
                draw.rectangle(
                    (x + 1, y + 1, x + col_w - 1, y + grid_height - 1),
                    outline=0,
                    width=2,
                )

            header_text = f"{day['weekday']} {day['day']}"
            draw.text((x + 4, y + 4), header_text, fill=0, font=header_font)

            text_y = y + 24
            for event in day["events"]:
                start = event["start"]
                time_text = ""
                if hasattr(start, "strftime"):
                    time_text = start.strftime("%H:%M ")

                label = f"{time_text}{event['name']}".strip()
                if len(label) > 12:
                    label = label[:11] + "…"

                draw.text((x + 4, text_y), label, fill=0, font=event_font)
                text_y += 14

            if day["extra_count"] > 0:
                draw.text(
                    (x + 4, text_y),
                    f"+{day['extra_count']}",
                    fill=0,
                    font=event_font,
                )

        img = img.point(lambda p: 255 if p > 128 else 0, mode="1")

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()