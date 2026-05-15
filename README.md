# PSE-FS2026: Odoo IoT for Digital Signage

## Overview

This Odoo addon turns Odoo into a first-party TRMNL API server. Instead of relying on the TRMNL cloud, your TRMNL e-ink display connects directly to your Odoo instance. Odoo manages device registration, renders preview images from live Odoo data (calendar events, tasks, CRM leads, etc.), and serves them to the device on every poll.

The TRMNL firmware is unchanged — it uses the same `/api/setup`, `/api/display`, and `/api/log` endpoints it would use against the official TRMNL cloud.

## How It Works

```
TRMNL Device
    │  GET /api/display  (every N seconds)
    ▼
Odoo (this addon)
    │  looks up active Profile for the device
    │  renders Odoo data → 800×480 PNG
    ▼
Device downloads PNG and displays it
```

1. The device registers itself via `/api/setup` → a Device record is created in Odoo
2. The admin creates a **Profile** linking the device to an Odoo model (Calendar, Tasks, CRM, etc.)
3. The admin clicks **Render Preview** → Odoo queries the model's data and generates a PNG
4. The device polls `/api/display` → receives the image URL → downloads and displays the PNG
5. On every subsequent poll, Odoo re-renders if the configured render interval has elapsed

## Repository Structure

```
.
├── addons/
│   └── trmnl/
│       ├── controllers/          # HTTP endpoints (/api/setup, /api/display, /api/log, /api/profile/image)
│       ├── models/               # Business logic (device lifecycle, auth, rendering pipeline)
│       │   ├── trmnl_profile.py         # Profile model: fields, domain building, data access helpers
│       │   └── trmnl_profile_render.py  # Rendering orchestration mixin (inherits trmnl.profile)
│       ├── views/                # Odoo backend UI (XML)
│       ├── security/             # Access control
│       ├── tests/                # Test suite
│       ├── trmnl_display_canvas.py       # Shared canvas constants, font helpers, footer renderer
│       ├── trmnl_preview.py              # List/table renderer (pure Python, PIL)
│       ├── trmnl_calendar_preview.py     # Calendar month renderer
│       └── trmnl_calendar_week_preview.py # Calendar week renderer
├── docs/
│   └── development.md            # Developer guide (Make commands, API testing)
├── compose.yaml
├── Dockerfile
├── LICENSE
├── Makefile
├── README.md
└── requirements.txt
```

### Rendering architecture

The rendering pipeline is split into two clearly separated layers:

**Layer 1 — Odoo model layer** (`models/trmnl_profile.py`, `models/trmnl_profile_render.py`)

All Odoo concerns are handled here. `TrmnlProfile` defines fields, domain building, and generic data access helpers (`_load_records`, `_extract_field_value`). `TrmnlProfileRenderMixin` extends `trmnl.profile` via `_inherit` — making it a full Odoo model — and owns the rendering pipeline: auto-refresh timing, calendar ORM queries, ORM-record → plain-dict conversion, renderer dispatch, footer compositing, and PNG persistence via `write()`.

**Layer 2 — Pure Python drawing utilities** (`trmnl_preview.py`, `trmnl_calendar_preview.py`, `trmnl_calendar_week_preview.py`, `trmnl_display_canvas.py`)

These are stateless functions. They accept plain Python data structures (lists of strings for list/kanban; dicts for calendar) and return PNG bytes. They have no Odoo ORM imports and no side-effects beyond producing image bytes. This keeps PIL rendering logic independently testable without a running Odoo instance.

The boundary is explicit: `TrmnlProfileRenderMixin._dispatch_renderer()` is the single crossing point. It converts ORM records into plain Python values, then calls a Layer 2 function. No ORM records ever cross into Layer 2.

## Prerequisites

- Docker and Docker Compose (or Podman Compose)
- `make`

The Makefile uses `docker compose` by default. For a local override, create `local.mk` in the repo root:

```makefile
COMPOSE=podman compose
```

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/Abilium-GmbH/pse_trmnl_odoo_connector.git
cd pse_trmnl_odoo_connector
```

### 2. Start Odoo

```bash
make
```

This initializes the database, installs the `trmnl` module, and starts Odoo. On a fresh database this runs automatically.

Odoo is available at [http://localhost:8069](http://localhost:8069). Default credentials: `admin` / `admin`.

### 3. (Optional) Watch for changes during development

```bash
make watch
```

Watches `addons/trmnl/` and upgrades the module automatically when files change.

---

## Connecting a TRMNL Device

### Network requirement

The Docker Compose setup binds Odoo to `0.0.0.0:8069`, so it is reachable from both `localhost` (browser on the same machine) and the LAN IP (physical TRMNL device on the same network).

**No manual URL configuration is needed in the typical setup.** When the device polls Odoo for the first time, the server reads the `Host` header and automatically stores the correct URL for serving images back to the device.

If auto-detection does not work (for example, if Odoo sits behind a reverse proxy, or the detected address is a VM bridge IP rather than the host's LAN IP), override it manually:

- Go to **Settings → Technical → Parameters → System Parameters**
- Set `trmnl.public_base_url` = `http://192.168.1.x:8069` (your actual LAN IP)

