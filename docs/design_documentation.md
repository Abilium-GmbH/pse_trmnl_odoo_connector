# TRMNL Odoo Connector — Design Documentation

## Table of Contents

1. [Overview](#overview)
2. [Repository Structure](#repository-structure)
3. [Architecture](#architecture)
4. [Design Patterns](#design-patterns)
5. [Data Model](#data-model)
6. [HTTP API](#http-api)
7. [Device Lifecycle](#device-lifecycle)
8. [Security Model](#security-model)
9. [Display Policy System](#display-policy-system)
10. [Refresh Rate System](#refresh-rate-system)
11. [Telemetry and Log Ingestion](#telemetry-and-log-ingestion)
12. [Backend UI](#backend-ui)
13. [Test Strategy](#test-strategy)
14. [Development Workflow](#development-workflow)
15. [Known Constraints and Design Decisions](#known-constraints-and-design-decisions)

---

## Overview

This module integrates [TRMNL](https://trmnl.com) e-ink display devices with Odoo 19. It acts as a self-hosted replacement for the TRMNL cloud, implementing the device-facing HTTP protocol (`/api/setup`, `/api/display`, `/api/log`) entirely within Odoo. Administrators manage devices, configure display content, and control access policy through the standard Odoo backend.  

This design documentation reflects the current stage of the main branch as of 20.05.2026 and is subject to change.

The renderer subsystem — responsible for generating dynamic content per device — is actively being developed on the feature branch `feature/generic-trmnl-rendering-integration` and has not yet been merged into main. The `image_url` and `filename` fields currently serve static default values (`DEFAULT_IMAGE_URL`, `DEFAULT_FILENAME`). 

**Technology stack:**
- Odoo 19 (Python, XML views, ORM)
- PostgreSQL 18
- Docker / Docker Compose
- Pillow, Requests (declared as Python external dependencies)

---

## Repository Structure

```
.
├── addons/
│   └── trmnl/
│       ├── __init__.py
│       ├── __manifest__.py
│       ├── controllers/
│       │   ├── __init__.py
│       │   ├── trmnl_api_base.py          # Shared controller helpers (mixin)
│       │   ├── device_setup_controller.py # GET /api/setup
│       │   ├── device_display_controller.py # GET /api/display
│       │   └── device_log_controller.py   # POST /api/log
│       ├── models/
│       │   ├── __init__.py
│       │   ├── trmnl_device.py            # Core model, fields, ORM overrides
│       │   ├── trmnl_device_security.py   # Token hashing and verification
│       │   ├── trmnl_device_lifecycle.py  # Registration, acceptance, response builders
│       │   ├── trmnl_device_telemetry.py  # Telemetry capture and log ingestion
│       │   ├── trmnl_device_display.py    # Display request resolution and response builders
│       │   ├── trmnl_device_ui.py         # Backend UI fields and actions
│       │   ├── trmnl_device_log.py        # Device log entry model
│       │   └── trmnl_device_wizard.py     # Confirmation wizards
│       ├── security/
│       │   └── ir.model.access.csv
│       ├── views/
│       │   ├── trmnl_device_views.xml
│       │   ├── trmnl_device_wizard_views.xml
│       │   └── trmnl_menu.xml
│       └── tests/
│           ├── __init__.py
│           ├── test_api_common.py          # Shared test helpers and mixins
│           ├── test_api_setup.py
│           ├── test_api_display.py
│           ├── test_api_log.py
│           └── test_device_refresh_rate.py
├── compose.yaml
├── Dockerfile
├── requirements.txt
├── Makefile
├── scripts/
│   └── odoo-dev.sh
└── docs/
    └── curl_commands.txt
```

---

## Architecture

### Layering

The module follows Odoo's conventional MVC structure with an additional horizontal decomposition of the model layer into focused mixins.

```
┌─────────────────────────────────────────────────┐
│                  Odoo HTTP Layer                │
│  DeviceSetupController                          │
│  DeviceDisplayController                        │
│  DeviceLogController                            │
│         (all inherit TrmnlApiControllerMixin)   │
└────────────────────┬────────────────────────────┘
                     │ calls model methods
┌────────────────────▼────────────────────────────┐
│               trmnl.device model                │
│  TrmnlDevice (core fields, ORM overrides)       │
│  + TrmnlDeviceSecurityMixin  (_inherit)         │
│  + TrmnlDeviceLifecycleMixin (_inherit)         │
│  + TrmnlDeviceTelemetryMixin (_inherit)         │
│  + TrmnlDeviceDisplayMixin   (_inherit)         │
│  + TrmnlDeviceUiExtension    (_inherit)         │
└────────────────────┬────────────────────────────┘
                     │ One2many
┌────────────────────▼────────────────────────────┐
│           trmnl.device.log model                │
│  TrmnlDeviceLog                                 │
└─────────────────────────────────────────────────┘
```

### Model Mixin Responsibilities

The `trmnl.device` model is decomposed using Odoo's `_inherit` mechanism. Each mixin has a single, clearly bounded responsibility:

| Mixin / Class | File | Responsibility |
|---|---|---|
| `TrmnlDevice` | `trmnl_device.py` | Core fields, constants, ORM overrides, primitive helpers |
| `TrmnlDeviceSecurityMixin` | `trmnl_device_security.py` | PBKDF2 token hashing, verification, accepted/presented token slots |
| `TrmnlDeviceLifecycleMixin` | `trmnl_device_lifecycle.py` | Registration from `/api/setup`, stub creation, auto-accept, manual accept, response builders |
| `TrmnlDeviceTelemetryMixin` | `trmnl_device_telemetry.py` | Telemetry write-back from display headers, log entry ingestion from `/api/log` |
| `TrmnlDeviceDisplayMixin` | `trmnl_device_display.py` | Display request resolution decision tree, display/reset/error response builders |
| `TrmnlDeviceUiExtension` | `trmnl_device_ui.py` | Backend-only fields (sequence, device_name, log_ids), computed UI fields, wizard-opening actions, bulk list actions |

### Controller Design

All three controllers inherit `TrmnlApiControllerMixin` for:
- `_mask_identifier()` — partial masking of MAC addresses in log output.
- `_json_response()` — consistent JSON serialization with correct headers (`Content-Type`, `Cache-Control`, `Pragma`).

Controllers are deliberately thin: they extract headers, delegate all business logic to model methods, and map the returned `record_status` string to an HTTP status code.

---

## Design Patterns

The implementation uses several established design patterns and architectural principles.

#### Model-View-Controller

The module follows Odoo's standard Model-View-Controller structure. Controllers handle HTTP requests, models contain business logic and persistence, and XML views define the backend user interface.

This separation keeps device communication, business logic, and user interface definitions clearly separated.

#### Mixin Pattern

The `trmnl.device` model is split into several focused mixins using Odoo's `_inherit` mechanism.

Each mixin is responsible for one specific area, such as security, lifecycle handling, telemetry, display logic, or backend UI actions. This avoids one large monolithic model file and improves maintainability.

#### Thin Controller Pattern

The HTTP controllers are intentionally kept thin. They extract request data, call model methods, and transform the result into an HTTP response.

The actual business logic remains in the model layer, where it can be reused and tested more easily.

#### Strategy-like Policy System

The display policy system follows a strategy-like approach. Depending on the configured policy, the system handles unknown devices and token mismatches differently.

The supported policies are:

- `error`
- `auto_accept`
- `factory_reset`

Because the active policy is loaded from `ir.config_parameter`, the behavior can be changed without modifying the controller code or restarting the server.

---

## Data Model

### `trmnl.device`

The primary model. All device state is stored here.

#### Identity Fields

| Field | Type | Notes |
|---|---|---|
| `mac_address` | `Char` | Canonical uppercase colon-separated MAC. Unique. Write-protected after creation. |
| `friendly_id` | `Char` | Short human-readable ID (`TRMNL-XXXXXX`). Assigned during `/api/setup` or on manual acceptance. Unique. Write-protected after creation. |
| `api_token_hash` | `Char` | PBKDF2-SHA256 hash (base64) of the accepted API token. |
| `api_token_salt` | `Char` | Random salt (base64) for the accepted token hash. |
| `last_presented_token_hash` | `Char` | Hash of the most recent token presented in a display call that did not match the accepted token. Used during manual acceptance. |
| `last_presented_token_salt` | `Char` | Salt for the presented token hash. |

Identity fields are guarded by a `write()` override; mutation requires `trmnl_allow_identity_update=True` in the ORM context.

#### Lifecycle Fields

| Field | Type | Notes |
|---|---|---|
| `approval_state` | `Selection` | `accepted`, `token_mismatch`, `unknown_device` |
| `registration_source` | `Selection` | `setup`, `display`, `manual` |
| `first_seen_at` | `Datetime` | UTC, set on record creation. |
| `last_seen_at` | `Datetime` | UTC, updated on every valid interaction. |
| `last_setup_at` | `Datetime` | UTC, updated on `/api/setup`. |
| `last_display_at` | `Datetime` | UTC, updated on a successful display response. |
| `last_log_at` | `Datetime` | UTC, updated after any `/api/log` submission from an accepted device. |
| `accepted_at` | `Datetime` | UTC, set when the device transitions to `accepted`. |
| `last_access_denied_at` | `Datetime` | UTC, set on any rejected request. |
| `setup_request_count` | `Integer` | Incremented on each `/api/setup` call. |
| `display_request_count` | `Integer` | Incremented on each successful display response. |
| `log_entry_count` | `Integer` | Running total of stored log entries. |
| `invalid_token_count` | `Integer` | Count of display calls rejected for token mismatch. |
| `display_denied_count` | `Integer` | Count of display calls rejected for non-token reasons. |

#### Configuration Fields (server → device)

| Field | Type | Notes |
|---|---|---|
| `filename` | `Char` | Image filename sent to the device. Changing this triggers a refresh on the device side. |
| `image_url` | `Char` | URL the device will fetch and display. |
| `desired_refresh_rate` | `Integer` | Seconds. Stored internally, exposed in the UI as `desired_refresh_rate_minutes`. Range: 60–1800 s. |
| `reset_pending` | `Boolean` | One-shot flag: when `True`, the next `/api/display` poll delivers a `reset_firmware` response and the record is deleted. |

#### Telemetry Fields (device → server, read-only)

| Field | Type | Notes |
|---|---|---|
| `firmware_version` | `Char` | Last reported firmware version. |
| `refresh_rate` | `Integer` | Seconds last reported by the device in display poll headers. Not used for the response; `desired_refresh_rate` is used instead. |
| `battery_voltage` | `Float` | Last reported voltage. |
| `battery_percentage` | `Integer` | Computed from `battery_voltage` using a configurable min/max voltage window. |
| `rssi_dbm` | `Integer` | Raw RSSI in dBm. |
| `rssi_quality` | `Selection` | Bucketed quality label: `excellent`, `good`, `fair`, `poor`, `unknown`. |
| `display_width` | `Integer` | Pixels, from display headers. |
| `display_height` | `Integer` | Pixels, from display headers. |
| `wifi_status` | `Char` | Last reported Wi-Fi status string. |

#### UI-only Fields (from `TrmnlDeviceUiExtension`)

| Field | Type | Notes |
|---|---|---|
| `sequence` | `Integer` | Manual drag-to-sort order in the list view. |
| `device_name` | `Char` | Admin-facing label. Not transmitted to the device. |
| `log_ids` | `One2many` | Read-only relation to `trmnl.device.log`. |
| `desired_refresh_rate_minutes` | `Integer` (computed) | UI proxy for `desired_refresh_rate`. Compute/inverse pair. |
| `last_reported_refresh_rate_minutes` | `Integer` (computed) | `refresh_rate` converted to minutes for display. |
| `accept_button_visible` | `Boolean` (computed) | Controls visibility of the Accept Device button. |

---

### `trmnl.device.log`

Stores individual log entries submitted by devices via `/api/log`.

| Field | Type | Notes |
|---|---|---|
| `device_id` | `Many2one` | Parent device. `ondelete="cascade"`. |
| `log_id` | `Integer` | Device-assigned log ID. Unique per device (enforced by DB constraint). |
| `created_at` | `Datetime` | UTC datetime converted from the Unix epoch value in the payload. |
| `log_message` | `Text` | Free-text log message. |
| `log_codeline` | `Integer` | Source line number. |
| `log_sourcefile` | `Char` | Source file path. |
| `retry_attempt` | `Integer` | Retry counter from the device. |
| `wifi_rssi_level` | `Integer` | RSSI at the time of the log entry. |
| `wifi_status` | `Char` | Wi-Fi status string. |
| `refresh_rate` | `Integer` | Refresh rate in seconds at the time of the log entry. |
| `time_since_last_sleep_start` | `Integer` | Sleep duration in seconds. |
| `current_fw_version` | `Char` | Firmware version at the time of the log entry. |
| `special_function` | `Char` | Device special function string. |
| `battery_voltage` | `Float` | Battery voltage at the time of the log entry. |
| `wakeup_reason` | `Char` | Wake reason string. |
| `free_heap_size` | `Integer` | Free heap in bytes. |
| `max_alloc_size` | `Integer` | Largest contiguous allocatable block in bytes. |
| `name` | `Char` (computed, stored) | Human-readable label derived from `log_id`, `log_message`, `log_sourcefile`, and `log_codeline`. |

A DB-level unique constraint on `(device_id, log_id)` prevents duplicate log entries.

---

## HTTP API

All endpoints are public (`auth="public"`) and CSRF-exempt. They are designed to be called directly by TRMNL firmware.

### `GET /api/setup`

Registers a new device. Called by the device on first boot or after a factory reset.

**Request headers:**

| Header | Required | Description |
|---|---|---|
| `ID` | Yes | Device MAC address |
| `FW-Version` | No | Firmware version string |

**Success response (`200`):**
```json
{
  "status": 200,
  "api_key": "<raw_token>",
  "friendly_id": "TRMNL-XXXXXX",
  "image_url": "<url>"
}
```

**Error response (`200`):**
```json
{ "status": 404 }
```

The endpoint always returns HTTP 200; protocol-level errors are communicated via the `status` field in the JSON body. A `404` body is returned when the MAC is missing, malformed, or already registered without a pending reset.

**Special case — `reset_pending`:** If the MAC address matches a device with `reset_pending = True`, that record is deleted and a fresh registration proceeds normally, issuing a new token and friendly ID.

---

### `GET /api/display`

Polled by the device at the configured refresh rate to retrieve the current image URL and next refresh interval.

**Request headers:**

| Header | Required | Description |
|---|---|---|
| `ID` | Yes | Device MAC address |
| `Access-Token` | Yes | Raw API token |
| `Refresh-Rate` | No | Device-reported current refresh rate (seconds) |
| `Battery-Voltage` | No | Battery voltage |
| `FW-Version` | No | Firmware version |
| `RSSI` | No | RSSI in dBm |
| `Width` | No | Display width in pixels |
| `Height` | No | Display height in pixels |

**Success response (`200`):**
```json
{
  "status": 0,
  "filename": "<filename>",
  "image_url": "<url>",
  "refresh_rate": 60
}
```

**Reset response (`200`):** Same as the success response, plus `"reset_firmware": true`.

**Error responses (`200`):**
```json
{ "status": 202 }   // Unknown device or token mismatch under the error policy
{ "status": 500 }   // Under the factory-reset policy
```

The endpoint always returns HTTP 200. See [Display Policy System](#display-policy-system) for the full decision tree.

---

### `POST /api/log`

Receives batched log entries from the device.

**Request headers:**

| Header | Required | Description |
|---|---|---|
| `ID` | Yes | Device MAC address |
| `Access-Token` | Yes | Raw API token |
| `Content-Type` | Yes | `application/json` |

**Request body:**
```json
{
  "logs": [ { ... }, { ... } ]
}
```

**Success response:** HTTP `204` with an empty body.

**Error response:** HTTP `401` with an empty body — returned for missing identity, unknown device, invalid token, or any device not in the `accepted` state.

---

## Device Lifecycle

### Registration via `/api/setup`

1. MAC address is normalized and validated.
2. If the MAC already exists with `reset_pending = True`, the old record is deleted and registration proceeds as if the MAC were new.
3. If the MAC already exists without a pending reset, a `404` body is returned.
4. A new record is created with `approval_state = accepted`, a freshly generated `friendly_id`, and a newly generated API token (hashed).
5. The raw token is returned once in the setup response and is never stored in plaintext.

### Stub Creation via `/api/display` (error policy)

When a display request arrives from an unknown MAC under the error policy, a stub `trmnl.device` record is created with `approval_state = unknown_device`. The presented token is stored hashed in `last_presented_token_hash/salt` so an administrator can later accept the device without requiring a factory reset.

### Manual Acceptance

An administrator opens the Accept Device wizard. The wizard calls `device.accept_device()`, which:
1. Copies `last_presented_token_hash/salt` → `api_token_hash/salt`.
2. Clears the presented-token slot.
3. Sets `approval_state = accepted` and `accepted_at`.
4. Generates a `friendly_id` if absent (for `unknown_device` records that bypassed `/api/setup`).

### Factory Reset (per-device)

An administrator schedules a reset via the Reset Device wizard or the bulk Reset Selected action. This sets `reset_pending = True`. On the device's next `/api/display` poll:
1. The `reset_pending` check runs before token validation, so the reset signal is delivered regardless of whether the token is valid.
2. A `reset_firmware: true` response is returned.
3. The device record is deleted immediately.

If the device calls `/api/setup` before polling `/api/display`, the `reset_pending` flag is cleared and the device is re-registered normally.

---

## Security Model

### API Token Lifecycle

Tokens are generated using `secrets.token_urlsafe(32)` (256 bits of entropy). They are never stored in plaintext. The storage scheme uses PBKDF2-HMAC-SHA256 with a 16-byte random salt per token and 600,000 iterations (per the OWASP Password Storage Cheat Sheet 2026 recommendation).

Comparison uses `hmac.compare_digest` to prevent timing attacks.

Two token slots exist per device:

- **`api_token_hash/salt`** — the authoritative accepted token. Written during `/api/setup`, on auto-accept, or on manual acceptance.
- **`last_presented_token_hash/salt`** — the most recently presented-but-unmatched token. Allows the admin to adopt a device's current token without requiring a factory reset.

### Identity Field Protection

`mac_address` and `friendly_id` are write-protected at the ORM level via a `write()` override. Any write to these fields without the `trmnl_allow_identity_update=True` context key raises `AccessError`. All internal code that legitimately needs to mutate these fields passes the context key explicitly.

### Access Control

All device-facing endpoints use `auth="public"` because TRMNL firmware does not carry Odoo session credentials. Authentication is handled at the application layer via MAC address + API token verification before any data is served or stored.

The Odoo backend UI is restricted to `base.group_system` (Odoo administrators) via `ir.model.access.csv`.

---

## Display Policy System

The display policy controls how the server responds to `/api/display` requests from devices that are not yet accepted or whose token does not match. The policy is stored in `ir.config_parameter` under the key `trmnl.display_unknown_device_policy`.

### Policy Options

| Policy constant | Value | Behaviour |
|---|---|---|
| `DISPLAY_POLICY_ERROR` | `"error"` | Return `{"status": 202}`. Create a stub record for unknown MACs. Record the token mismatch for known MACs. Admin must manually accept. |
| `DISPLAY_POLICY_AUTO_ACCEPT` | `"auto_accept"` | Adopt the presented token immediately. Register unknown devices. Serve display content on the same request. |
| `DISPLAY_POLICY_FACTORY_RESET` | `"factory_reset"` | Return `{"status": 500}`. Do not create any records. Under token mismatch, delete the existing record. |

### Resolution Decision Tree

```
GET /api/display
│
├── Missing MAC?  → {"status": 202}, no record created
│
├── MAC has reset_pending?  → build_reset_response(), delete record
│
├── MAC unknown?
│   ├── auto_accept         → register_or_adopt_from_display_headers(), serve display
│   ├── factory_reset       → {"status": 500}, no record created
│   └── error (default)     → create stub record, {"status": 202}
│
└── MAC known?
    ├── token valid + state==accepted  → serve display (normal path)
    ├── token valid + state!=accepted  → {"status": 202}, record_access_denied()
    └── token invalid?
        ├── auto_accept  → adopt token, serve display
        ├── factory_reset  → {"status": 500}, delete record
        └── error          → record_token_mismatch_from_display(), {"status": 202}
```

The policy is read from `ir.config_parameter` on every request, so changes take effect immediately without a server restart. Administrators change the policy through the Display Policy wizard accessible from the TRMNL menu.

---

## Refresh Rate System

The refresh rate controls how frequently the device polls `/api/display`.

### Internal vs. UI Representation

Internally, `desired_refresh_rate` stores seconds (an integer). The UI always presents and accepts minutes via the computed/inverse field pair `desired_refresh_rate_minutes`.

Valid range: **1 minute (60 s) to 30 minutes (1800 s)**, enforced by the `_check_desired_refresh_rate_bounds` constraint on `create` and `write`.

Constants exported from `trmnl_device.py`:

| Constant | Value | Purpose |
|---|---|---|
| `SECONDS_PER_MINUTE` | `60` | Unit conversion |
| `REFRESH_RATE_MIN_SECONDS` | `60` | Lower bound |
| `REFRESH_RATE_MAX_SECONDS` | `1800` | Upper bound |
| `DEFAULT_REFRESH_RATE` | `60` | Default for new devices |

### Telemetry vs. Desired Rate

The device reports its current refresh interval in the `Refresh-Rate` header on every display poll. This value is written to the **read-only** `refresh_rate` field (telemetry). It does not overwrite `desired_refresh_rate`. This separation allows an administrator to change the commanded rate independently of what the device currently uses, with the new rate taking effect on the device's next poll.

---

## Telemetry and Log Ingestion

### Display Telemetry

On every successful `/api/display` response, `_apply_display_telemetry()` is called to persist the values reported in the request headers: `firmware_version`, `refresh_rate` (last reported), `battery_voltage`, `rssi_dbm`, `display_width`, `display_height`. The `desired_refresh_rate` field is never touched by this method.

### Log Ingestion

`ingest_logs_from_payload()` processes the `logs` array from a `/api/log` POST body:

1. Validates MAC address and token; returns `"missing_identity"` or `"unauthorized"` if invalid.
2. Only processes logs for devices in the `accepted` state.
3. For each entry in the array, calls `_prepare_log_values()` to map the raw JSON keys to model field names.
4. Checks for existing `(device_id, log_id)` pairs to prevent duplicate storage (the unique constraint provides a DB-level backstop, but the Python check avoids raising exceptions in normal operation).
5. Updates `last_log_at` and `log_entry_count` on the parent device record.

Unix epoch timestamps from the device are converted to naive UTC `datetime` objects using `_unix_epoch_to_datetime()`.

---

## Backend UI

### Menu Structure

```
TRMNL
├── Devices          (list + form view of trmnl.device)
└── Display Policy   (transient wizard form)
```

### Device List View

Columns: Sequence (drag handle), Friendly ID, Device Name, MAC Address, Status (badge widget), Image Filename, Last Seen At, Refresh Rate (min), Battery %, Signal Strength.

List-level server actions (Action drop-down):
- **Accept Selected** — accepts all selected non-accepted devices that have a stored presented token. Devices without a token are skipped with a `UserError` listing the skipped names.
- **Remove Selected** — deletes records immediately.
- **Reset Selected** — sets `reset_pending = True` on all selected records.

### Device Form View

- Header buttons: Accept Device (conditionally visible), Reset Device, Remove Device.
- Status bar: `unknown_device` → `token_mismatch` → `accepted`.
- Configuration group: Image URL, Refresh Rate (minutes), Image Filename (read-only).
- Telemetry group: Battery %, Signal Strength, Last Reported Refresh Rate, Last Seen At, Last Display At.
- Logs tab: Read-only embedded list of `trmnl.device.log` records.

The Accept Device button is only visible when the display policy is `error` and the device is not yet accepted. This is enforced by the `accept_button_visible` computed field.

### Wizards

All wizards use `TransientModel` and are opened as modal dialogs (`target="new"`).

| Wizard | Purpose |
|---|---|
| `trmnl.device.accept.wizard` | Confirms manual acceptance of a device by adopting its last-presented token. |
| `trmnl.device.remove.wizard` | Offers Remove (immediate) or Reset & Remove (deferred via `reset_pending`) options. |
| `trmnl.device.reset.wizard` | Confirms scheduling a factory reset (`reset_pending = True`). |
| `trmnl.display.policy.wizard` | Reads and writes the global display policy from/to `ir.config_parameter`. |

`TrmnlDeviceActionWizardMixin` is an abstract `AbstractModel` providing shared `device_id`, `device_display_name`, and navigation helpers to the three device-action wizards.

---

## Test Strategy

Tests are located in `addons/trmnl/tests/` and use Odoo's `HttpCase` (for endpoint tests) and `TransactionCase` (for model unit tests). All tests are tagged `post_install` and `-at_install`.

### Test Modules

| Module | Type | Coverage |
|---|---|---|
| `test_api_setup.py` | `HttpCase` | `/api/setup` — success, duplicate MAC rejection, missing/invalid ID, `reset_pending` re-registration |
| `test_api_display.py` | `HttpCase` | `/api/display` — all three policies (error, auto-accept, factory-reset), per-device reset flow, refresh rate separation, policy persistence |
| `test_api_log.py` | `HttpCase` | `/api/log` — batched log storage, empty payload, missing identity, unknown device, invalid/missing token, unknown_device stub rejection |
| `test_device_refresh_rate.py` | `TransactionCase` | Compute/inverse round-trips, boundary constraint enforcement |

### Shared Test Helpers (`TrmnlApiHttpCaseMixin`)

- `_register_device_through_setup()` — registers a device via the real HTTP endpoint; returns device record, raw token, and raw payload.
- `_display_headers()`, `_log_headers()`, `_setup_headers()` — header factory methods.
- `_log_entry()`, `_log_payload()` — fixture factories for log payloads.
- `_set_display_policy()`, `_get_display_policy()` — read/write the global display policy config param.
- `_assert_display_success_payload()` — asserts the standard successful display response shape.

### Running Tests

```bash
make test
```

This bootstraps the environment first (ensuring the module is installed), then runs the Odoo test runner scoped to the `trmnl` module tag.

### Test Results

The automated tests cover the main functional and security-relevant behavior of the module.

The tested areas include:

- device registration through `/api/setup`
- display polling through `/api/display`
- log ingestion through `/api/log`
- handling of missing or invalid device identifiers
- token validation and token mismatch handling
- unknown device handling
- display policy behavior for `error`, `auto_accept`, and `factory_reset`
- refresh rate conversion and boundary validation
- telemetry persistence
- reset and re-registration behavior

Golden image tests were initially considered but were ultimately not implemented because rendering behavior is already validated through automated rendering-related test cases.

In addition to automated tests, manual testing was performed with real TRMNL devices. These tests verified that devices can connect to the Odoo server, poll the display endpoint, receive the configured refresh rate, and react to reset behavior. In addition manual testing was also used to identify usability issues in the UI.

The test concept itself is maintained in a separate document. This design documentation therefore summarizes the test strategy and test results, while the detailed test cases are described in the dedicated test concept.

---

## Development Workflow

See `docs/development.md` for the full guide. Quick reference:

| Command | Effect |
|---|---|
| `make` / `make start` | Start containers, install module if needed |
| `make watch` | Start and watch `addons/trmnl/` for changes; auto-upgrades on save |
| `make update` | Force module upgrade and restart Odoo |
| `make test` | Bootstrap + run tests |
| `make logs` | Stream Odoo logs |
| `make shell` | Shell inside the Odoo container |
| `make downv` | Destroy all containers and volumes (full reset) |

The `scripts/odoo-dev.sh` script handles Postgres readiness waiting, database existence checks, and conditional install vs. upgrade logic.

---

## Known Constraints and Design Decisions

### No Plaintext Token Storage

The raw API token is generated once and returned in the `/api/setup` response. It is immediately hashed and the plaintext is discarded. If a token is lost (e.g., the setup response was not received), the device must be factory-reset to obtain a new one.

### PBKDF2 Iteration Count

600,000 iterations of PBKDF2-HMAC-SHA256 are used, matching the OWASP recommendation at the time of writing. Increasing this value in future requires a migration to re-hash all existing stored tokens.

### `reset_pending` vs. Immediate Deletion

Devices are not deleted immediately on a reset request because the firmware must receive the `reset_firmware: true` signal on its next poll to actually clear its stored Wi-Fi credentials and API key. Immediate deletion would leave the physical device in an inconsistent state, continuing to poll with stale credentials.

### `desired_refresh_rate` vs. `refresh_rate`

Two separate fields exist for the refresh rate to prevent the device from overwriting an admin-configured value on its next poll. `refresh_rate` is purely telemetry (what the device is currently doing). `desired_refresh_rate` is a command (what the server wants the device to do next).

### Display Policy Stored in `ir.config_parameter`

The policy is a global setting, not per-device, and is stored in `ir.config_parameter` rather than a dedicated settings model. It is read on every request, so policy changes are effective immediately with no restart required. An invalid stored value falls back to `DISPLAY_POLICY_ERROR`.

### Identity Field Protection Context Key

The `trmnl_allow_identity_update` context key is used internally to allow controlled mutation of `mac_address` and `friendly_id` during lifecycle transitions (e.g., clearing `reset_pending`, promoting a presented token). This pattern avoids duplicating the protection logic while keeping the guard visible at the call sites.
