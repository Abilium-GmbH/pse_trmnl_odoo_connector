{
    "name": "TRMNL",
    "summary": "Module for TRMNL display management",
    "description": "Manage devices, profiles, and render logs for TRMNL",
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
