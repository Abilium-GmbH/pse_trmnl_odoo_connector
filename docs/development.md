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
