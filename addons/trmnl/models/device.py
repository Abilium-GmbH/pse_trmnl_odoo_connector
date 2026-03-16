import requests
import io

from PIL import Image, ImageDraw

from odoo import models, fields


class TrmnlDevice(models.Model):
    _name = "trmnl.device"
    _description = "TRMNL Display"

    name = fields.Char(string="Display Name", required=True)
    device_id = fields.Char(string="Device ID")
    last_sync = fields.Datetime(string="Last Sync")
    active = fields.Boolean(string="Active", default=True)
    webhook_url = fields.Char(string="Webhook URL")
    
    content_type = fields.Selection(
        [
            ("custom_message", "Custom Message"),
            ("device_info", "Device Info"),
        ],
        string="Content Type",
        default="device_info",
        required=True,
    )

    custom_message = fields.Text(string="Custom Message")

    def send_to_trmnl(self):
        self.ensure_one()

        if not self.webhook_url:
            raise ValueError("No webhook_url configured for this device.")

        # 800x480 passt gut für TRMNL
        image = Image.new("1", (800, 480), 1)  # 1 = weiss
        draw = ImageDraw.Draw(image)

        # Einfacher Text mittig-ish
        # Produkt aus Odoo laden
        # Inhalt abhängig vom Content Type
        if self.content_type == "device_info":
            draw.text((60, 60), self.name or "TRMNL Display", fill=0)
            draw.line((60, 120, 740, 120), fill=0, width=2)
            draw.text((60, 170), f"Device ID: {self.device_id or '-'}", fill=0)
            draw.text((60, 230), f"Last Sync: {self.last_sync or '-'}", fill=0)
            draw.text((60, 290), f"Status: {'Active' if self.active else 'Inactive'}", fill=0)

        elif self.content_type == "custom_message":
            draw.text((60, 60), self.name or "Custom Message", fill=0)
            draw.line((60, 120, 740, 120), fill=0, width=2)
            draw.text((60, 200), self.custom_message or "No message configured", fill=0)

        else:
            draw.text((60, 60), "Unknown Content Type", fill=0)

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        buffer.seek(0)

        response = requests.post(
            self.webhook_url,
            headers={"Content-Type": "image/png"},
            data=buffer.getvalue(),
            timeout=10,
        )

        response.raise_for_status()
        self.last_sync = fields.Datetime.now()

        return {
            "type": "ir.actions.client",
            "tag": "reload",
        }
