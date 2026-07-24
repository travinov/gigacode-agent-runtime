#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/lib/common.sh"

[ -L "$GAR_CURRENT_LINK" ] || gar_die "current version link is missing"
[ -x "$GAR_LAUNCHER" ] || gar_die "agent-runtime launcher is missing"
GIGACODE=$(gar_find_gigacode)

"$GAR_LAUNCHER" --version
"$GAR_LAUNCHER" diagnose --json
gar_verify_mcp "$GIGACODE"
echo "installation verified"
