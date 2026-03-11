import json
from odoo import http


class TrmnlController(http.Controller):

    @http.route('/trmnl/data', type='http', auth='public', methods=['GET'], csrf=False)
    def trmnl_data(self, **kwargs):
        data = {
            "display_name": "TRMNL Test Display",
            "content": {
                "title": "TRMNL Test",
                "message": "Hello from Odoo"
            },
            "status": "ok"
        }

        return http.Response(
            json.dumps(data),
            content_type='application/json'
        )