from datetime import datetime, timedelta, date, time
from PIL import Image, ImageDraw, ImageFont
import io


class CalendarProvider:

    def fetch_data(self, env, profile):
        if profile.calendar_view_mode == "month":
            return self._fetch_month_data(env)
        return self._fetch_week_data(env)

    # MONTH DATA
    def _fetch_month_data(self, env):
        today = date.today()
        year = today.year
        month = today.month

        month_start = date(year, month, 1)
        first_weekday = month_start.weekday()
        grid_start = month_start - timedelta(days=first_weekday)
        grid_end = grid_start + timedelta(days=41)

        events = env["calendar.event"].search([
            ("start", ">=", datetime.combine(grid_start, time.min)),
            ("start", "<=", datetime.combine(grid_end, time.max)),
        ], order="start asc")

        events_by_day = {}
        for event in events:
            if isinstance(event.start, str):
                continue
            d = event.start.date()
            events_by_day.setdefault(d, []).append({
                "name": event.name or "",
                "start": event.start,
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

    # WEEK DATA
    def _fetch_week_data(self, env):
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)

        events = env["calendar.event"].search([
            ("start", "<=", datetime.combine(week_end, time.max)),
            ("stop", ">=", datetime.combine(week_start, time.min)),
        ], order="start asc")

        events_by_day = {week_start + timedelta(days=i): [] for i in range(7)}

        for event in events:
            start = event.start
            end = getattr(event, "stop", None) or getattr(event, "end", None)

            if isinstance(start, str) or not start:
                continue
            if isinstance(end, str) or not end:
                end = start + timedelta(hours=1)

            d = max(start.date(), week_start)
            last = min(end.date(), week_end)

            while d <= last:
                day_start = datetime.combine(d, time.min)
                day_end = datetime.combine(d, time.max)

                visible_start = max(start, day_start)
                visible_end = min(end, day_end)

                if visible_start < visible_end:
                    events_by_day[d].append({
                        "name": event.name or "",
                        "start": visible_start,
                        "end": visible_end,
                    })

                d += timedelta(days=1)

        weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        days = []
        current = week_start

        for i in range(7):
            events = sorted(events_by_day[current], key=lambda e: (e["start"], e["end"]))
            days.append({
                "date": current,
                "weekday": weekday_labels[i],
                "day": current.day,
                "is_today": current == today,
                "events": events,
            })
            current += timedelta(days=1)

        return {
            "mode": "week",
            "title": f"Week of {week_start.strftime('%d %b %Y')}",
            "days": days,
        }

    # TEXT FIT HELPERS
    def _fit_text(self, draw, text, font, max_width):
        if max_width <= 4:
            return ""

        if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
            return text

        ellipsis = "…"
        lo, hi = 0, len(text)

        while lo < hi:
            mid = (lo + hi + 1) // 2
            candidate = text[:mid] + ellipsis
            if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
                lo = mid
            else:
                hi = mid - 1

        if lo <= 0:
            return ""
        return text[:lo] + ellipsis

    def _draw_text_clipped(self, draw, xy, text, font, max_width, fill=0):
        t = self._fit_text(draw, text, font, max_width)
        if t:
            draw.text(xy, t, fill=fill, font=font)

    # OVERLAP HANDLING
    def _assign_event_columns(self, events):
        laid_out = []
        active = []

        for e in sorted(events, key=lambda x: (x["start"], x["end"])):
            active = [a for a in active if a["end"] > e["start"]]

            used = {a["col"] for a in active}
            col = 0
            while col in used:
                col += 1

            item = dict(e)
            item["col"] = col
            active.append(item)
            laid_out.append(item)

        i = 0
        while i < len(laid_out):
            cluster = [laid_out[i]]
            end = laid_out[i]["end"]
            j = i + 1

            while j < len(laid_out) and laid_out[j]["start"] < end:
                cluster.append(laid_out[j])
                end = max(end, laid_out[j]["end"])
                j += 1

            cols = max(x["col"] for x in cluster) + 1
            for x in cluster:
                x["max_cols"] = cols

            i = j

        return laid_out

    # RENDER MONTH
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
            title_font = header_font = day_font = event_font = ImageFont.load_default()

        margin = 20
        title_h = 32
        weekday_h = 24

        grid_top = margin + title_h + weekday_h + 8
        grid_left = margin
        grid_width = width - 2 * margin
        grid_height = height - grid_top - margin

        cell_w = grid_width // 7
        cell_h = grid_height // 6

        draw.text((margin, margin), data["title"], fill=0, font=title_font)

        for i, name in enumerate(data["weekdays"]):
            draw.text((grid_left + i * cell_w + 4, margin + title_h), name, fill=0, font=header_font)

        for r in range(7):
            y = grid_top + r * cell_h
            draw.line((grid_left, y, grid_left + 7 * cell_w, y), fill=0)

        for c in range(8):
            x = grid_left + c * cell_w
            draw.line((x, grid_top, x, grid_top + 6 * cell_h), fill=0)

        for r, week in enumerate(data["weeks"]):
            for c, day in enumerate(week):
                x = grid_left + c * cell_w
                y = grid_top + r * cell_h

                if day["is_today"]:
                    draw.rectangle((x+1, y+1, x+cell_w-1, y+cell_h-1), outline=0, width=2)

                fill = 0 if day["in_month"] else 150
                draw.text((x+3, y+2), str(day["day"]), fill=fill, font=day_font)

        img = img.point(lambda p: 255 if p > 128 else 0, mode="1")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    # RENDER WEEK 
    def _render_week(self, data):
        width, height = 800, 480
        img = Image.new("L", (width, height), 255)
        draw = ImageDraw.Draw(img)

        try:
            title_font = ImageFont.truetype("DejaVuSans.ttf", 20)
            header_font = ImageFont.truetype("DejaVuSans.ttf", 11)
            tiny_font = ImageFont.truetype("DejaVuSans.ttf", 9)
        except Exception:
            title_font = header_font = tiny_font = ImageFont.load_default()

        margin = 10
        title_h = 24
        header_h = 18
        time_axis_w = 30

        grid_left = margin + time_axis_w
        header_top = margin + title_h + 4
        grid_top = header_top + header_h
        grid_width = width - grid_left - margin
        grid_height = height - grid_top - margin

        day_w = grid_width // 7

        start_hour = 6
        end_hour = 22
        total_minutes = (end_hour - start_hour) * 60

        def y_from_dt(dt):
            mins = (dt.hour*60+dt.minute) - start_hour*60
            mins = max(0, min(total_minutes, mins))
            return grid_top + int((mins/total_minutes)*grid_height)

        draw.text((margin, margin), data["title"], fill=0, font=title_font)

        for hour in range(start_hour, end_hour+1):
            y = y_from_dt(datetime.combine(date.today(), time(hour=hour)))
            draw.line((grid_left, y, grid_left+7*day_w, y), fill=180)

        for i in range(8):
            x = grid_left + i*day_w
            draw.line((x, header_top, x, grid_top+grid_height), fill=0)

        for i, day in enumerate(data["days"]):
            x = grid_left + i*day_w
            txt = f"{day['weekday']} {day['day']}"
            draw.text((x+2, header_top+2), txt, fill=0, font=header_font)

            events = self._assign_event_columns(day["events"])

            for e in events:
                y1 = y_from_dt(e["start"])
                y2 = y_from_dt(e["end"])

                if y2 - y1 < 12:
                    y2 = y1 + 12

                cols = e["max_cols"]
                col = e["col"]

                tile_w = max(8, (day_w-4)//cols)
                x1 = x + 2 + col*tile_w
                x2 = x1 + tile_w - 2

                draw.rectangle((x1, y1, x2, y2), outline=0)

                label = e["start"].strftime("%H:%M")
                label = self._fit_text(draw, label, tiny_font, x2-x1-2)
                draw.text((x1+1, y1+1), label, fill=0, font=tiny_font)

        img = img.point(lambda p: 255 if p > 128 else 0, mode="1")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()