from odoo import http


class TrmnlController(http.Controller):

    @http.route('/trmnl/data', type='http', auth='public', methods=['GET'], csrf=False)
    def trmnl_data(self, **kwargs):
        json_data = """
        {
            "title": "TRMNL Test",
            "message": "Hello from Odoo",
            "status": "ok"
        }
        """
        return http.Response(json_data, content_type='application/json')

