# The Structure of the Repository

This document gives a high-level map of the repository: what each top-level
folder is for, how the **trmnl** Odoo module is laid out, and where to find the
tests. For architecture, the HTTP protocol, the data model, and the security
design, see the [design documentation](design_documentation.md) — this file
deliberately stays at the overview level and does not repeat it.

---

## Overview of the Repository

```text
.
├── addons/
│   └── trmnl/                  # The TRMNL Odoo module (all custom code)
├── data/
│   └── fictitious_calendar_data_2026.xlsx   # Sample dataset for demoing calendar profiles
├── docs/                       # Project documentation (see below)
├── scripts/
│   └── odoo-dev.sh             # Dev helper invoked by the Makefile
├── .env.example                # Template for Postgres / Odoo container env vars
├── .pre-commit-config.yaml     # Ruff / formatting pre-commit hooks
├── compose.yaml                # Docker Compose stack (Odoo + PostgreSQL)
├── Dockerfile                  # Custom Odoo image (fonts + Python deps)
├── LICENSE
├── Makefile                    # make start / watch / update / test shortcuts
├── pyproject.toml              # Ruff/tooling configuration
├── README.md                   # Project overview and quick start
└── requirements.txt            # Container Python packages (pillow, requests)
```

---

## Top-Level Folders and Files

### addons/

