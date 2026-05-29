# Repo-local, override-friendly COMPOSE setup.
# Dev lifecycle targets run docker compose directly (no helper script).

SHELL := /bin/bash
.DEFAULT_GOAL := start

# For optional overrides
-include local.mk

COMPOSE ?= docker compose
DB_SERVICE ?= db
ODOO_SERVICE ?= odoo
DB_NAME ?= odoo
MODULE ?= trmnl
MODULE_DIR := $(CURDIR)/addons/$(MODULE)

.PHONY: start watch bootstrap update test stop down downv restart logs shell

# Shared bootstrap / update / watch logic (from former scripts/odoo-dev.sh).
.ONESHELL:
.SILENT: start update watch
start update watch:
	set -euo pipefail
	ACTION="$@"
	COMPOSE_CMD="$(COMPOSE)"
	DB_SERVICE="$(DB_SERVICE)"
	ODOO_SERVICE="$(ODOO_SERVICE)"
	DB_NAME="$(DB_NAME)"
	MODULE="$(MODULE)"
	MODULE_DIR="$(MODULE_DIR)"

	run_compose() {
		# shellcheck disable=SC2086
		$$COMPOSE_CMD "$$@"
	}

	die() {
		printf 'error: %s\n' "$$*" >&2
		exit 1
	}

	db_query_default() {
		local sql="$$1"
		run_compose exec -T "$$DB_SERVICE" sh -lc \
			"psql -v ON_ERROR_STOP=1 -U \"\$$POSTGRES_USER\" -d \"\$$POSTGRES_DB\" -tAc \"$$sql\"" \
			| tr -d '[:space:]'
	}

	wait_for_db() {
		local timeout_seconds="$${1:-120}"
		local elapsed=0

		until run_compose exec -T "$$DB_SERVICE" sh -lc \
			'pg_isready -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' >/dev/null 2>&1; do
			sleep 2
			elapsed=$$((elapsed + 2))
			if (( elapsed >= timeout_seconds )); then
				die "Timed out waiting for Postgres service '$$DB_SERVICE' to become ready"
			fi
		done
	}

	target_database_exists() {
		[[ "$$(db_query_default "SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$$DB_NAME');")" == "t" ]]
	}

	db_has_odoo_schema() {
		run_compose exec -T "$$DB_SERVICE" sh -lc \
			"psql -v ON_ERROR_STOP=1 -U \"\$$POSTGRES_USER\" -d \"$$DB_NAME\" -tAc \"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'ir_module_module');\"" \
			| tr -d '[:space:]'
	}

	module_state() {
		if ! target_database_exists; then
			printf 'missing\n'
			return 0
		fi

		if [[ "$$(db_has_odoo_schema)" != "t" ]]; then
			printf 'missing\n'
			return 0
		fi

		run_compose exec -T "$$DB_SERVICE" sh -lc \
			"psql -v ON_ERROR_STOP=1 -U \"\$$POSTGRES_USER\" -d \"$$DB_NAME\" -tAc \"SELECT COALESCE((SELECT state FROM ir_module_module WHERE name = '$$MODULE' LIMIT 1), 'uninstalled');\"" \
			| tr -d '[:space:]'
	}

	install_modules() {
		local modules="$$1"
		printf 'Installing %s into database "%s"...\n' "$$modules" "$$DB_NAME"
		run_compose run --rm --no-deps "$$ODOO_SERVICE" odoo --http-interface=0.0.0.0 -d "$$DB_NAME" -i "$$modules" --stop-after-init
	}

	upgrade_module() {
		printf 'Upgrading module "%s" in database "%s"...\n' "$$MODULE" "$$DB_NAME"
		run_compose run --rm --no-deps "$$ODOO_SERVICE" odoo --http-interface=0.0.0.0 -d "$$DB_NAME" -u "$$MODULE" --stop-after-init
	}

	ensure_bootstrapped() {
		run_compose up -d "$$DB_SERVICE"
		wait_for_db

		local state
		state="$$(module_state)"

		case "$$state" in
			missing)
				install_modules "base,$${MODULE}"
				;;
			uninstalled|to\ install)
				install_modules "$$MODULE"
				;;
			to\ upgrade)
				upgrade_module
				;;
			installed)
				printf 'Module "%s" is already installed.\n' "$$MODULE"
				;;
			*)
				printf 'Module "%s" is in state "%s"; upgrading to stay in sync.\n' "$$MODULE" "$$state"
				upgrade_module
				;;
		esac

		run_compose up -d "$$ODOO_SERVICE"
	}

	source_tree_hash() {
		if [[ ! -d "$$MODULE_DIR" ]]; then
			printf 'missing\n'
			return 0
		fi

		find "$$MODULE_DIR" -type f \
			-not -path '*/__pycache__/*' \
			-not -name '*.pyc' \
			-not -name '*.pyo' \
			-not -path '*/.git/*' \
			-print0 \
			| sort -z \
			| xargs -0 -r sha256sum \
			| sha256sum \
			| awk '{print $$1}'
	}

	do_start() {
		ensure_bootstrapped
	}

	do_update() {
		run_compose up -d "$$DB_SERVICE"
		wait_for_db

		local state
		state="$$(module_state)"

		if [[ "$$state" == "missing" || "$$state" == "uninstalled" || "$$state" == "to install" ]]; then
			ensure_bootstrapped
			return 0
		fi

		upgrade_module
		run_compose up -d "$$ODOO_SERVICE"
		run_compose restart "$$ODOO_SERVICE"
	}

	do_watch() {
		do_start

		local previous_hash current_hash
		previous_hash="$$(source_tree_hash)"

		printf 'Watching "%s" for changes. Press Ctrl-C to stop.\n' "$$MODULE_DIR"
		while true; do
			sleep 2
			current_hash="$$(source_tree_hash)"
			if [[ "$$current_hash" != "$$previous_hash" ]]; then
				previous_hash="$$current_hash"
				printf 'Change detected, updating "%s"...\n' "$$MODULE"
				do_update
			fi
		done
	}

	case "$$ACTION" in
		start) do_start ;;
		update) do_update ;;
		watch) do_watch ;;
		*) die "Unknown action '$$ACTION'. Use: start, update, or watch." ;;
	esac

bootstrap: start

test: start
	$(COMPOSE) run --rm $(ODOO_SERVICE) odoo --http-interface=0.0.0.0 -d $(DB_NAME) -u $(MODULE) --stop-after-init --test-enable --test-tags /$(MODULE)

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
