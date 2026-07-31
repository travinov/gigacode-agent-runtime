---
name: runtime-skill-probe
description: Verify that a runtime agent received its explicitly assigned GigaCode Skill. Use only in the corporate skill allowlist acceptance scenario.
priority: 100
---

# Runtime Skill Probe

When this Skill is assigned by GigaCode Agent Runtime, include the exact field
`"skill_marker": "RUNTIME_SKILL_PROBE_OK"` in the final JSON object.

Also return a short `summary` describing the supplied task. Do not call tools,
read files, change the workspace, or perform network operations.
