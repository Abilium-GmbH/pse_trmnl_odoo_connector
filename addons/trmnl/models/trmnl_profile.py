import logging
import requests

from odoo import models, fields
from .providers.calendar_provider import CalendarProvider
from .trmnl_render_log import TrmnlRenderLog

_logger = logging.getLogger(__name__)


class TrmnlProfile(models.Model):
    _name = "trmnl.profile"
    _description = "TRMNL Profile"

    name = fields.Char(required=True)

    device_id = fields.Many2one("trmnl.device", required=True)

    provider_type = fields.Selection([
        ("calendar", "Calendar"),
    ], default="calendar", required=True)

    calendar_view_mode = fields.Selection([
        ("week", "Weekly"),
        ("month", "Monthly"),
    ], default="week")

    active = fields.Boolean(default=True)

    def _get_provider(self):
        if self.provider_type == "calendar":
            return CalendarProvider()
        raise Exception("Unknown provider")

    def generate_image(self):
        provider = self._get_provider()

        data = provider.fetch_data(self.env, self)
        image_bytes = provider.render(data, self)

        return image_bytes

    def send_to_device(self):
        for record in self:
            try:
                _logger.info(
                    "TRMNL: starting send for profile=%s device=%s",
                    record.id,
                    record.device_id.id,
                )

                provider = record._get_provider()

                _logger.info("TRMNL: fetching data for profile=%s", record.id)
                data = provider.fetch_data(self.env, record)
                _logger.info(
                    "TRMNL: fetched %s items for profile=%s",
                    len(data) if data else 0,
                    record.id,
                )

                _logger.info("TRMNL: rendering image for profile=%s", record.id)
                image_bytes = provider.render(data, record)
                _logger.info(
                    "TRMNL: rendered image size=%s bytes for profile=%s",
                    len(image_bytes),
                    record.id,
                )

                _logger.info("TRMNL: posting to webhook for device=%s", record.device_id.id)
                response = requests.post(
                    record.device_id.webhook_url,
                    data=image_bytes,
                    headers={"Content-Type": "image/png"},
                    timeout=20,
                )

                _logger.info(
                    "TRMNL: webhook response status=%s body=%s",
                    response.status_code,
                    response.text[:500],
                )
                response.raise_for_status()

                record.device_id.write({
                    "last_sync_at": fields.Datetime.now(),
                    "last_status": "ok",
                })

                self.env["trmnl.render.log"].create({
                    "profile_id": record.id,
                    "device_id": record.device_id.id,
                    "status": "ok",
                })

            except Exception:
                _logger.exception(
                    "TRMNL: send failed for profile=%s device=%s",
                    record.id,
                    record.device_id.id,
                )

                record.device_id.write({
                    "last_status": "error",
                })

                self.env["trmnl.render.log"].create({
                    "profile_id": record.id,
                    "device_id": record.device_id.id,
                    "status": "error",
                    "error_message": "See Odoo logs for traceback",
                })

    def action_test_send(self):
        self.send_to_device()
