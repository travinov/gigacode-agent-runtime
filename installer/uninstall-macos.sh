#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/lib/common.sh"

PURGE=0
if [ "$#" -gt 1 ]; then
  gar_die "usage: uninstall-macos.sh [--purge-data]"
fi
if [ "$#" -eq 1 ]; then
  [ "$1" = "--purge-data" ] || gar_die "unknown option: $1"
  PURGE=1
fi

if GIGACODE=$(gar_find_gigacode 2>/dev/null); then
  gar_unregister_mcp "$GIGACODE"
fi

if [ -L "$GAR_LAUNCHER" ]; then
  LAUNCHER_TARGET=$(readlink "$GAR_LAUNCHER")
  case "$LAUNCHER_TARGET" in
    "$GAR_INSTALL_ROOT"/*) /bin/rm -f "$GAR_LAUNCHER" ;;
    *) gar_die "launcher does not belong to this installation" ;;
  esac
fi
if [ -e "$GAR_INSTALL_ROOT" ] || [ -L "$GAR_INSTALL_ROOT" ]; then
  gar_remove_tree "$GAR_INSTALL_ROOT" "$(dirname "$GAR_INSTALL_ROOT")"
fi

if [ "$PURGE" -eq 1 ]; then
  [ ! -L "$GAR_DATA_DIR" ] || gar_die "refusing to purge a symlinked data directory"
  gar_assert_safe_under "$GAR_DATA_DIR" "$HOME"
  [ "$(basename "$GAR_DATA_DIR")" = "agent-runtime" ] || \
    gar_die "data directory must end with agent-runtime"
  if [ "${GAR_CONFIRM_PURGE:-}" != "PURGE" ]; then
    printf 'Type PURGE to delete %s: ' "$GAR_DATA_DIR"
    read -r ANSWER
    [ "$ANSWER" = "PURGE" ] || gar_die "data purge was not confirmed"
  fi
  gar_remove_tree "$GAR_DATA_DIR" "$HOME"
  echo "runtime data purged: $GAR_DATA_DIR"
else
  echo "runtime data preserved: $GAR_DATA_DIR"
fi
echo "GigaCode Agent Runtime uninstalled"