All custom Odoo modules live here. The single module in this repository is
**trmnl**, which implements the device-facing HTTP protocol, display profiles,
and PNG rendering for TRMNL e-ink displays. See
[Structure of the TRMNL Module](#structure-of-the-trmnl-module) below.

### data/

Non-code fixtures. `fictitious_calendar_data_2026.xlsx` is a sample dataset that
can be imported into an Odoo model to populate a calendar and try out calendar
profiles. It is **not** auto-loaded by the module manifest — it is a manual
import aid for demos and testing.

### docs/

Project documentation:

- [User guide (PDF)](user_guide.pdf) — pairing, devices, profiles, troubleshooting
- [Design documentation](design_documentation.md) — architecture, API, security, data model, test strategy
- [Development guide](development.md) — Docker/Make workflow, running tests, contributor setup
- [Curl commands](curl_commands.md) — example `curl` calls that simulate the device API requests
- [README](../README.md) — project overview and quick start
- `assets/videos/` — demo media used by the README (`odoo_setup.mp4`, `trmnl_display.gif`)

### scripts/

Development helper scripts. `scripts/odoo-dev.sh` is the entry point used by the
`Makefile` for the start, watch, update, and test actions.

### compose.yaml / Dockerfile

`compose.yaml` defines the local stack (PostgreSQL + Odoo). `Dockerfile` builds
the custom Odoo image, installing the fonts used by the renderers and the Python
dependencies from `requirements.txt`.

### Makefile

Shortcuts for the Docker dev loop: `make start`, `make watch`, `make update`,
`make test`, and related targets. See the [development guide](development.md).

### requirements.txt / pyproject.toml / .pre-commit-config.yaml / .env.example

`requirements.txt` pins the Python packages installed in the Odoo container
(`pillow`, `requests`); the module manifest itself only requires **Pillow**.
`pyproject.toml` holds tooling (Ruff) config, `.pre-commit-config.yaml` wires up
the pre-commit hooks, and `.env.example` documents the Postgres/Odoo environment
variables expected by `compose.yaml`.

---

## Structure of the TRMNL Module

```text
addons/trmnl/
├── controllers/        # HTTP API endpoints (device-facing)
├── lib/                # Pure-Python helpers (no Odoo/ORM dependency)
├── models/             # ORM models and business logic
├── security/           # Access control
├── static/             # Module icon, fonts, backend JS widget
├── views/              # Odoo XML UI definitions
├── tests/              # Automated test suite
├── __init__.py
└── __manifest__.py     # Module metadata, dependencies, data files, hooks
```

The manifest depends on `base` and `web`, requires **Pillow**, and registers a
`post_init_hook` / `uninstall_hook` (default-screen image seeding and cleanup).

---

## controllers/

HTTP endpoints called by TRMNL firmware and by devices downloading profile
images. Device routes are `auth="public"` with application-layer token checks.

| File | Endpoint | Purpose |
|---|---|---|
| `device_setup_controller.py` | `GET /api/setup` | Device registration and API token issuance |
| `device_display_controller.py` | `GET /api/display` | Display polling, profile resolution, image URL |
| `device_log_controller.py` | `POST /api/log` | Telemetry and firmware log ingestion |
| `profile_image_controller.py` | `GET /api/profile/image/<id>` | Serve the stored profile PNG to devices |
| `trmnl_api_base.py` | — | Shared JSON response and logging helpers |

---

## lib/

Pure-Python helpers with no Odoo or PIL-model dependencies, kept separate so
they are easy to unit-test in isolation.

| File | Purpose |
|---|---|
| `display_canvas.py` | Canvas dimensions/palette, font helpers, footer layout. `DISPLAY_WIDTH` (800) / `DISPLAY_HEIGHT` (480) are fallbacks; renderers scale to the device-reported size |
| `net.py` | URL / host reachability checks used to decide whether a base URL is reachable by a physical device on the LAN |

---

## models/

The device and profile logic is split into focused `_inherit` mixins rather than
two monolithic files, keeping protocol handling, security, rendering, and data
loading separable.

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
| `trmnl_profile.py` | Profile fields, model selector, image URLs |
| `trmnl_profile_domain.py` | `filter_domain` safe-eval, structural/semantic validation, preset + effective domain building |
| `trmnl_profile_render.py` | Render orchestration, PNG persistence, auto-refresh timing |
| `trmnl_profile_render_data.py` | ORM data-loading layer: queries and record→dict conversion feeding the PIL renderers (no PIL code) |
| `trmnl_profile_render_list.py` | List and kanban PIL renderers |
| `trmnl_profile_render_calendar.py` | Month and week calendar PIL renderers |
| `trmnl_profile_render_graph.py` | Bar and line chart PIL renderers |
| `trmnl_image.py` | Default-screen seeding/cleanup (install & uninstall hooks) |
| `trmnl_data_watcher.py` | Detects source-record changes and marks affected screens stale |

---

## security/

`ir.model.access.csv` restricts backend access to Settings / Administrator users
(`base.group_system`). The device-facing API routes are public and enforce
token checks in application code instead.

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

- `description/` — module icon shown in the Odoo Apps list
- `fonts/` — TrueType fonts (DejaVu Sans) used by the PIL renderers
- `src/js/` — `trmnl_layout_select_widget.js`, the backend layout-selection widget

---

## tests/

The suite lives in `addons/trmnl/tests/` (registered in `tests/__init__.py`) and
runs with `make test`. `test_common.py` and `test_api_common.py` are shared base
classes/helpers, not test cases themselves. The remaining modules group as
follows:

### HTTP API endpoints
| File | Covers |
|---|---|
| `test_api_setup.py` | `/api/setup` registration and token issuance |
| `test_api_display.py` | `/api/display` polling, profile resolution, image URL |
| `test_api_log.py` | `/api/log` telemetry/log ingestion |

### Device behavior & lifecycle
| File | Covers |
|---|---|
| `test_device_refresh_rate.py` | Per-device refresh interval configuration |
| `test_device_screen_size.py` | `Width`/`Height` headers driving stored size and PNG dimensions |
| `test_poll_timestamp.py` | Poll-metadata footer drawn on rendered previews |
| `test_image_url.py` | Device-reachable URL detection, image URL generation, warnings |
| `test_trmnl_image_seeder.py` | Default-screen seeding and cleanup lifecycle |
| `test_module_uninstall.py` | Safe module uninstall (savepoint-wrapped invalidation) |

### Profile configuration, domains & selectors
| File | Covers |
|---|---|
| `test_model_selector.py` | `app_model_id` selector domain |
| `test_profile_filter_domain.py` | `filter_domain` field behavior |
| `test_profile_view_types.py` | `available_view_types` computation and layout selection |
| `test_profile_data_staleness.py` | Data-change invalidation / re-render pipeline |

### Rendering & image output
| File | Covers |
|---|---|
| `test_profile_renderers.py` | Each `_render_*_png` returns valid PNG bytes |
| `test_profile_dashboard_layout.py` | List/kanban layouts use the dashboard renderers |
| `test_profile_render_preview.py` | Render Preview button (single-click, cache busting) |
| `test_display_image_quality.py` | Finalized PNGs match device output (list B/W, kanban grayscale) |
| `test_graph_chart.py` | Bar-graph data loading, validation, renderer |
| `test_line_chart.py` | Line-chart validation, data loading, renderer |
| `test_calendar_device_image.py` | Stored calendar preview bytes match the device image endpoint |
| `test_device_image_sync.py` | Image URL/filename changes when preview bytes change |

---

## Summary

The repository follows a modular Odoo architecture:

- **controllers/** — device-facing HTTP API and image delivery
- **lib/** — dependency-free canvas and network helpers
- **models/** — device lifecycle, security, profiles, data loading, and PIL rendering, split into focused mixins
- **views/** + **static/** — Odoo backend UI and assets
- **security/** — access permissions
- **tests/** — endpoint, device, profile, and renderer validation

This separation keeps device protocol handling, business logic, rendering, and
UI definitions maintainable as the module grows. For the *why* behind these
pieces, see the [design documentation](design_documentation.md).
