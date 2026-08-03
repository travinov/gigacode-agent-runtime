#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: verify-offline-release.sh RELEASE.zip" >&2
  exit 2
fi

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd "$SCRIPT_DIR/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-"$PROJECT_ROOT/.venv/bin/python"}
ARCHIVE=$1
CHECKSUM_FILE="${ARCHIVE}.sha256"

if [ ! -f "$ARCHIVE" ] || [ ! -f "$CHECKSUM_FILE" ]; then
  echo "release ZIP or checksum is missing" >&2
  exit 1
fi

EXPECTED=$(awk 'NR == 1 {print $1}' "$CHECKSUM_FILE")
ACTUAL=$(
  "$PYTHON_BIN" -c \
    'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' \
    "$ARCHIVE"
)
if [ "$EXPECTED" != "$ACTUAL" ]; then
  echo "release ZIP checksum mismatch" >&2
  exit 1
fi

"$PYTHON_BIN" "$SCRIPT_DIR/release_tool.py" verify-zip "$ARCHIVE"
echo "offline release verified: $ARCHIVE"
