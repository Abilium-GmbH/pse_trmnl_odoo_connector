# TRMNL Odoo Connector — Design Documentation

_Last updated: June 2026

This document describes the architecture and design of the **TRMNL** Odoo
add-on, which drives [TRMNL](https://usetrmnl.com) e-ink displays from Odoo.
Each device registers itself over HTTP, periodically polls the server, and is
served a freshly rendered image of live Odoo business data — no app or cloud
account required.

For day-to-day workflows see [`development.md`](./development.md); for raw API
examples see [`curl_commands.md`](./curl_commands.md).

---

## 1. Overview

The connector turns TRMNL e-ink panels into live dashboards for Odoo data.

- **Self-service onboarding.** A device calls `/api/setup` and receives an API
  token. Depending on the configured policy, it is either auto-accepted or held
  for manual admin approval.
- **Profiles.** A *profile* binds one device to any Odoo model and a layout —
  list, kanban, calendar (month/week), or bar/line chart — with filters,
  ordering, and a refresh cadence.
- **Change-driven rendering.** Edits to the underlying records mark the affected
  profiles stale; the next device poll triggers a re-render to PNG.
- **Token-based security.** Devices authenticate with a MAC address + API token
  (PBKDF2-HMAC-SHA256, salted, 600 000 iterations). No Odoo user account is
  required on the device.
- **Diagnostics.** Devices post structured logs to `/api/log` for review in the
  backend.

### Technology stack

| Component        | Value                                              |
|------------------|----------------------------------------------------|
| Odoo             | 19.0 (base image `odoo:19.0-20260305`)             |
| Python deps      | `Pillow` (`pillow==12.1.1`) — for PNG rendering    |
| System deps      | `fonts-dejavu-core` (TrueType fonts for PIL)       |
| Database         | PostgreSQL 18.3                                     |
| Odoo deps        | `base`, `web`                                      |
| Module version   | 1.0.0                                              |

---

## 2. Repository structure

```
.
├── addons/trmnl/
│   ├── __manifest__.py
│   ├── __init__.py                     # post_init_hook / uninstall_hook (image seeding)
│   ├── controllers/
│   │   ├── trmnl_api_base.py           # shared controller mixin (JSON, logging, masking)
│   │   ├── device_setup_controller.py  # GET  /api/setup
│   │   ├── device_display_controller.py# GET  /api/display
│   │   ├── device_log_controller.py    # POST /api/log
│   │   └── profile_image_controller.py # GET  /api/profile/image/<int:profile_id>
│   ├── models/
│   │   ├── trmnl_device.py             # core model + constants
│   │   ├── trmnl_device_security.py    # token generation / hashing / verification
│   │   ├── trmnl_device_lifecycle.py   # registration, policy, response builders
│   │   ├── trmnl_device_telemetry.py   # telemetry capture + log ingestion
│   │   ├── trmnl_device_display.py     # display request resolution (decision tree)
│   │   ├── trmnl_device_ui.py          # backend UI fields & actions
│   │   ├── trmnl_device_log.py         # log entry model
│   │   ├── trmnl_device_wizard.py      # accept / remove / reset / policy wizards
│   │   ├── trmnl_image.py              # built-in image seeder (ir.attachment)
│   │   ├── trmnl_data_watcher.py       # marks profiles stale on data change
│   │   ├── trmnl_profile.py            # profile model + fields
│   │   ├── trmnl_profile_domain.py     # filter domain parsing / presets
│   │   ├── trmnl_profile_render.py     # render trigger logic + pipeline
│   │   ├── trmnl_profile_render_data.py# ORM → plain-dict data loading
│   │   ├── trmnl_profile_render_list.py# PIL list / kanban renderers
│   │   ├── trmnl_profile_render_calendar.py # PIL calendar renderers
│   │   └── trmnl_profile_render_graph.py    # PIL bar / line chart renderers
│   ├── lib/
│   │   ├── display_canvas.py           # e-ink palette, fonts, footer compositing
│   │   └── net.py                      # client-reachability heuristics
│   ├── security/ir.model.access.csv
│   ├── views/
│   │   ├── trmnl_device_views.xml
│   │   ├── trmnl_device_wizard_views.xml
│   │   ├── trmnl_profile_views.xml
│   │   └── trmnl_menu.xml
│   ├── static/
│   │   ├── description/icon.png
│   │   ├── fonts/DejaVuSans.ttf, DejaVuSans-Bold.ttf
│   │   ├── img/default_screen.bmp, unauthorized_screen.bmp
│   │   └── src/js/trmnl_layout_select_widget.js
│   └── tests/                          # see §10
├── data/fictitious_calendar_data_2026.xlsx  # demo fixture (not loaded by manifest)
├── docs/development.md, docs/curl_commands.md, docs/design_documentation.md
├── scripts/odoo-dev.sh
├── Dockerfile, compose.yaml, Makefile, requirements.txt
├── pyproject.toml, .pre-commit-config.yaml
```

---

## 3. Architecture

The add-on follows a thin-controller / fat-model design. HTTP controllers parse
headers and delegate all business logic to model methods; the model layer is
split into focused mixins that all `_inherit = "trmnl.device"` (or
`"trmnl.profile"`).

```
TRMNL device ──HTTP──▶ controllers/  ──delegates──▶ trmnl.device mixins
                                                     ├─ security   (tokens)
                                                     ├─ lifecycle  (registration/policy)
                                                     ├─ telemetry  (headers/logs)
                                                     └─ display    (resolution tree)

trmnl.profile mixins ──render──▶ lib/display_canvas (PIL) ──▶ PNG ──▶ device
        ▲
trmnl.data.watcher (base ORM hooks) marks profiles stale on source edits
```

### Device model mixins (`_inherit = "trmnl.device"`)

| File                        | Responsibility |
|-----------------------------|----------------|
| `trmnl_device.py`           | Field definitions, constants, parsers, MAC normalization, refresh-rate constraint, identity write-protection. |
| `trmnl_device_security.py`  | Token generation, PBKDF2 hashing, timing-safe verification, accepted/presented token slots, promotion. |
| `trmnl_device_lifecycle.py` | Display policy read/write, `/api/setup` registration, unknown-device upsert, token-mismatch recording, auto-accept, manual accept, setup response builders. |
| `trmnl_device_telemetry.py` | Telemetry capture from display headers, `/api/display` activity touch, `/api/log` ingestion + dedup. |
| `trmnl_device_display.py`   | `resolve_display_request` decision tree and all display response builders. |
| `trmnl_device_ui.py`        | Backend-only fields (`device_name`, `sequence`, `log_ids`, computed minutes) and form/bulk actions. |

### Profile model mixins (`_inherit = "trmnl.profile"`)

| File                             | Responsibility |
|----------------------------------|----------------|
| `trmnl_profile.py`               | Field definitions, layout/model selection, view-type availability, constraints, computed status fields. |
| `trmnl_profile_domain.py`        | Filter-domain parsing (`safe_eval`), preset filters, effective-domain building, validation. |
| `trmnl_profile_render.py`        | Re-render trigger logic, renderer dispatch, footer compositing, the `_render_and_store_preview` pipeline. |
| `trmnl_profile_render_data.py`   | ORM → plain-dict conversion for each layout, timezone handling, graph/line/calendar data loading. |
| `trmnl_profile_render_{list,calendar,graph}.py` | Pure PIL renderers producing PNG bytes. |

---

## 4. Data model

### `trmnl.device` — the device

Identity is the **MAC address only**. (`friendly_id` no longer exists.)

**Identity & secrets** (write-protected after create)

| Field | Type | Notes |
|-------|------|-------|
| `mac_address` | Char | required, readonly, indexed, unique. Writable only with `trmnl_allow_identity_update` context key. |
| `api_token_hash` / `api_token_salt` | Char | accepted-token slot (PBKDF2 hash + salt, base64). |
| `last_presented_token_hash` / `last_presented_token_salt` | Char | most-recently-presented token awaiting promotion. |

**Lifecycle**

| Field | Type | Notes |
|-------|------|-------|
| `approval_state` | Selection | `unknown_device` (default) / `token_mismatch` / `accepted`. Indexed. |
| `last_seen_at` | Datetime | last contact with any endpoint. |
| `last_poll_at` | Datetime | last successful `/api/display`. |
| `added_at` | Datetime | registration or manual acceptance. |
| `last_api_call` | Selection | `setup` / `display` / `log`. |

**Configuration (server → device)**

| Field | Type | Notes |
|-------|------|-------|
| `filename` | Char | last served filename; device refreshes when it changes. Default `default_screen.bmp`. |
| `image_url` | Char | absolute URL for the device to fetch. |
| `reset_pending` | Boolean | one-shot; next poll triggers a firmware reset. |
| `desired_refresh_rate` | Integer | **server-commanded** interval in seconds (60–1800, default 60). |
| `desired_refresh_rate_minutes` | Integer | computed/inverse UI pair (minutes), not stored. |

**Telemetry (device → server, readonly)**

| Field | Type | Notes |
|-------|------|-------|
| `firmware_version` | Char | |
| `refresh_rate` | Integer | the interval the device **actually** reports (never overwritten by `desired_refresh_rate`). |
| `battery_voltage` | Float(16,3) | |
| `battery_percentage` | Integer | computed/stored; 3.0 V→0 %, 4.2 V→100 %. |
| `rssi_dbm` | Integer | |
| `rssi_quality` | Selection | computed/stored: excellent ≥ −60, good ≥ −70, fair ≥ −80, else poor. |
| `display_width` / `display_height` | Integer | reported panel dimensions (default canvas 800×480). |

**Backend-only** (from `trmnl_device_ui.py`): `sequence`, `device_name`,
`log_ids`, `last_reported_refresh_rate_minutes` (computed), `accept_button_visible`
(computed — true when policy is `error` and the device is not accepted).

### `trmnl.device.log` — diagnostic log entries

`_order = "created_at desc, id desc"`; unique on `(device_id, log_id)`.
Cascade-deleted with the device. Fields mirror the firmware log schema:
`created_at`, `wifi_rssi_level`, `wifi_status`, `refresh_rate`,
`time_since_last_sleep_start`, `current_fw_version`, `special_function`,
`battery_voltage`, `wakeup_reason`, `free_heap_size`, `max_alloc_size`,
`log_id`, `log_message`, `log_codeline`, `log_sourcefile`, `retry_attempt`,
and a computed `name`.

### `trmnl.profile` — a screen definition

`_order = "sequence, name"`. Binds a device to a model + layout.

- **Identity / source:** `name`, `active`, `sequence`, `device_id`,
  `app_model_id` (→ `ir.model`, filtered to non-technical app models),
  `app_model_name` (related), `user_ids` (render context), `trmnl_layout`
  (`list`/`kanban`/`calendar`/`graph`), `available_view_types` (computed).
- **List/kanban:** `display_field_ids`, `kanban_stage_field_id`,
  `display_limit` (default 20), `display_order` (default `id desc`).
- **Filters:** `filter_preset` (`none`/`my_records`/`today`/`this_week`/
  `this_month`/`overdue`), `filter_domain`, `include_archived`.
- **Graph (bar):** `graph_type` (`bar`/`line`), `graph_groupby_field_id`,
  `graph_measure_field_id`, `graph_sort_order`, `graph_max_groups`, `graph_title`.
- **Graph (line):** `line_date_field_id`, `line_measure_field_id`,
  `line_date_groupby` (`day`/`week`/`month`), `line_max_points`.
- **Calendar:** `calendar_view_mode` (`month`/`week`), `calendar_week_mode`,
  `calendar_reference_mode` (`today`/`custom`), `calendar_reference_date`.
- **Preview / render:** `preview_image` (Binary), `preview_generated_at`,
  `preview_data_stale`, `preview_renderer_version`, `preview_image_html`
  (computed HTML, unsanitized), `auto_refresh_interval_minutes` (default 10).
- **Device delivery status:** `device_last_polled_at`, `device_refresh_rate`,
  `device_next_expected_poll_at` (computed), `display_image_url` (computed),
  `url_warning`, `layout_warning`.

Constraints reject layouts not available for the chosen model, invalid graph
configs (bar needs a group-by; line needs a date field), and malformed custom
filter domains.

---

## 5. HTTP API

All endpoints use `auth="public"`, `csrf=False`, `sitemap=False`. Devices are
embedded systems on arbitrary networks, so authentication is by MAC + API token
rather than Odoo sessions. JSON responses carry `Cache-Control: no-store`.

> **Convention:** `/api/setup`, `/api/display`, and `/api/log` return **HTTP 200**
> in almost all cases; success/error is encoded in the JSON `status` field.

### `GET /api/setup`

Registers/refreshes a device and issues an API token.

Request headers: `ID` (MAC), `FW-Version`.

Success:
```json
{ "status": 200, "api_key": "<raw-token>", "image_url": "<absolute-url>" }
```
Failure (e.g. malformed MAC): `{ "status": 404 }`.

Delegates to `device.upsert_from_setup_headers(headers)` →
`device.build_setup_response(api_token=raw_token)`.

### `GET /api/display`

The core polling endpoint. Reads `ID`, optional `Access-Token`, `FW-Version`,
`Refresh-Rate`, `Battery-Voltage`, `RSSI`, `Width`, `Height`, and `Host` (used to
build the poll base URL; client IP is also recorded for reachability checks).

Response shapes:

- **Serve image** (accepted device): `{ "status": 0, "filename", "image_url",
  "refresh_rate" }` where `refresh_rate` is the device's `desired_refresh_rate`.
- **Error image** (error policy, unknown/mismatch): `{ "status": 0,
  "filename": "unauthorized_screen.bmp", "image_url": "<unauthorized-url>",
  "refresh_rate": 60 }`.
- **Per-device reset** (`reset_pending`): a full display payload plus
  `"reset_firmware": true` with `"status": 0`; the device record is then deleted.
- **Factory-reset policy:** `{ "status": 500 }` (record deleted/not created).

Delegates to `device.resolve_display_request(headers)` →
`DisplayResolutionResult(device, payload, record_status)`.

### `POST /api/log`

Ingests structured device logs. Headers: `ID`, `Access-Token`. Body:
`{ "logs": [ { id, created_at, wifi_signal, wifi_status, refresh_rate,
sleep_duration, firmware_version, special_function, battery_voltage, wake_reason,
free_heap_size, max_alloc_size, message, source_line, source_path, retry } ] }`.

- Success → **HTTP 204** (empty body).
- Missing identity / bad token → **HTTP 401** (empty body).

Entries are deduplicated by `(device_id, log_id)` and only accepted for devices
in the `accepted` state. Delegates to
`device.ingest_logs_from_payload(headers, payload)`.

### `GET /api/profile/image/<int:profile_id>`

Serves the rendered profile PNG to the device (and to admins).

- Returns `image/png` with `Cache-Control: no-store` and an `ETag` digest when
  available; **404** if missing.
- Authorization: Odoo system admins (`base.group_system`) may fetch without a
  token; otherwise a matching `Access-Token` (query param or header) is required
  against `profile.device_id._verify_api_token(...)`.

---

## 6. Display policy & the resolution decision tree

The behaviour for unknown / mismatched devices is governed by the system
parameter **`trmnl.display_unknown_device_policy`** (default `error`):

| Policy | Behaviour |
|--------|-----------|
| `error` (default) | Record/refresh the device as `unknown_device` (or `token_mismatch`), store the presented token for admin review, and serve the **unauthorized image**. |
| `auto_accept` | Adopt the presented token, promote to `accepted`, and serve the real display payload. |
| `factory_reset` | Return `{ "status": 500 }` and delete any record — instructing the device to wipe itself. |

`resolve_display_request` dispatches as follows:

1. **MAC missing/invalid** → unauthorized image (`missing_identity`).
2. **`reset_pending` set** → `build_reset_response()` (`status:0` +
   `reset_firmware:true`), then delete record (`reset_pending`).
3. **Known `unknown_device`** → policy-driven
   (`_resolve_known_unknown_device_display_request`).
4. **Unknown MAC** → policy-driven (`_resolve_unknown_display_request`); under
   `error`, a stub `unknown_device` record is created with telemetry.
5. **Accepted, token valid** → apply telemetry, record poll, serve display.
6. **Accepted but token invalid/missing** → policy-driven
   (`_resolve_token_mismatch_display_request`): `error` sets `token_mismatch` and
   stores the presented token; `auto_accept` adopts it; `factory_reset` wipes.

The policy is edited via the **Display Policy** wizard (menu) backed by
`_get_display_request_policy` / `_set_display_request_policy`.

---

## 7. Security model

### Tokens

- **Generation:** `secrets.token_urlsafe(32)` — 256 bits of entropy.
- **Hashing:** PBKDF2-HMAC-SHA256, **600 000 iterations**, per-token 16-byte
  random salt; hash and salt stored base64 (`_hash_api_token`).
- **Verification:** timing-safe `hmac.compare_digest` (`_verify_api_token`).
- **Two slots:** the *accepted* slot is the authoritative in-use token (set on
  setup, auto-accept, manual accept, or token adoption); the *presented* slot
  holds a not-yet-trusted token captured during a poll for admin review. Manual
  acceptance calls `_promote_presented_token_to_accepted()`.

### Identity protection

`mac_address` is `readonly` and additionally guarded in `write()`: changing it
requires the `trmnl_allow_identity_update` context key, otherwise `AccessError`.

### Access control

All HTTP endpoints are `auth="public"`. All backend model access is restricted to
**`base.group_system`**:

| Model | R | W | C | U |
|-------|---|---|---|---|
| `trmnl.device` | ✓ | ✓ | ✓ | ✓ |
| `trmnl.device.log` | ✓ | — | — | ✓ |
| `trmnl.profile` | ✓ | ✓ | ✓ | ✓ |
| `trmnl.device.accept/remove/reset.wizard`, `trmnl.display.policy.wizard` | ✓ | ✓ | ✓ | ✓ |

---

## 8. Refresh-rate handling

Two independent fields keep the **command** and the **observation** separate:

| Field | Direction | Source | Units |
|-------|-----------|--------|-------|
| `desired_refresh_rate` | server → device | admin config | seconds (60–1800, default 60) |
| `refresh_rate` | device → server | poll telemetry | seconds (reported) |

The UI exposes minutes via computed/inverse pairs
(`desired_refresh_rate_minutes`, `last_reported_refresh_rate_minutes`). The
bounds (60–1800 s) are enforced by an `@api.constrains` check.

---

## 9. Rendering pipeline

### Trigger logic (`trmnl_profile_render.py`)

A profile re-renders on the next poll when **any** of these hold:

1. no preview exists yet, or
2. `preview_data_stale` is `True` (set by the data watcher), or
3. the `auto_refresh_interval_minutes` window has elapsed since
   `preview_generated_at` (≤ 0 falls back to 10 minutes), or
4. `preview_renderer_version` differs from the installed module version (catches
   renderer changes on module upgrade).

### Pipeline

`_render_and_store_preview` loads the device canvas dimensions, loads records via
the effective domain, dispatches to the correct PIL renderer
(list/kanban/calendar-month/calendar-week/bar/line), composites a footer band
(device label + localized "last updated" timestamp), and persists the PNG plus
metadata. Admins can force a render from the form via **Render Preview**
(`action_render_preview`).

### Active profile selection

On poll, `_resolve_display_image` picks the device's lowest-`sequence` active
profile:
```python
search([("device_id","=",self.id),("active","=",True)],
       limit=1, order="sequence asc, id asc")
```
If none exists, the device falls back to its own `image_url`/`filename`
(default or unauthorized image per state).

### Canvas library (`lib/display_canvas.py`)

Encapsulates the e-ink rendering primitives: panel geometry
(`DISPLAY_WIDTH=800`, `DISPLAY_HEIGHT=480`, `FOOTER_BAND_HEIGHT=26`,
`CONTENT_HEIGHT=454`), a grayscale ink palette, DejaVu font loading with
fallback, text truncation/measuring, list-header drawing, PNG serialization, and
`composite_with_footer(...)`. `lib/net.py` provides `client_can_reach_host` and
`is_device_reachable_base_url` heuristics so the served `image_url` is one the
device can actually reach.

### Built-in images & data watcher

- **`trmnl.image.seeder`** seeds `default_screen.bmp` and
  `unauthorized_screen.bmp` as **public `ir.attachment`** records on
  `post_init_hook` and removes them on `uninstall_hook`, storing the attachment
  IDs in `ir.config_parameter`. URLs are resolved via `/web/image/<id>`.
- **`trmnl.data.watcher`** (`_inherit = "base"`) hooks `create`/`write`/`unlink`
  on all models and flags `preview_data_stale` on active profiles watching the
  changed model. It uses a savepoint so it stays resilient during uninstall.

---

## 10. Backend UI

- **Menu:** root **TRMNL** (system-only) → **Devices**, **Profiles**,
  **Display Policy**.
- **Device list/form:** status badge, telemetry group (battery, signal,
  reported refresh rate, timestamps, `last_api_call`), a logs tab, and header
  actions opening the **Accept / Reset / Remove** wizards. List-view server
  actions provide bulk Accept/Remove/Reset.
- **Profile form:** dynamic groups that show/hide by layout (calendar / graph /
  list-kanban / filters), a **Render Preview** button, the rendered preview, and
  device-delivery status fields.
- **Custom widget** `trmnl_layout_select` (`static/src/js/...`) subclasses Odoo's
  `SelectionField` and narrows the layout dropdown live to
  `available_view_types` for the selected model.
- **Wizards** (`trmnl_device_wizard.py`) share
  `TrmnlDeviceActionWizardMixin`: Accept (promotes the presented token), Remove
  (delete, or reset-and-remove), Reset (schedules `reset_pending`), and Display
  Policy (reads/writes the policy parameter).

---

## 11. Test strategy

Tests live in `addons/trmnl/tests/` (≈23 files), all tagged
`@tagged("-at_install", "post_install")` and run under the `/trmnl` tag via
`make test`. Coverage spans:

- **API (HttpCase):** `test_api_setup`, `test_api_display` (all policy modes),
  `test_api_log`, plus device-image/HTTP rendering checks
  (`test_calendar_device_image`, `test_device_screen_size`).
- **Device model:** refresh-rate compute/inverse/bounds
  (`test_device_refresh_rate`), image sync (`test_device_image_sync`), uninstall
  resilience (`test_module_uninstall`), image seeding/cleanup
  (`test_trmnl_image_seeder`).
- **Profiles & rendering:** PIL renderers (`test_profile_renderers`,
  `test_graph_chart`, `test_line_chart`), filter domains
  (`test_profile_filter_domain`), view types (`test_profile_view_types`),
  staleness (`test_profile_data_staleness`), preview button
  (`test_profile_render_preview`), layout (`test_profile_dashboard_layout`),
  image quality/URL/poll-timestamp, and model-selector domain.

Shared helpers: `test_api_common.py` (`TrmnlApiHttpCaseMixin` — header builders,
JSON helpers, device registration) and `test_common.py` (device/model fixtures).

---

## 12. Development & infrastructure

- **`Makefile`** targets: `start`/`bootstrap`, `watch` (auto-upgrade on change),
  `update`, `test`, `stop`, `down`, `downv`, `restart`, `logs`, `shell`. Override
  `COMPOSE` etc. in `local.mk`.
- **`compose.yaml`:** `db` (`postgres:18.3`, healthcheck) and `odoo`
  (`odoo-custom:19.0`, port 8069, `--dev=reload,xml`, addons bind-mounted).
- **`Dockerfile`:** `odoo:19.0-20260305` + `fonts-dejavu-core` + pip install from
  `requirements.txt` (`pillow==12.1.1`).
- **`scripts/odoo-dev.sh`:** drives install/upgrade/watch/test, including an
  isolated `odoo_test` database for the test target.
- **Quality:** `pyproject.toml` configures Ruff (lint + format, ignoring `F401`);
  `.pre-commit-config.yaml` runs Ruff and the standard file hygiene / JSON / XML /
  YAML checks.
- **`__manifest__.py`** loads: `security/ir.model.access.csv`, the four view
  files, and registers the layout-select JS asset; `post_init_hook` /
  `uninstall_hook` manage the seeded images.
