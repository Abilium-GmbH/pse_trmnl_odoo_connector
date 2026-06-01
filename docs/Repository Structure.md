# The Structure of the Repository

This documentation provides an overview of the repository structure and explains the purpose of the most important folders and files.

---

## Overview of the Repository

```text
.
├── addons/
│   └── trmnl/                  # Main Odoo module
├── docs/
│   ├── assets/videos/          # README demo media (e.g. trmnl_display.gif)
│   ├── design_documentation.md
│   ├── development.md
│   ├── user_manual.md
│   └── Repository Structure.md
├── scripts/
│   └── odoo-dev.sh
├── compose.yaml
├── Dockerfile
├── LICENSE
├── Makefile
├── README.md
└── requirements.txt
```

---

## General Repository Structure

### addons/

The `addons` folder contains all custom Odoo modules of the project. In this repository the main module is **trmnl**, which implements device communication, display profiles, and PNG rendering for TRMNL e-ink displays.

### docs/

Project documentation:

- [user manual](user_manual.md) — installation, pairing, devices, profiles, troubleshooting
- [design documentation](design_documentation.md) — architecture, API, security, data model
- [development guide](development.md) — Docker workflow, Make targets, tests
- [README](../README.md) — project overview and quick start
- `assets/videos/` — media embedded in the README

### scripts/

Helper scripts for development. `scripts/odoo-dev.sh` is invoked by the `Makefile` for start, watch, update, and test actions.

### compose.yaml / Dockerfile

Docker Compose stack (PostgreSQL + Odoo) and the custom Odoo image (fonts, Python dependencies from `requirements.txt`).

### Makefile

Shortcuts for `make start`, `make watch`, `make test`, and related development tasks.

### requirements.txt

Python packages installed in the Odoo container (`pillow`, `requests`).

---

## Structure of the TRMNL Module

```text
addons/trmnl/
├── controllers/                # HTTP API endpoints
├── models/                     # Business logic and ORM models
├── security/                   # Access control
├── static/                     # Icons, fonts, backend JS widgets
├── views/                      # Odoo XML UI definitions
├── trmnl_display_canvas.py     # Shared PIL canvas helpers
├── trmnl_net.py                # URL / host reachability helpers
├── tests/
├── __init__.py
└── __manifest__.py
```

---

## controllers/

HTTP endpoints called by TRMNL firmware and by devices downloading profile images.

| File | Endpoint | Purpose |
|---|---|---|
| `device_setup_controller.py` | `GET /api/setup` | Device registration and API token issuance |
| `device_display_controller.py` | `GET /api/display` | Display polling, profile resolution, image URL |
| `device_log_controller.py` | `POST /api/log` | Telemetry and firmware log ingestion |
| `profile_image_controller.py` | `GET /api/profile/image/<id>` | Serve stored profile PNG to devices |
| `trmnl_api_base.py` | — | Shared JSON response and logging helpers |

---

## models/

### Device subsystem

| File | Purpose |
|---|---|
| `trmnl_device.py` | Core device fields, ORM overrides, refresh rate |
| `trmnl_device_security.py` | API token generation, PBKDF2 hashing, verification |
| `trmnl_device_lifecycle.py` | Registration, acceptance, stub creation, reset |
| `trmnl_device_display.py` | Display response building and profile integration |
| `trmnl_device_telemetry.py` | Header telemetry and `/api/log` ingestion |
| `trmnl_device_log.py` | `trmnl.device.log` model |
| `trmnl_device_ui.py` | Backend-only fields, list actions, button visibility |
| `trmnl_device_wizard.py` | Accept, remove, reset, and display-policy wizards |

### Profile / renderer subsystem

| File | Purpose |
|---|---|
| `trmnl_profile.py` | Profile fields, domain building, model selector, image URLs |
| `trmnl_profile_render.py` | Render orchestration, PNG persistence, auto-refresh timing |
| `trmnl_profile_render_list.py` | List and kanban PIL renderers |
| `trmnl_profile_render_calendar.py` | Month and week calendar PIL renderers |
| `trmnl_profile_render_graph.py` | Bar and line chart PIL renderers |
| `trmnl_image.py` | Default screen seeding on module install |
| `trmnl_data_watcher.py` | Detect source-record changes for re-render |

---

## security/

`ir.model.access.csv` restricts backend access to Settings / Administrator users (`base.group_system`). Device-facing API routes use `auth="public"` with application-layer token checks.

---

## views/

| File | Purpose |
|---|---|
| `trmnl_device_views.xml` | Device list and form views |
| `trmnl_device_wizard_views.xml` | Device action and display-policy wizards |
| `trmnl_profile_views.xml` | Profile list and form views |
| `trmnl_menu.xml` | TRMNL menu: Devices, Profiles, Display Policy |

---

## static/

- `description/` — module icon shown in Odoo Apps
- `fonts/` — TrueType fonts used by PIL renderers
- `src/js/` — backend widget for layout selection

---

## tests/

Automated tests under `addons/trmnl/tests/` cover:

- Device API endpoints (`test_api_*.py`)
- Refresh rate logic (`test_device_refresh_rate.py`)
- Profile rendering, filters, and view types (`test_profile_*.py`)
- Chart data loading, image URLs, and device image sync

Run the full suite with `make test`. See the [development guide](development.md) and [design documentation](design_documentation.md) for details.

---

## Summary

The repository follows a modular Odoo architecture:

- **controllers/** — HTTP API and image delivery
- **models/** — device lifecycle, security, profiles, and PIL rendering
- **views/** — Odoo backend UI
- **security/** — access permissions
- **tests/** — automated API and renderer validation

This separation keeps device protocol handling, business logic, rendering, and UI definitions maintainable as the module grows.
