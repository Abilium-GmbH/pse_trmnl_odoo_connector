{
    "name": "TRMNL",
    "summary": "Module for TRMNL device/profile management",
    "description": "Manage devices, profiles, and render logs for TRMNL",
    "author": "Abilium GmbH",
    "license": "MIT",
    "version": "1.0.0",
    "depends": ["base", "calendar"],
    "data": [
        "security/ir.model.access.csv",
        "views/trmnl_device_views.xml",
        "views/trmnl_profile_views.xml",
        "views/menus.xml",
        "data/ir_cron.xml",
    ],
    "application": True,
}
