{
    "name": "TRMNL",
    "summary": "Drive TRMNL e-ink displays from Odoo — render live business data as auto-updating screens",
    "description": """
TRMNL Connector for Odoo
========================

Turn TRMNL e-ink displays into live dashboards for your Odoo data. Each device
registers itself over HTTP and periodically polls the server, which renders the
latest content as an image and serves it back — no app or cloud account required.

Key features
------------
* Self-service device onboarding via /api/setup, with token-based authentication
  and an admin approval workflow for unknown devices.
* Profiles bind a device to any Odoo model (calendars, sales orders, tasks,
  contacts, ...) and a layout: list, kanban, calendar (month/week), or bar/line
  chart.
* Custom filter domains and presets (my records, today, overdue, ...) control
  exactly which records appear on each screen.
* Automatic, change-driven refresh: edits to the underlying records mark the
  affected screens stale and trigger a re-render on the next device poll.
* Configurable per-device refresh interval and on-device diagnostics via /api/log.
""",
    "category": "Productivity / IoT",
    "author": "Abilium GmbH",
    "license": "Other OSI approved licence",
    "version": "1.0.0",
    "images": ["static/description/icon.png"],
    "depends": ["base", "web"],
    "external_dependencies": {"python": ["Pillow"]},
    "data": [
        "security/ir.model.access.csv",
        "views/trmnl_device_views.xml",
        "views/trmnl_device_wizard_views.xml",
        "views/trmnl_profile_views.xml",
        "views/trmnl_menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "trmnl/static/src/js/trmnl_layout_select_widget.js",
        ],
    },
    "post_init_hook": "post_init_hook",
    "uninstall_hook": "uninstall_hook",
}
