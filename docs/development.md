# Development Guide

This document is for contributors working on the TRMNL Odoo connector.

## Prerequisites

- Docker Compose or Podman Compose
- `make`

The Makefile uses `docker compose` by default. For a local override, create `local.mk` in the repo root.

Example:

```makefile
COMPOSE=podman compose
```

## Make commands

### `make start`
Starts the database and Odoo, waits for Postgres to be ready, and ensures the `trmnl` module is installed. On a fresh database, it installs `base` and `trmnl` automatically.

### `make bootstrap`
Alias for `make start`.

### `make watch`
Runs `make start` and then watches `addons/trmnl/` for changes. When files change, it upgrades the module so Python, XML, and data changes are picked up with minimal manual work.

### `make update`
Forces a module upgrade for `trmnl` and restarts Odoo. Use this when changes are not reflected automatically.

### `make test`
Bootstraps the environment first, then runs the Odoo test suite for `trmnl`.

### `make stop`
Stops Odoo and Postgres without removing containers or data.

### `make down`
Removes containers and network, but keeps persistent volumes.

### `make downv`
Removes containers, network, and volumes. This deletes all local database data.

### `make restart`
Restarts only the Odoo container.

### `make logs`
Streams the Odoo logs.

### `make shell`
Opens a shell inside the Odoo container.

## Normal workflow

### First run
Use:

```bash
make
```

This initializes the database and installs the module automatically.  
NOTE: `make` defaults to: `make start`

### Daily development
Use:

```bash
make watch
```

Then edit files in `addons/trmnl/`. Python changes reload quickly, and module-level changes are upgraded automatically.

### When you need a manual refresh
Use:

```bash
make update
```

### When you want to test
Use:

```bash
make test
```

### Reset options

Keep data:

```bash
make down
make start
```

Delete everything and start fresh:

```bash
make downv
make start
```

---

## Testing the API manually

Replace `192.168.x.x` with your machine's LAN IP and the token with a real value from a registered device.

### Get your LAN IP

```bash
hostname -I
```

### `/api/setup` — register a device

```bash
curl -X GET "http://192.168.x.x:8069/api/setup" \
  -H "ID: AA:BB:CC:DD:EE:FF" \
  -H "FW-Version: 1.5.2"
```

### `/api/display` — poll for the current image

```bash
curl -X GET "http://192.168.x.x:8069/api/display" \
  -H "ID: AA:BB:CC:DD:EE:FF" \
  -H "Access-Token: <api_key from setup response>" \
  -H "Refresh-Rate: 1800" \
  -H "Battery-Voltage: 4.1" \
  -H "FW-Version: 1.5.2" \
  -H "RSSI: -69" \
  -H "Width: 800" \
  -H "Height: 480"
```

### `/api/log` — send a device log entry

```bash
curl -X POST "http://192.168.x.x:8069/api/log" \
  -H "ID: AA:BB:CC:DD:EE:FF" \
  -H "Access-Token: <api_key from setup response>" \
  -H "Accept: application/json, */*" \
  -H "Content-Type: application/json" \
  -d '{
    "logs": [
      {
        "created_at": 1745000000,
        "id": 42,
        "message": "Image render failed: unexpected EOF",
        "source_line": 318,
        "source_path": "src/bl.cpp",
        "wifi_signal": -67,
        "wifi_status": "Connected",
        "refresh_rate": 1800,
        "sleep_duration": 145,
        "firmware_version": "1.5.2",
        "special_function": "None",
        "battery_voltage": 3.95,
        "wake_reason": "Timer",
        "free_heap_size": 48320,
        "max_alloc_size": 38912
      }
    ]
  }'
```
