#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/lib/common.sh"

[ -f "$GAR_PREVIOUS_FILE" ] || gar_die "no previous version is recorded"
PREVIOUS_TARGET=$(sed -n '1p' "$GAR_PREVIOUS_FILE")
case "$PREVIOUS_TARGET" in
  versions/*) ;;
  *) gar_die "recorded rollback target is invalid" ;;
esac
[ -x "$GAR_INSTALL_ROOT/$PREVIOUS_TARGET/venv/bin/agent-runtime" ] || \
  gar_die "recorded previous version is unavailable"

CURRENT_TARGET=$(gar_read_current)
GIGACODE=$(gar_find_gigacode)
gar_switch_current "$PREVIOUS_TARGET"
gar_install_launcher
if ! gar_register_mcp "$GIGACODE" || ! gar_verify_mcp "$GIGACODE"; then
  if [ -n "$CURRENT_TARGET" ]; then
    gar_switch_current "$CURRENT_TARGET"
    gar_install_launcher
    gar_register_mcp "$GIGACODE" >/dev/null 2>&1 || true
  fi
  gar_die "rollback registration verification failed"
fi

if [ -n "$CURRENT_TARGET" ] && [ "$CURRENT_TARGET" != "$PREVIOUS_TARGET" ]; then
  printf '%s\n' "$CURRENT_TARGET" > "$GAR_PREVIOUS_FILE"
fi
echo "rolled back to $PREVIOUS_TARGET"
