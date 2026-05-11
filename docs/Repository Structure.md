# The Structure of the Repository

This documentation provides an overview of the repository structure and explains the purpose of the most important folders and files.

---

# Overview of the Repository

```text
.
├── addons/
│   └── trmnl/
│       ├── controllers/
│       ├── models/
│       │   └── providers/
│       ├── security/
│       ├── tests/
│       ├── views/
│       ├── __init__.py
│       └── __manifest__.py
├── data/
├── docs/
├── scripts/
├── compose.yaml
├── Dockerfile
├── LICENSE
├── Makefile
├── README.md
└── requirements.txt
```

---

# General Repository Structure

## addons/

The `addons` folder contains all custom Odoo modules of the project.  
In this repository the main module is the `trmnl` module, which implements the communication between Odoo and the TRMNL e-ink displays.

---

## docs/

The `docs` folder contains technical documentation and additional project-related explanations.

---

## scripts/

The `scripts` folder contains helper scripts for development, deployment, automation, or maintenance tasks.

---

## compose.yaml

Defines the Docker Compose setup used to run the application and its services locally or in development environments.

---

## Dockerfile

Contains the instructions required to build the Docker image for the project.

---

## Makefile

Provides shortcuts for common development tasks such as starting containers, running tests, or formatting code.

---

## requirements.txt

Lists all required Python dependencies for the project.

---

# Structure of the TRMNL Module

```text
addons/trmnl/
├── controllers/
├── models/
├── security/
├── tests/
├── views/
├── __init__.py
└── __manifest__.py
```

The `trmnl` module contains the complete implementation for managing TRMNL devices inside Odoo.

---

# Content of the Folders

## controllers/

The `controllers` folder contains all HTTP API endpoints that are used by the TRMNL displays to communicate with Odoo.

The controllers process incoming requests from the devices and return the required responses.

### Main responsibilities

- Device setup and registration
- Display polling
- Log ingestion
- HTTP response handling
- API request validation

### Important files

#### `device_setup_controller.py`

Implements the `/api/setup` endpoint.

Responsible for:

- Registering new TRMNL devices
- Generating API tokens
- Returning the setup response to the device

---

#### `device_display_controller.py`

Implements the `/api/display` endpoint.

Responsible for:

- Handling display polling requests
- Validating devices and tokens
- Returning image URLs and display instructions
- Sending identify or reset commands

---

#### `device_log_controller.py`

Implements the `/api/log` endpoint.

Responsible for:

- Receiving device logs
- Validating authorization
- Storing telemetry and log data

---

#### `trmnl_api_base.py`

Contains shared helper methods used by all controllers.

Responsible for:

- JSON response generation
- Identifier masking for logs
- Shared API utility functions

---

## models/

The `models` folder contains the complete business logic and database models of the module.

This includes:

- Device management
- Security logic
- Device lifecycle handling
- Telemetry processing
- Display response generation
- Odoo backend functionality

---

### Core Model Files

#### `trmnl_device.py`

Core device model of the module.

Defines:

- Device database fields
- Device identity handling
- Refresh rate configuration
- Battery and telemetry fields
- Validation logic
- Helper methods

This file represents the central TRMNL device object inside Odoo.

---

#### `trmnl_device_security.py`

Contains all API token and security-related functionality.

Responsible for:

- Token generation
- PBKDF2 hashing
- Token verification
- Token promotion and adoption
- Secure token storage

---

#### `trmnl_device_lifecycle.py`

Contains device registration and lifecycle logic.

Responsible for:

- Device registration via `/api/setup`
- Unknown device handling
- Token mismatch handling
- Auto-accept logic
- Factory reset policy
- Manual device acceptance

---

#### `trmnl_device_display.py`

Contains logic for handling display requests and generating display responses.

Responsible for:

- Display payload generation
- Display request resolution
- Identify command handling
- Error response handling
- Display policy execution

---

#### `trmnl_device_telemetry.py`

Handles telemetry processing and log ingestion.

Responsible for:

- Parsing telemetry headers
- Updating device telemetry values
- Processing `/api/log` payloads
- Creating log entries
- Updating device activity statistics

---

#### `trmnl_device_log.py`

Defines the database model for stored device log entries.

Responsible for:

- Storing device logs
- Log metadata
- Readable log labels
- Log relationships to devices

---

#### `trmnl_device_ui.py`

Contains Odoo backend UI extensions and actions.

Responsible for:

- Backend-only helper fields
- Device ordering
- Button visibility logic
- Identify actions
- Opening wizards and forms

---

#### `trmnl_device_wizard.py`

Contains transient models for backend confirmation dialogs and management wizards.

Responsible for:

- Accept device wizard
- Remove device wizard
- Reset device wizard
- Display policy wizard

---

## security/

The `security` folder contains access control and permission configuration for Odoo.

### Important files

#### `ir.model.access.csv`

Defines which users and groups are allowed to:

- Read records
- Create records
- Modify records
- Delete records

---

## tests/

The `tests` folder contains automated test cases for the TRMNL module.

The tests verify:

- API behavior
- Device registration
- Display communication
- Log handling
- Refresh rate logic
- Security functionality

---

### Important test files

#### `test_api_setup.py`

Tests the `/api/setup` endpoint.

---

#### `test_api_display.py`

Tests the `/api/display` endpoint and all display policies.

---

#### `test_api_log.py`

Tests the `/api/log` endpoint and log storage.

---

#### `test_device_refresh_rate.py`

Tests refresh rate calculations, validation, and UI conversion logic.

---

#### `test_api_common.py`

Contains shared utilities and helper functions used by all API tests.

---

## views/

The `views` folder contains all XML definitions for the Odoo backend user interface.

This includes:

- Form views
- List views
- Menu entries
- Wizard dialogs
- Action definitions

### Important files

#### `trmnl_device_views.xml`

Defines the main device views inside Odoo.

---

#### `trmnl_device_wizard_views.xml`

Defines the wizard dialog views.

---

#### `trmnl_menu.xml`

Defines the navigation menu entries for the module.

---

# Module Configuration Files

## `__manifest__.py`

Defines the Odoo module configuration.

Contains:

- Module metadata
- Dependencies
- Loaded XML files
- External Python dependencies
- Version information

---

## `__init__.py`

Initializes Python packages and imports submodules so they are loaded by Odoo.

---

# Summary

The repository is structured around a modular Odoo architecture.

The TRMNL module itself is separated into multiple layers:

- `controllers/` → HTTP API endpoints
- `models/` → business logic and database models
- `views/` → Odoo backend interface
- `security/` → access permissions
- `tests/` → automated validation and API testing

This separation improves maintainability, readability, and scalability of the project.