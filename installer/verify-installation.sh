#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/lib/common.sh"

[ -L "$GAR_CURRENT_LINK" ] || gar_die "current version link is missing"
[ -x "$GAR_LAUNCHER" ] || gar_die "agent-runtime launcher is missing"
[ -f "$GAR_DATA_DIR/config.yaml" ] || \
  gar_die "corporate runtime configuration is missing"
for SCENARIO_NAME in \
  corporate-sequential \
  corporate-parallel \
  corporate-mixed \
  corporate-review-repair-loop
do
  [ -f "$GAR_DATA_DIR/scenarios/$SCENARIO_NAME.yaml" ] || \
    gar_die "corporate scenario is missing: $SCENARIO_NAME"
done
GIGACODE=$(gar_find_gigacode)

"$GAR_LAUNCHER" --version
"$GAR_LAUNCHER" diagnose --json
gar_verify_mcp "$GIGACODE"
echo "installation verified"
