#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
RELEASE_ROOT=$(CDPATH= cd "$SCRIPT_DIR/.." && pwd)
. "$SCRIPT_DIR/lib/common.sh"

TEMP_VERSION=""
CREATED_VERSION=0
ROLLBACK_REQUIRED=0
PREVIOUS_TARGET=""
ROLLBACK_TARGET=""
GIGACODE=""

rollback_failed_install() {
  if [ "$ROLLBACK_REQUIRED" -eq 1 ]; then
    if [ -n "$ROLLBACK_TARGET" ]; then
      gar_switch_current "$ROLLBACK_TARGET" || true
      gar_install_launcher || true
      if [ -n "$GIGACODE" ]; then
        gar_register_mcp "$GIGACODE" >/dev/null 2>&1 || true
      fi
    else
      /bin/rm -f "$GAR_CURRENT_LINK" "$GAR_LAUNCHER"
      if [ -n "$GIGACODE" ]; then
        gar_unregister_mcp "$GIGACODE"
      fi
    fi
  fi
  if [ -n "$TEMP_VERSION" ] && [ -d "$TEMP_VERSION" ]; then
    gar_remove_tree "$TEMP_VERSION" "$GAR_INSTALL_ROOT/versions"
  fi
  if [ "$CREATED_VERSION" -eq 1 ]; then
    gar_remove_tree "$GAR_INSTALL_ROOT/versions/$GAR_VERSION" "$GAR_INSTALL_ROOT/versions"
  fi
}

on_exit() {
  STATUS=$?
  trap - EXIT HUP INT TERM
  if [ "$STATUS" -ne 0 ]; then
    rollback_failed_install
  fi
  exit "$STATUS"
}
trap on_exit EXIT
trap 'exit 130' HUP INT TERM

gar_assert_platform
PYTHON=$(gar_find_python)
PY_MINOR=$(gar_python_minor "$PYTHON")
GIGACODE=$(gar_find_gigacode)
"$PYTHON" "$RELEASE_ROOT/scripts/release_tool.py" verify "$RELEASE_ROOT"
gar_fail_after preflight

mkdir -p "$GAR_INSTALL_ROOT/versions" "$GAR_BIN_DIR" \
  "$GAR_DATA_DIR/scenarios" "$GAR_DATA_DIR/runs"
TARGET="versions/$GAR_VERSION"
VERSION_DIR="$GAR_INSTALL_ROOT/$TARGET"
PREVIOUS_TARGET=$(gar_read_current)
ROLLBACK_TARGET=$PREVIOUS_TARGET
if [ "$PREVIOUS_TARGET" = "$TARGET" ] && [ -f "$GAR_PREVIOUS_FILE" ]; then
  ROLLBACK_TARGET=$(sed -n '1p' "$GAR_PREVIOUS_FILE")
fi

if [ ! -x "$VERSION_DIR/venv/bin/agent-runtime" ]; then
  TEMP_VERSION=$(mktemp -d "$GAR_INSTALL_ROOT/versions/.install-$GAR_VERSION.XXXXXX")
  "$PYTHON" -m venv "$TEMP_VERSION/venv"
  gar_fail_after venv

  "$TEMP_VERSION/venv/bin/python" -m pip install \
    --no-index \
    --require-hashes \
    --find-links "$RELEASE_ROOT/wheelhouse/common" \
    --find-links "$RELEASE_ROOT/wheelhouse/py$PY_MINOR" \
    -r "$RELEASE_ROOT/requirements/runtime-py$PY_MINOR.lock"

  PROJECT_WHEEL=$(
    find "$RELEASE_ROOT/wheelhouse/common" -type f \
      -name "gigacode_agent_runtime-$GAR_VERSION-*.whl" -print
  )
  if [ -z "$PROJECT_WHEEL" ] || \
    [ "$(printf '%s\n' "$PROJECT_WHEEL" | wc -l | tr -d ' ')" -ne 1 ]; then
    gar_die "expected exactly one project wheel"
  fi
  "$TEMP_VERSION/venv/bin/python" -m pip install \
    --no-index --no-deps "$PROJECT_WHEEL"
  "$TEMP_VERSION/venv/bin/agent-runtime" --version
  gar_fail_after install

  mv "$TEMP_VERSION" "$VERSION_DIR"
  TEMP_VERSION=""
  CREATED_VERSION=1
fi

ROLLBACK_REQUIRED=1
gar_switch_current "$TARGET"
gar_install_launcher
gar_fail_after activate

"$VERSION_DIR/venv/bin/agent-runtime" diagnose --json >/dev/null
gar_register_mcp "$GIGACODE"
gar_fail_after register
gar_verify_mcp "$GIGACODE"
gar_fail_after verify

if [ -n "$ROLLBACK_TARGET" ] && [ "$ROLLBACK_TARGET" != "$TARGET" ]; then
  printf '%s\n' "$ROLLBACK_TARGET" > "$GAR_PREVIOUS_FILE"
fi
ROLLBACK_REQUIRED=0
trap - EXIT HUP INT TERM

echo "installed GigaCode Agent Runtime $GAR_VERSION"
echo "launcher: $GAR_LAUNCHER"
echo "data: $GAR_DATA_DIR"
