#!/bin/sh
set -eu

REPOSITORY=${GIGACODE_AGENT_RUNTIME_REPOSITORY:-travinov/gigacode-agent-runtime}
RELEASE_TAG=${GIGACODE_AGENT_RUNTIME_RELEASE_TAG:-v1.0.0-rc.1}
RELEASE_VERSION=${GIGACODE_AGENT_RUNTIME_RELEASE_VERSION:-1.0.0}
EXPECTED_SHA256=${GIGACODE_AGENT_RUNTIME_EXPECTED_SHA256:-8a426e00d5531d43c9100b02b3d27263bcc5160b5fb29dbf79770ebd097edb97}
ARCHIVE="gigacode-agent-runtime-v${RELEASE_VERSION}-macos-x86_64.zip"
CHECKSUM="${ARCHIVE}.sha256"
BASE_URL="https://github.com/${REPOSITORY}/releases/download/${RELEASE_TAG}"
TEMP_ROOT=${TMPDIR:-/private/tmp}
WORK_DIR=""

die() {
  echo "error: $*" >&2
  exit 1
}

cleanup() {
  if [ -n "$WORK_DIR" ]; then
    case "$WORK_DIR" in
      "$TEMP_ROOT"/gigacode-agent-runtime-install.*)
        /bin/rm -rf "$WORK_DIR"
        ;;
    esac
  fi
}

trap cleanup EXIT HUP INT TERM

SYSTEM=${GAR_TEST_SYSTEM:-$(uname -s)}
MACHINE=${GAR_TEST_MACHINE:-$(uname -m)}
[ "$SYSTEM" = "Darwin" ] || die "v1 supports Darwin only, got $SYSTEM"
[ "$MACHINE" = "x86_64" ] || die "v1 supports x86_64 only, got $MACHINE"

for command_name in awk curl shasum unzip; do
  command -v "$command_name" >/dev/null 2>&1 ||
    die "required command not found: $command_name"
done

WORK_DIR=$(mktemp -d "$TEMP_ROOT/gigacode-agent-runtime-install.XXXXXX")
curl --fail --location --silent --show-error \
  "$BASE_URL/$ARCHIVE" --output "$WORK_DIR/$ARCHIVE"
curl --fail --location --silent --show-error \
  "$BASE_URL/$CHECKSUM" --output "$WORK_DIR/$CHECKSUM"

DECLARED_SHA256=$(awk 'NR == 1 {print $1}' "$WORK_DIR/$CHECKSUM")
[ "$DECLARED_SHA256" = "$EXPECTED_SHA256" ] ||
  die "published checksum does not match the pinned release checksum"
(cd "$WORK_DIR" && shasum -a 256 -c "$CHECKSUM")

unzip -q "$WORK_DIR/$ARCHIVE" -d "$WORK_DIR"
RELEASE_ROOT="$WORK_DIR/gigacode-agent-runtime-v${RELEASE_VERSION}-macos-x86_64"
[ -f "$RELEASE_ROOT/installer/install-macos.sh" ] ||
  die "installer is missing from the verified release"

sh "$RELEASE_ROOT/installer/install-macos.sh"
