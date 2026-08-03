#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
RELEASE_ROOT=$(CDPATH= cd "$SCRIPT_DIR/.." && pwd)
. "$SCRIPT_DIR/lib/common.sh"

CREATED_VERSION=0
ROLLBACK_REQUIRED=0
PREVIOUS_TARGET=""
ROLLBACK_TARGET=""
GIGACODE=""
VERSION_DIR=""
SEED_ROLLBACK_FILE=""

rollback_failed_install() {
  if [ -n "$SEED_ROLLBACK_FILE" ] && [ -f "$SEED_ROLLBACK_FILE" ]; then
    while IFS= read -r SEEDED_PATH; do
      if [ -n "$SEEDED_PATH" ]; then
        case "$SEEDED_PATH" in
          "$GAR_DATA_DIR"/*) gar_assert_safe_under "$SEEDED_PATH" "$GAR_DATA_DIR" ;;
          "$GAR_AGENTS_DIR"/*) gar_assert_safe_under "$SEEDED_PATH" "$GAR_AGENTS_DIR" ;;
          "$GAR_SKILLS_DIR"/*) gar_assert_safe_under "$SEEDED_PATH" "$GAR_SKILLS_DIR" ;;
          "$GAR_COMMANDS_DIR"/*) gar_assert_safe_under "$SEEDED_PATH" "$GAR_COMMANDS_DIR" ;;
          *) gar_die "seeded path is outside managed roots: $SEEDED_PATH" ;;
        esac
        /bin/rm -f "$SEEDED_PATH"
      fi
    done < "$SEED_ROLLBACK_FILE"
    /bin/rm -f "$SEED_ROLLBACK_FILE"
  fi
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
  if [ "$CREATED_VERSION" -eq 1 ] && [ -n "$VERSION_DIR" ]; then
    gar_remove_tree "$VERSION_DIR" "$GAR_INSTALL_ROOT/versions"
  fi
}

seed_owned_command_if_missing() {
  SOURCE=$1
  TARGET=$2
  MARKER=$3
  if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
    echo "preserved existing GigaCode command: $TARGET"
    return 0
  fi
  seed_file_if_missing "$SOURCE" "$TARGET"
  COMMAND_DIGEST=$(gar_sha256_file "$TARGET")
  TEMP_MARKER="${MARKER}.tmp.$$"
  /bin/rm -f "$TEMP_MARKER"
  printf '%s\n' "$COMMAND_DIGEST" > "$TEMP_MARKER"
  chmod 600 "$TEMP_MARKER"
  /bin/mv -f "$TEMP_MARKER" "$MARKER"
  printf '%s\n' "$MARKER" >> "$SEED_ROLLBACK_FILE"
}

seed_file_if_missing() {
  SOURCE=$1
  TARGET=$2
  [ -f "$SOURCE" ] || gar_die "corporate profile file is missing: $SOURCE"
  if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
    echo "preserved existing profile file: $TARGET"
    return 0
  fi
  TEMP_TARGET="${TARGET}.tmp.$$"
  /bin/rm -f "$TEMP_TARGET"
  /bin/cp "$SOURCE" "$TEMP_TARGET"
  chmod 600 "$TEMP_TARGET"
  /bin/mv -f "$TEMP_TARGET" "$TARGET"
  printf '%s\n' "$TARGET" >> "$SEED_ROLLBACK_FILE"
  echo "installed corporate profile file: $TARGET"
}

seed_corporate_profile() {
  PROFILE_ROOT="$RELEASE_ROOT/corporate-profile"
  [ -d "$PROFILE_ROOT/scenarios" ] || \
    gar_die "corporate scenario profile is missing"
  SEED_ROLLBACK_FILE="$GAR_DATA_DIR/.install-seeded.$$"
  : > "$SEED_ROLLBACK_FILE"
  seed_file_if_missing \
    "$PROFILE_ROOT/config.yaml" \
    "$GAR_DATA_DIR/config.yaml"
  SCENARIO_COUNT=0
  for SOURCE_SCENARIO in "$PROFILE_ROOT/scenarios/"*.yaml; do
    [ -f "$SOURCE_SCENARIO" ] || continue
    SCENARIO_COUNT=$((SCENARIO_COUNT + 1))
    seed_file_if_missing \
      "$SOURCE_SCENARIO" \
      "$GAR_DATA_DIR/scenarios/$(basename "$SOURCE_SCENARIO")"
  done
  [ "$SCENARIO_COUNT" -gt 0 ] || gar_die "corporate scenario profile is empty"
  AGENT_COUNT=0
  for SOURCE_AGENT in "$PROFILE_ROOT/agents/"*.md; do
    [ -f "$SOURCE_AGENT" ] || continue
    AGENT_COUNT=$((AGENT_COUNT + 1))
    seed_file_if_missing \
      "$SOURCE_AGENT" \
      "$GAR_AGENTS_DIR/$(basename "$SOURCE_AGENT")"
  done
  [ "$AGENT_COUNT" -gt 0 ] || gar_die "corporate agent profile is empty"
  SKILL_COUNT=0
  for SOURCE_SKILL_DIR in "$PROFILE_ROOT/skills/"*; do
    [ -d "$SOURCE_SKILL_DIR" ] || continue
    SOURCE_SKILL="$SOURCE_SKILL_DIR/SKILL.md"
    [ -f "$SOURCE_SKILL" ] || gar_die "corporate Skill is missing SKILL.md"
    SKILL_COUNT=$((SKILL_COUNT + 1))
    TARGET_SKILL_DIR="$GAR_SKILLS_DIR/$(basename "$SOURCE_SKILL_DIR")"
    [ ! -L "$TARGET_SKILL_DIR" ] || gar_die "refusing symlinked Skill directory"
    mkdir -p "$TARGET_SKILL_DIR"
    seed_file_if_missing "$SOURCE_SKILL" "$TARGET_SKILL_DIR/SKILL.md"
  done
  [ "$SKILL_COUNT" -gt 0 ] || gar_die "corporate Skill profile is empty"
  OPTIONAL_SIMPLE_SCENARIO="$PROFILE_ROOT/optional-scenarios/corporate-simple-skills.yaml"
  [ -f "$OPTIONAL_SIMPLE_SCENARIO" ] || \
    gar_die "optional simple Skills scenario is missing"
  if "$VERSION_ENTRYPOINT" skills describe doc-review --json >/dev/null 2>&1 && \
    "$VERSION_ENTRYPOINT" skills describe secure-coding --json >/dev/null 2>&1
  then
    seed_file_if_missing \
      "$OPTIONAL_SIMPLE_SCENARIO" \
      "$GAR_DATA_DIR/scenarios/corporate-simple-skills.yaml"
  else
    echo "skipped corporate-simple-skills: doc-review and secure-coding are required"
  fi
  seed_owned_command_if_missing \
    "$PROFILE_ROOT/commands/open_studio.md" \
    "$GAR_STUDIO_COMMAND" \
    "$GAR_STUDIO_COMMAND_MARKER"
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

PROJECT_WHEEL=$(
  find "$RELEASE_ROOT/wheelhouse/common" -type f \
    -name "gigacode_agent_runtime-$GAR_VERSION-*.whl" -print
)
if [ -z "$PROJECT_WHEEL" ] || \
  [ "$(printf '%s\n' "$PROJECT_WHEEL" | wc -l | tr -d ' ')" -ne 1 ]; then
  gar_die "expected exactly one project wheel"
fi
PROJECT_DIGEST=$(
  "$PYTHON" -c \
    'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' \
    "$PROJECT_WHEEL"
)

mkdir -p "$GAR_INSTALL_ROOT/versions" "$GAR_BIN_DIR" \
  "$GAR_DATA_DIR/scenarios" "$GAR_DATA_DIR/runs" "$GAR_AGENTS_DIR" \
  "$GAR_SKILLS_DIR"
mkdir -p "$GAR_COMMANDS_DIR"
VERSION_TARGET="versions/$GAR_VERSION-$PROJECT_DIGEST"
VERSION_DIR="$GAR_INSTALL_ROOT/$VERSION_TARGET"
PREVIOUS_TARGET=$(gar_read_current)
ROLLBACK_TARGET=$PREVIOUS_TARGET
if [ "$PREVIOUS_TARGET" = "$VERSION_TARGET" ] && [ -f "$GAR_PREVIOUS_FILE" ]; then
  ROLLBACK_TARGET=$(sed -n '1p' "$GAR_PREVIOUS_FILE")
fi

VERSION_ENTRYPOINT="$VERSION_DIR/venv/bin/agent-runtime"
if [ -x "$VERSION_ENTRYPOINT" ] && \
  "$VERSION_ENTRYPOINT" --version >/dev/null 2>&1; then
  :
else
  if [ -e "$VERSION_DIR" ] || [ -L "$VERSION_DIR" ]; then
    gar_remove_tree "$VERSION_DIR" "$GAR_INSTALL_ROOT/versions"
  fi
  mkdir -p "$VERSION_DIR"
  CREATED_VERSION=1
  "$PYTHON" -m venv "$VERSION_DIR/venv"
  gar_fail_after venv

  "$VERSION_DIR/venv/bin/python" -m pip install \
    --no-index \
    --require-hashes \
    --find-links "$RELEASE_ROOT/wheelhouse/common" \
    --find-links "$RELEASE_ROOT/wheelhouse/py$PY_MINOR" \
    -r "$RELEASE_ROOT/requirements/runtime-py$PY_MINOR.lock"

  "$VERSION_DIR/venv/bin/python" -m pip install \
    --no-index --no-deps "$PROJECT_WHEEL"
  "$VERSION_ENTRYPOINT" --version
  gar_fail_after install
fi

ROLLBACK_REQUIRED=1
gar_switch_current "$VERSION_TARGET"
gar_install_launcher
gar_fail_after activate

seed_corporate_profile
gar_fail_after seed

"$VERSION_DIR/venv/bin/agent-runtime" diagnose --json >/dev/null
gar_register_mcp "$GIGACODE"
gar_fail_after register
gar_verify_mcp "$GIGACODE"
gar_fail_after verify

if [ -n "$ROLLBACK_TARGET" ] && [ "$ROLLBACK_TARGET" != "$VERSION_TARGET" ]; then
  printf '%s\n' "$ROLLBACK_TARGET" > "$GAR_PREVIOUS_FILE"
fi
ROLLBACK_REQUIRED=0
/bin/rm -f "$SEED_ROLLBACK_FILE"
SEED_ROLLBACK_FILE=""
trap - EXIT HUP INT TERM

echo "installed GigaCode Agent Runtime $GAR_VERSION"
echo "launcher: $GAR_LAUNCHER"
echo "data: $GAR_DATA_DIR"
