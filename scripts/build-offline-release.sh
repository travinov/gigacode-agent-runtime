#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd "$SCRIPT_DIR/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-"$PROJECT_ROOT/.venv/bin/python"}
SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-1767225600}
PYTHONHASHSEED=${PYTHONHASHSEED:-0}
export SOURCE_DATE_EPOCH PYTHONHASHSEED
cd "$PROJECT_ROOT"
VERSION=$(
  "$PYTHON_BIN" -c \
    'import sys; sys.path.insert(0, "src"); from gigacode_agent_runtime.version import __version__; print(__version__)'
)
RELEASE_NAME="gigacode-agent-runtime-v${VERSION}-macos-x86_64"
WORK_DIR=$(mktemp -d "${TMPDIR:-/private/tmp}/gar-release.XXXXXX")
STAGE_ROOT="$WORK_DIR/$RELEASE_NAME"
BUILD_DIST="$WORK_DIR/project-wheel"
OUTPUT_DIR="$PROJECT_ROOT/dist"

cleanup() {
  /bin/rm -rf "$WORK_DIR"
}
trap cleanup EXIT HUP INT TERM

mkdir -p "$STAGE_ROOT/wheelhouse/common" "$BUILD_DIST" "$OUTPUT_DIR"
"$PYTHON_BIN" -m build --wheel --outdir "$BUILD_DIST" "$PROJECT_ROOT"

PROJECT_WHEEL=$(
  find "$BUILD_DIST" -type f -name "gigacode_agent_runtime-${VERSION}-*.whl" -print
)
if [ -z "$PROJECT_WHEEL" ] || [ "$(printf '%s\n' "$PROJECT_WHEEL" | wc -l | tr -d ' ')" -ne 1 ]; then
  echo "Expected exactly one project wheel" >&2
  exit 1
fi
cp "$PROJECT_WHEEL" "$STAGE_ROOT/wheelhouse/common/"

for MINOR in 311 312 313 314; do
  DOWNLOAD_DIR="$WORK_DIR/download-py$MINOR"
  mkdir -p "$DOWNLOAD_DIR" "$STAGE_ROOT/wheelhouse/py$MINOR"
  "$PYTHON_BIN" -m pip download \
    --require-hashes \
    --only-binary=:all: \
    --platform macosx_10_15_x86_64 \
    --implementation cp \
    --python-version "$MINOR" \
    --abi "cp$MINOR" \
    --dest "$DOWNLOAD_DIR" \
    -r "$PROJECT_ROOT/requirements/runtime-py$MINOR.lock"
  "$PYTHON_BIN" "$SCRIPT_DIR/release_tool.py" split-wheels \
    "$DOWNLOAD_DIR" \
    "$STAGE_ROOT/wheelhouse/common" \
    "$STAGE_ROOT/wheelhouse/py$MINOR"
done

cp -R "$PROJECT_ROOT/installer" "$STAGE_ROOT/installer"
cp -R "$PROJECT_ROOT/examples" "$STAGE_ROOT/examples"
cp -R "$PROJECT_ROOT/docs" "$STAGE_ROOT/docs"
cp -R "$PROJECT_ROOT/optional-skill" "$STAGE_ROOT/optional-skill"
cp -R "$PROJECT_ROOT/requirements" "$STAGE_ROOT/requirements"
mkdir -p "$STAGE_ROOT/scripts"
cp "$SCRIPT_DIR/release_tool.py" "$STAGE_ROOT/scripts/release_tool.py"
cp "$PROJECT_ROOT/README.md" "$PROJECT_ROOT/CHANGELOG.md" \
  "$PROJECT_ROOT/LICENSE" "$STAGE_ROOT/"

find "$STAGE_ROOT" -type f \( -name ".DS_Store" -o -name "*.pyc" \) \
  -exec /bin/rm -f {} \;
find "$STAGE_ROOT/installer" "$STAGE_ROOT/scripts" -type f -name "*.sh" \
  -exec chmod 755 {} \;
chmod 755 "$STAGE_ROOT/scripts/release_tool.py"

"$PYTHON_BIN" "$SCRIPT_DIR/release_tool.py" manifest \
  "$STAGE_ROOT" "$PROJECT_ROOT/release-manifest.json"
"$PYTHON_BIN" "$SCRIPT_DIR/release_tool.py" verify "$STAGE_ROOT"

ARCHIVE="$OUTPUT_DIR/$RELEASE_NAME.zip"
"$PYTHON_BIN" "$SCRIPT_DIR/release_tool.py" package "$STAGE_ROOT" "$ARCHIVE"
CHECKSUM=$("$PYTHON_BIN" "$SCRIPT_DIR/release_tool.py" checksum "$ARCHIVE")
"$SCRIPT_DIR/verify-offline-release.sh" "$ARCHIVE"

printf '%s\n%s\n' "$ARCHIVE" "$CHECKSUM"
