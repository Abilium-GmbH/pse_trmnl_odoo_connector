import io
from itertools import product
import requests

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

    def send_to_trmnl(self):
        self.ensure_one()

        if not self.webhook_url:
            raise ValueError("No webhook_url configured for this device.")

        # 800x480 passt gut für TRMNL
        image = Image.new("1", (800, 480), 1)  # 1 = weiss
        draw = ImageDraw.Draw(image)

        # Einfacher Text mittig-ish
        # Produkt aus Odoo laden
        product = self.env['product.product'].search([], limit=1)

        product_name = product.name if product else "No product found"
        product_price = product.list_price if product else "-"

        # Titel
        draw.text((60, 60), "Featured Product", fill=0)

        # Trennlinie
        draw.line((60, 120, 740, 120), fill=0, width=2)

        # Produktdaten
        draw.text((60, 180), product_name, fill=0)
        draw.text((60, 260), f"Price: {product_price}", fill=0)

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