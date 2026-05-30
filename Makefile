# Repo-local, override-friendly COMPOSE setup.
# Routes lifecycle actions through one helper script.
# It also makes test bootstrap the environment first, so tests are less fragile on a clean volume.

SHELL := /usr/bin/env bash
.DEFAULT_GOAL := start

# For optional overrides
-include local.mk

COMPOSE ?= docker compose
DB_SERVICE ?= db
ODOO_SERVICE ?= odoo
DB_NAME ?= odoo
MODULE ?= trmnl
DEV_SCRIPT := ./scripts/odoo-dev.sh

.PHONY: start watch bootstrap update test stop down downv restart logs shell

start:
	$(DEV_SCRIPT) start "$(COMPOSE)" "$(DB_SERVICE)" "$(ODOO_SERVICE)" "$(DB_NAME)" "$(MODULE)"

bootstrap: start

watch:
	$(DEV_SCRIPT) watch "$(COMPOSE)" "$(DB_SERVICE)" "$(ODOO_SERVICE)" "$(DB_NAME)" "$(MODULE)"

update:
	$(DEV_SCRIPT) update "$(COMPOSE)" "$(DB_SERVICE)" "$(ODOO_SERVICE)" "$(DB_NAME)" "$(MODULE)"

test:
	$(DEV_SCRIPT) test "$(COMPOSE)" "$(DB_SERVICE)" "$(ODOO_SERVICE)" "$(DB_NAME)" "$(MODULE)"

stop:
	$(COMPOSE) stop $(ODOO_SERVICE) $(DB_SERVICE)

down:
	$(COMPOSE) down

downv:
	$(COMPOSE) down -v

restart:
	$(COMPOSE) restart $(ODOO_SERVICE)

logs:
	$(COMPOSE) logs -f $(ODOO_SERVICE)

shell:
	$(COMPOSE) exec $(ODOO_SERVICE) sh
