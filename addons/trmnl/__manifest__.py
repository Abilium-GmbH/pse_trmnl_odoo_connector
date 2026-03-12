{
    "name": "TRMNL Integration",
    "version": "1.0",
    "summary": "Integration von TRMNL e-Ink Displays in Odoo",
    "depends": ["base"],
    "data": [
        "security/ir.model.access.csv",
        "views/trmnl_device_views.xml",
    ],
    "installable": True,
    "application": True,
}