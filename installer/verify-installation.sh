#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd "$(dirname "$0")" && pwd)
. "$SCRIPT_DIR/lib/common.sh"

[ -L "$GAR_CURRENT_LINK" ] || gar_die "current version link is missing"
[ -x "$GAR_LAUNCHER" ] || gar_die "agent-runtime launcher is missing"
[ -f "$GAR_DATA_DIR/config.yaml" ] || \
  gar_die "corporate runtime configuration is missing"
[ -f "$GAR_AGENTS_DIR/business-analyst-proactive.md" ] || \
  gar_die "reusable GigaCode agent profile is missing"
[ -f "$GAR_SKILLS_DIR/runtime-skill-probe/SKILL.md" ] || \
  gar_die "GigaCode Skill probe is missing"
[ -f "$GAR_STUDIO_COMMAND" ] || \
  gar_die "GigaCode /open_studio command is missing"
for SCENARIO_NAME in \
  corporate-sequential \
  corporate-parallel \
  corporate-mixed \
  corporate-review-repair-loop \
  corporate-agent-ref \
  corporate-skill-ref
do
  [ -f "$GAR_DATA_DIR/scenarios/$SCENARIO_NAME.yaml" ] || \
    gar_die "corporate scenario is missing: $SCENARIO_NAME"
done
GIGACODE=$(gar_find_gigacode)

"$GAR_LAUNCHER" --version
"$GAR_LAUNCHER" agents list --json
"$GAR_LAUNCHER" skills list --json
if "$GAR_LAUNCHER" skills describe doc-review --json >/dev/null 2>&1 && \
  "$GAR_LAUNCHER" skills describe secure-coding --json >/dev/null 2>&1
then
  [ -f "$GAR_DATA_DIR/scenarios/corporate-simple-skills.yaml" ] || \
    gar_die "optional simple Skills scenario is missing"
fi
"$GAR_LAUNCHER" diagnose --json
gar_verify_mcp "$GIGACODE"
echo "installation verified"
