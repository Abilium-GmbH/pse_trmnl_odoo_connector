# Development Guide

This document is for contributors working on the TRMNL Odoo connector.

## Prerequisites

- Docker Compose or Podman Compose
- `make`

---

## Normal workflow

### First run

```bash
make
```

`make` with no arguments defaults to `make start`. On a fresh database this
installs `base` and `trmnl` automatically.

### Daily development

```bash
make watch
```

Edit files under `addons/trmnl/`. The watcher polls the source tree every
two seconds using a SHA-256 hash and upgrades the module automatically when
a change is detected.

### Manual refresh

```bash
make update
```

Use this when a change is not picked up automatically or when you need a
one-shot upgrade outside the watch loop.

### Running tests

```bash
make test
```

Tests run in a fully isolated Docker project (`trmnl-test`) with a fresh
database. The dev database is never touched. The isolated project and its
volumes are removed automatically when the run finishes.

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

## Make targets (reference)

| Target | Description |
|---|---|
| `make` / `make start` | Start the database and Odoo; install or upgrade `trmnl` as needed. |
| `make bootstrap` | Alias for `make start`. |
| `make watch` | Run `make start`, then watch `addons/trmnl/` and upgrade on every change. |
| `make update` | Upgrade the module and restart Odoo. Installs from scratch if the database is missing. |
| `make test` | Run the Odoo test suite for `trmnl` in an isolated environment (see above). |
| `make stop` | Stop Odoo and Postgres without removing containers or data. |
| `make down` | Remove containers and network; keep persistent volumes. |
| `make downv` | Remove containers, network, and volumes — deletes all local database data. |
| `make restart` | Restart only the Odoo container. |
| `make logs` | Stream Odoo logs. |
| `make shell` | Open a shell inside the Odoo container. |

### Overridable variables

Create a `local.mk` file in the repo root to override any of these without
modifying the `Makefile`:

| Variable | Default | Description |
|---|---|---|
| `COMPOSE` | `docker compose` | Compose command — set to `podman compose` on Fedora or when using Podman. |
| `DB_SERVICE` | `db` | Name of the database service in `compose.yaml`. |
| `ODOO_SERVICE` | `odoo` | Name of the Odoo service in `compose.yaml`. |
| `DB_NAME` | `odoo` | PostgreSQL database name used for development. |
| `MODULE` | `trmnl` | Odoo module name passed to install/upgrade/test commands. |

Example `local.mk` for Podman:

```makefile
COMPOSE=podman compose
```

---

## Underlying script

All `make` targets delegate to `scripts/odoo-dev.sh`. You can call it
directly if you need to work outside of `make`:

```
scripts/odoo-dev.sh <action> <compose_cmd> <db_service> <odoo_service> <db_name> <module>
```

| Positional argument | Corresponds to |
|---|---|
| `action` | `start`, `update`, `watch`, or `test` |
| `compose_cmd` | e.g. `docker compose` or `podman compose` |
| `db_service` | Service name of the Postgres container |
| `odoo_service` | Service name of the Odoo container |
| `db_name` | Target PostgreSQL database |
| `module` | Odoo module name |

Example — equivalent to `make update`:

```bash
scripts/odoo-dev.sh update "docker compose" db odoo odoo trmnl
```
