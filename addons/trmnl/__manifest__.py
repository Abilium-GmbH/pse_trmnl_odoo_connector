{
    "name": "TRMNL",
    "summary": "Module for TRMNL display management",
    "description": "Manage devices, profiles, and render logs for TRMNL",
    "category": "Productivity / IoT",
    "author": "Abilium GmbH",
    "license": "Other OSI approved licence",
    "version": "1.0.9",
    "application": True,
    "images": ["static/description/icon.png"],
    "depends": ["base", "web"],
    "external_dependencies": {"python": ["Pillow"]},
    "assets": {
        "web.assets_backend": [
            "trmnl/static/src/js/trmnl_layout_select_widget.js",
        ],
    },
    "data": [
            "security/trmnl_groups.xml",
            "security/ir.model.access.csv",
            "views/trmnl_device_views.xml",
            "views/trmnl_device_wizard_views.xml",
            "views/trmnl_profile_views.xml",
            "views/trmnl_menu.xml",
            ],
}
