import json
from odoo import http


class TrmnlController(http.Controller):

    @http.route('/trmnl/data', type='http', auth='public', methods=['GET'], csrf=False)
    def trmnl_data(self, **kwargs):
        device = http.request.env['trmnl.device'].sudo().search([], limit=1)

        data = {
            "display_name": device.name if device else "TRMNL Display",
            "content": {
                "title": device.name if device else "No device configured",
                "message": "Data from Odoo"
            },
            "status": "ok"
        }

        return http.Response(
            json.dumps(data),
            content_type='application/json'
        )