### Step 1 — Point the device at Odoo

Configure your TRMNL device to use your Odoo URL as its custom server instead of the TRMNL cloud. Refer to the TRMNL firmware documentation for how to set a custom API server.

### Step 2 — Register the device

Power on the device. It will call `/api/setup` automatically. A **Device** record appears in Odoo under **TRMNL → Devices** with status `Accepted`.

If the device does not appear, check that the Odoo URL is reachable from the device's network.

### Step 3 — Create a Profile

1. Go to **TRMNL → Profiles → New**
2. Enter a name and select the device
3. Select an **Odoo Model** (e.g. `calendar.event`, `project.task`, `crm.lead`)
4. Choose a **View Type** (List, Kanban, or Calendar — Calendar is only relevant for `calendar.event`)
5. Select which fields to display, optionally configure filters and sort order
6. Click **Render Preview**

A preview image appears in the form. The **Device Delivery Status** section shows when the device last polled and when the next poll is expected.

### Step 4 — Wait for the device to poll

The device polls Odoo every N seconds (configured by **Refresh Rate** on the Device record, default 1800s / 30 min). It picks up the new image on its next poll.

---

## Supported Layouts

| Layout | Best for | Notes |
|--------|----------|-------|
| **List** | Any model | Tabular display; shows selected fields as columns |
| **Kanban** | Any model | Uses the same list renderer; no separate kanban layout exists |
| **Calendar (month)** | `calendar.event` | Monthly grid with event listings per day |
| **Calendar (week)** | `calendar.event` | Work week (Mon–Fri) or full week (Mon–Sun), hourly grid |

> **Note:** The Kanban option produces the same output as List. It is kept in the UI so that profiles created with layout type "kanban" continue to render without error.

> **Note:** The preview image shown in the form and the image served to the device are the same PNG binary. Differences in appearance on an e-ink display (e.g. alternating row shading) are due to the display's contrast characteristics — the image itself is identical.

---

## Filtering and Data

Each Profile has three independent filter layers applied with AND:

| Setting | Purpose |
|---------|---------|
| **Quick Filter** | Preset shortcuts: All, Assigned to Me, Today, This Week, This Month, Overdue |
| **Domain Filter** | Free-form Odoo domain, e.g. `[('priority', '=', '1')]`. Supports `uid`, `context_today()` |
| **Sort Order** | Raw `ORDER BY` clause, e.g. `date_deadline asc, name asc` |

**Render Interval** controls how often Odoo re-renders the image during device polls. Zero defaults to 10 minutes. The device's own refresh rate is set separately on the Device record.

---

## Device Approval Policies

Configure under **TRMNL → Display Policy**:

| Policy | Behaviour |
|--------|-----------|
| **Error** (default) | Unknown devices are recorded as stubs for manual review. Admin can accept them from the device list. |
| **Auto Accept** | Any device that polls is automatically accepted and served. Convenient for first-time setup. |
| **Factory Reset** | Unknown or mismatched devices receive a reset signal. |

---

## Make Commands

| Command | Description |
|---------|-------------|
| `make` / `make start` | Start Odoo and install the module |
| `make watch` | Start + auto-upgrade on file changes |
| `make update` | Force module upgrade and restart |
| `make test` | Run the test suite |
| `make stop` | Stop containers (keep data) |
| `make down` | Remove containers (keep volumes) |
| `make downv` | Remove containers and volumes (deletes all data) |
| `make restart` | Restart only the Odoo container |
| `make logs` | Stream Odoo logs |
| `make shell` | Open a shell inside the Odoo container |

---

## Environment Variables

The `compose.yaml` uses a `.env` file for configuration. If no `.env` file is present, default values from `compose.yaml` are used.

To use custom values:

```bash
cp .env.example .env
# edit .env as needed
```

---

## Notes for Linux Users

Some distributions (notably Fedora) recommend Podman over Docker. If you encounter issues, add a `local.mk` file:

```makefile
COMPOSE=podman compose
```

SELinux or AppArmor may also require additional configuration for volume mounts.

---

## Development Team

- Timur Umut Turgul — Key Account Manager
- Sascha Friedli — Chief Deliverable Officer
- Leïla Ayinkamiye — Quality Evangelist
- Claudio Berger — Master Tracker
