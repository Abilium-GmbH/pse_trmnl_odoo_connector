#!/usr/bin/env bash

# Local helper that makes the environment behave like a dev loop.
# It waits for Postgres readiness;
# detects whether the Odoo database already exists;
# installs "base" plus "trmnl" on a fresh database;
# upgrades the module when needed
# and can keep watching the module tree for changes.

set -euo pipefail

ACTION="${1:-start}"
COMPOSE_CMD="${2:?Missing compose command, e.g. 'podman compose' or 'docker compose'}"
DB_SERVICE="${3:-db}"
ODOO_SERVICE="${4:-odoo}"
DB_NAME="${5:-odoo}"
MODULE="${6:-trmnl}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODULE_DIR="${ROOT_DIR}/addons/${MODULE}"

die() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

run_compose() {
  # shellcheck disable=SC2086
  $COMPOSE_CMD "$@"
}

db_query_default() {
  local sql="$1"
  run_compose exec -T "$DB_SERVICE" sh -lc \
    "psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -tAc \"$sql\"" \
    | tr -d '[:space:]'
}

wait_for_db() {
  local timeout_seconds="${1:-120}"
  local elapsed=0

  until run_compose exec -T "$DB_SERVICE" sh -lc \
    'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; do
    sleep 2
    elapsed=$((elapsed + 2))
    if (( elapsed >= timeout_seconds )); then
      die "Timed out waiting for Postgres service '${DB_SERVICE}' to become ready"
    fi
  done
}

target_database_exists() {
  [[ "$(db_query_default "SELECT EXISTS (SELECT 1 FROM pg_database WHERE datname = '$DB_NAME');")" == "t" ]]
}

db_has_odoo_schema() {
  run_compose exec -T "$DB_SERVICE" sh -lc \
    "psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d \"$DB_NAME\" -tAc \"SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'ir_module_module');\"" \
    | tr -d '[:space:]'
}

module_state() {
  if ! target_database_exists; then
    printf 'missing\n'
    return 0
  fi

  if [[ "$(db_has_odoo_schema)" != "t" ]]; then
    printf 'missing\n'
    return 0
  fi

  run_compose exec -T "$DB_SERVICE" sh -lc \
    "psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d \"$DB_NAME\" -tAc \"SELECT COALESCE((SELECT state FROM ir_module_module WHERE name = '$MODULE' LIMIT 1), 'uninstalled');\"" \
    | tr -d '[:space:]'
}

install_modules() {
  local modules="$1"
  printf 'Installing %s into database "%s"...\n' "$modules" "$DB_NAME"
  run_compose run --rm --no-deps "$ODOO_SERVICE" odoo --http-interface=0.0.0.0 -d "$DB_NAME" -i "$modules" --stop-after-init
}

upgrade_module() {
  printf 'Upgrading module "%s" in database "%s"...\n' "$MODULE" "$DB_NAME"
  run_compose run --rm --no-deps "$ODOO_SERVICE" odoo --http-interface=0.0.0.0 -d "$DB_NAME" -u "$MODULE" --stop-after-init
}

ensure_bootstrapped() {
  run_compose up -d "$DB_SERVICE"
  wait_for_db

  local state
  state="$(module_state)"

  case "$state" in
    missing)
      install_modules "base,${MODULE}"
      ;;
    uninstalled|to\ install)
      install_modules "$MODULE"
      ;;
    to\ upgrade)
      upgrade_module
      ;;
    installed)
      printf 'Module "%s" is already installed.\n' "$MODULE"
      ;;
    *)
      printf 'Module "%s" is in state "%s"; upgrading to stay in sync.\n' "$MODULE" "$state"
      upgrade_module
      ;;
  esac

  run_compose up -d "$ODOO_SERVICE"
}

source_tree_hash() {
  if [[ ! -d "$MODULE_DIR" ]]; then
    printf 'missing\n'
    return 0
  fi

  find "$MODULE_DIR" -type f \
    -not -path '*/__pycache__/*' \
    -not -name '*.pyc' \
    -not -name '*.pyo' \
    -not -path '*/.git/*' \
    -print0 \
    | sort -z \
    | xargs -0 -r sha256sum \
    | sha256sum \
    | awk '{print $1}'
}

do_start() {
  ensure_bootstrapped
}

do_update() {
  run_compose up -d "$DB_SERVICE"
  wait_for_db

  local state
  state="$(module_state)"

  if [[ "$state" == "missing" || "$state" == "uninstalled" || "$state" == "to install" ]]; then
    ensure_bootstrapped
    return 0
  fi

  upgrade_module
  run_compose up -d "$ODOO_SERVICE"
  run_compose restart "$ODOO_SERVICE"
}

do_watch() {
  do_start

  local previous_hash current_hash
  previous_hash="$(source_tree_hash)"

  printf 'Watching "%s" for changes. Press Ctrl-C to stop.\n' "$MODULE_DIR"
  while true; do
    sleep 2
    current_hash="$(source_tree_hash)"
    if [[ "$current_hash" != "$previous_hash" ]]; then
      previous_hash="$current_hash"
      printf 'Change detected, updating "%s"...\n' "$MODULE"
      do_update
    fi
  done
}

do_test() {
  local test_project="trmnl-test"
  local test_db="odoo_test"

  run_compose --project-name "$test_project" up -d "$DB_SERVICE"

  # wait_for_db targets the default project; inline the wait here against the test project.
  local timeout_seconds=120
  local elapsed=0
  until run_compose --project-name "$test_project" exec -T "$DB_SERVICE" sh -lc \
    'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; do
    sleep 2
    elapsed=$((elapsed + 2))
    if (( elapsed >= timeout_seconds )); then
      run_compose --project-name "$test_project" down -v >/dev/null 2>&1
      die "Timed out waiting for test Postgres to become ready"
    fi
  done

  run_compose --project-name "$test_project" run --rm --no-deps "$ODOO_SERVICE" \
    odoo --http-interface=0.0.0.0 -d "$test_db" -i "base,$MODULE" --stop-after-init >/dev/null 2>&1

  local test_exit_code=0
  run_compose --project-name "$test_project" run --rm --no-deps "$ODOO_SERVICE" \
    odoo --http-interface=0.0.0.0 -d "$test_db" -u "$MODULE" --stop-after-init --test-enable --test-tags "/$MODULE" \
    || test_exit_code=$?

  run_compose --project-name "$test_project" down -v >/dev/null 2>&1

  return "$test_exit_code"
}

case "$ACTION" in
  start) do_start ;;
  update) do_update ;;
  watch) do_watch ;;
  test) do_test ;;
  *)
    die "Unknown action '${ACTION}'. Use: start, update, watch, or test."
    ;;
esac
