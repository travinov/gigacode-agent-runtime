#!/bin/sh

GAR_MCP_NAME="gigacode-agent-runtime"
GAR_VERSION="1.0.0"
GAR_INSTALL_ROOT=${GIGACODE_AGENT_RUNTIME_INSTALL_ROOT:-"$HOME/.local/share/gigacode-agent-runtime"}
GAR_BIN_DIR=${GIGACODE_AGENT_RUNTIME_BIN_DIR:-"$HOME/.local/bin"}
GAR_DATA_DIR=${GIGACODE_AGENT_RUNTIME_DATA_DIR:-"$HOME/.gigacode/agent-runtime"}
GAR_AGENTS_DIR=${GIGACODE_AGENT_RUNTIME_AGENTS_DIR:-"$HOME/.gigacode/agents"}
GAR_CURRENT_LINK="$GAR_INSTALL_ROOT/current"
GAR_PREVIOUS_FILE="$GAR_INSTALL_ROOT/previous-target"
GAR_LAUNCHER="$GAR_BIN_DIR/agent-runtime"

gar_die() {
  echo "error: $*" >&2
  exit 1
}

gar_require_command() {
  command -v "$1" >/dev/null 2>&1 || gar_die "required command not found: $1"
}

gar_assert_platform() {
  SYSTEM=${GAR_TEST_SYSTEM:-$(uname -s)}
  MACHINE=${GAR_TEST_MACHINE:-$(uname -m)}
  [ "$SYSTEM" = "Darwin" ] || gar_die "v1 supports Darwin only, got $SYSTEM"
  [ "$MACHINE" = "x86_64" ] || gar_die "v1 supports x86_64 only, got $MACHINE"
}

gar_python_minor() {
  "$1" -c \
    'import sys; print(f"{sys.version_info.major}{sys.version_info.minor}" if (3,11) <= sys.version_info[:2] < (3,15) else "")'
}

gar_find_python() {
  if [ -n "${GAR_PYTHON:-}" ]; then
    if command -v "$GAR_PYTHON" >/dev/null 2>&1; then
      RESOLVED=$(command -v "$GAR_PYTHON")
    elif [ -x "$GAR_PYTHON" ]; then
      RESOLVED=$GAR_PYTHON
    else
      gar_die "GAR_PYTHON is not executable"
    fi
    MINOR=$(gar_python_minor "$RESOLVED")
    [ -n "$MINOR" ] || gar_die "GAR_PYTHON must be Python 3.11-3.14"
    printf '%s\n' "$RESOLVED"
    return 0
  fi
  for CANDIDATE in python3.14 python3.13 python3.12 python3.11 python3; do
    if command -v "$CANDIDATE" >/dev/null 2>&1; then
      MINOR=$(gar_python_minor "$CANDIDATE")
      if [ -n "$MINOR" ]; then
        command -v "$CANDIDATE"
        return 0
      fi
    elif [ -x "$CANDIDATE" ]; then
      MINOR=$(gar_python_minor "$CANDIDATE")
      if [ -n "$MINOR" ]; then
        printf '%s\n' "$CANDIDATE"
        return 0
      fi
    fi
  done
  gar_die "Python 3.11-3.14 was not found"
}

gar_find_gigacode() {
  if [ -n "${GIGACODE_BIN:-}" ]; then
    [ -x "$GIGACODE_BIN" ] || gar_die "GIGACODE_BIN is not executable"
    printf '%s\n' "$GIGACODE_BIN"
    return 0
  fi
  command -v gigacode 2>/dev/null || gar_die "GigaCode CLI was not found"
}

gar_assert_safe_under() {
  TARGET=$1
  PARENT=$2
  [ -n "$TARGET" ] || gar_die "empty destructive target"
  [ "$TARGET" != "/" ] || gar_die "refusing to modify filesystem root"
  [ "$TARGET" != "$HOME" ] || gar_die "refusing to modify HOME"
  case "$TARGET" in
    "$PARENT"/*) ;;
    *) gar_die "target is outside the allowed root: $TARGET" ;;
  esac
}

gar_remove_tree() {
  TARGET=$1
  PARENT=$2
  gar_assert_safe_under "$TARGET" "$PARENT"
  if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
    /bin/rm -rf "$TARGET"
  fi
}

gar_read_current() {
  if [ -L "$GAR_CURRENT_LINK" ]; then
    readlink "$GAR_CURRENT_LINK"
  fi
}

gar_switch_current() {
  TARGET=$1
  case "$TARGET" in
    versions/*) ;;
    *) gar_die "invalid current target: $TARGET" ;;
  esac
  [ -d "$GAR_INSTALL_ROOT/$TARGET" ] || gar_die "version target is missing: $TARGET"
  TEMP_LINK="$GAR_INSTALL_ROOT/.current.$$"
  /bin/rm -f "$TEMP_LINK"
  ln -s "$TARGET" "$TEMP_LINK"
  /bin/mv -h -f "$TEMP_LINK" "$GAR_CURRENT_LINK"
}

gar_install_launcher() {
  mkdir -p "$GAR_BIN_DIR"
  TEMP_LAUNCHER="$GAR_BIN_DIR/.agent-runtime.$$"
  /bin/rm -f "$TEMP_LAUNCHER"
  ln -s "$GAR_CURRENT_LINK/venv/bin/agent-runtime" "$TEMP_LAUNCHER"
  /bin/mv -h -f "$TEMP_LAUNCHER" "$GAR_LAUNCHER"
}

gar_unregister_mcp() {
  GIGACODE=$1
  "$GIGACODE" mcp remove --scope user "$GAR_MCP_NAME" >/dev/null 2>&1 || true
}

gar_register_mcp() {
  GIGACODE=$1
  gar_unregister_mcp "$GIGACODE"
  "$GIGACODE" mcp add --scope user --transport stdio \
    "$GAR_MCP_NAME" "$GAR_LAUNCHER" mcp-serve
}

gar_verify_mcp() {
  GIGACODE=$1
  "$GIGACODE" mcp list | grep "$GAR_MCP_NAME" >/dev/null
}

gar_fail_after() {
  STAGE=$1
  if [ "${GAR_FAIL_AFTER:-}" = "$STAGE" ]; then
    gar_die "injected failure after stage: $STAGE"
  fi
}
