# Digital Signage Display System with TRMNL e-Ink Displays

![](docs/assets/videos/trmnl_display.gif)

## Project description

The **TRMNL** Odoo module is an IoT extension for the open source ERP system Odoo that enables the management of TRMNL e-Ink displays. The goal of the project is to show live Odoo data (for example calendar events, tasks, sales orders, or product information) on energy-efficient displays without relying on the TRMNL cloud.

The module acts as a self-hosted API server for TRMNL hardware. Devices pair directly with your Odoo instance, poll for display content over HTTP, and receive dynamically rendered 1-bit PNG images. Administrators manage devices, configure display profiles, and control access policy from the standard Odoo backend.

This module was developed as part of the Software Engineering Lab at the University of Bern, in cooperation with Abilium GmbH. It is **not** affiliated with TRMNL Holdings LLC.

## Features

- **Device management:** Register, monitor, and control TRMNL displays from **TRMNL → Devices** in Odoo
- **Display profiles:** Render Odoo records as list, kanban, calendar, or graph layouts on e-Ink screens
- **Self-hosted integration:** Implements the TRMNL device protocol (`/api/setup`, `/api/display`, `/api/log`) inside Odoo
- **E-Ink display support:** Serves optimized 1-bit PNG images in an energy-saving way
- **HTTP polling:** Transfers display updates reliably between Odoo and TRMNL devices over Wi-Fi
- **Display policy:** Control how unknown or mismatched devices are handled (error, auto-accept, or factory reset)
- **Status updates:** Automatically refreshes displays when source data changes or on a configurable render interval

## Technical requirements

### Server requirements

- Odoo v19.0
- Python 3 with Pillow (see `requirements.txt`)
- PostgreSQL
- Network connection so TRMNL devices can reach your Odoo server (LAN IP, public URL, or Odoo.sh)

### Display hardware

- TRMNL e-Ink display (firmware v1.8.2 or compatible)
- Wi-Fi connection
- Stable power supply

### Development (optional)

- Docker and Docker Compose (or Podman Compose)
- `make`

## Getting started

### Quick start with Docker

1. Clone the repository:

   ```bash
   git clone https://github.com/Abilium-GmbH/pse_trmnl_odoo_connector.git
   cd pse_trmnl_odoo_connector
   ```

2. Start Odoo and install the module:

   ```bash
   make
   ```

   On a fresh database this starts PostgreSQL and Odoo, then installs `base` and `trmnl` automatically.

3. Open Odoo in your browser:

   ```
   http://localhost:8069
   ```

   Default login: email `admin`, password `admin`.

4. If the module is not installed yet, go to **Apps**, remove the **Apps** filter, search for **TRMNL**, and install it.

### Manual Docker setup

If you prefer raw Docker Compose commands, run them from the repository root (where `compose.yaml` lives):

```bash
docker compose up -d db
docker compose run --rm odoo odoo -d odoo -i base --stop-after-init
docker compose up -d odoo
```

After the first setup, start the stack with:

```bash
docker compose up -d
```

Stop it with:

```bash
docker compose down
```

### Connect a TRMNL display

Pair your device with Odoo using the **Custom Server** flow on the TRMNL configuration page. For local or Docker setups, point the device at your machine's LAN address (for example `http://192.168.1.50:8069`), not `localhost`.

Step-by-step pairing, profile setup, and troubleshooting are covered in the [user manual](docs/user_manual.md).

### Environment variables

`compose.yaml` reads from a `.env` file. If none exists, defaults from `compose.yaml` are used. Copy `.env.example` to `.env` and adjust values as needed:

```bash
cp .env.example .env
```

On some Linux distributions (for example Fedora), Podman is recommended instead of Docker. See the [development guide](docs/development.md) for `local.mk` overrides.

## Documentation

For detailed guidance on installing and using this module, refer to the [user manual](docs/user_manual.md).

Additional documentation:

- [Design documentation](docs/design_documentation.md): architecture, HTTP API, security model, and data model
- [Development guide](docs/development.md): local workflow, Make targets, and running tests
- [Repository structure](docs/Repository%20Structure.md): folder layout and module organization

## Development and customization

The module can be extended to implement additional functions:

- New profile view types or renderers for other Odoo models
- Custom display policies or onboarding workflows
- Integration with additional TRMNL firmware features
- Support for other e-Ink display form factors

Contributors should start with `make watch` for live module reloads and `make test` for the isolated test suite. See the [development guide](docs/development.md) for details.

## Development Team

- Timur Umut Turgul - Key Account Manager (client contact)
- Sascha Friedli - Chief Deliverable Officer (deliverables and scheduling)
- Leila Ayinkamiye - Quality Evangelist (test concept and testing)
- Claudio Berger - Master Tracker (status reports and tracking)
