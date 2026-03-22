from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont
import io


class CalendarProvider:

    def fetch_data(self, env, profile):
        now = datetime.now()

        if profile.calendar_view_mode == "week":
            end = now + timedelta(days=7)
        else:
            end = now + timedelta(days=30)

        events = env["calendar.event"].search([
            ("start", ">=", now),
            ("start", "<=", end),
        ])

        result = []
        for e in events:
            result.append({
                "name": e.name,
                "start": e.start,
            })

        return result

    def render(self, data, profile):
        from PIL import Image, ImageDraw, ImageFont
        import io

        width, height = 800, 480

        # Build in grayscale first, then convert to strict 1-bit at the end.
        img = Image.new("L", (width, height), 255)  # 255 = white
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 18)
        except Exception:
            font = ImageFont.load_default()

        y = 20

        title = f"Calendar ({profile.calendar_view_mode})"
        draw.text((20, y), title, fill=0, font=font)  # 0 = black
        y += 40

        for event in data[:15]:
            text = f"{event['start']} - {event['name']}"
            draw.text((20, y), text, fill=0, font=font)
            y += 25

        # Force pure 1-bit monochrome output for TRMNL.
        img = img.point(lambda p: 255 if p > 128 else 0, mode="1")

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return buffer.getvalue()
