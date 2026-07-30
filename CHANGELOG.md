# Changelog

## [1.0.0-rc.8] - 2026-07-30

### Fixed

- Keep the lazily started Web UI inside the MCP server lifespan instead of the
  individual `start_run` request cancel scope.
- Prevent `start_run` from hanging, failing the durable run before its first
  step, and disconnecting the GigaCode stdio MCP client when Web UI is enabled.
- Exercise the real stdio acceptance flow with Web UI enabled and verify that
  the returned dashboard URL is bound to the created `run_id`.

## [1.0.0-rc.7] - 2026-07-30

### Added

- Install a non-destructive corporate profile with ready-to-run sequential,
  parallel, mixed, and review-repair scenarios using the verified GigaCode
  model IDs.
- Seed `~/.gigacode/agent-runtime/config.yaml` with the four approved models,
  bounded parallelism, local Web UI, and confirmation-gated full access when no
  user configuration exists.

### Fixed

- Replace the ambiguous MCP `inputs` object with Qwen-compatible
  `inputs_yaml` text for `plan_scenario` and `start_run`.
- Replace `inline_scenario` with `inline_scenario_yaml` and explicitly require
  YAML text so the GigaCode tool bridge does not reinterpret JSON-looking
  strings.
- Publish parameter descriptions and MCP instructions that prohibit
  JSON-stringified nested arguments and Shell fallback.
- Roll back newly seeded profile files if installation fails while preserving
  every pre-existing user file.

## [1.0.0-rc.6] - 2026-07-29

### Changed

- Expand the README into a sequential corporate installation and configuration
  guide with complete agent, model, scenario, step, loop, and MCP examples.

### Fixed

- Return complete step definitions from `describe_scenario` so an MCP client
  can reuse the exact scenario-v1 contract instead of guessing YAML fields.
- Report actionable missing fields for incomplete `agent` and `loop` steps.
- Reject `REPLACE_WITH_*` model placeholders during planning instead of
  forwarding them to GigaCode CLI.
- Prepare the dashboard before submitting background agent execution so
  `start_run` can return its run ID without yielding to child execution first.
- Teach the optional Skill to preserve MCP-only scope, distinguish
  `idempotency_key` from `run_id`, and recover safely after a client timeout.

## [1.0.0-rc.5] - 2026-07-29

### Fixed

- Publish non-empty descriptions for all 16 MCP tools so GigaCode/Qwen CLI
  accepts them as valid tools.
- Use a content-addressed installation directory so a corrected release
  candidate replaces an older build with the same public package version while
  preserving atomic activation and rollback.

## [1.0.0-rc.4] - 2026-07-29

### Fixed

- Create the macOS installer virtual environment at its final versioned path so
  Python console-script interpreter paths remain valid after installation.
- Rebuild an existing version directory when its `agent-runtime` entrypoint is
  present but cannot run.

## [1.0.0] - 2026-07-24

### Added

- Versioned config, scenario, execution-plan, run-state, and event contracts.
- Sequential, parallel, mixed DAG, and bounded loop execution.
- Durable state, interruption recovery, idempotency, retries, and input gates.
- GigaCode/Qwen CLI capability detection and permission enforcement.
- Opt-in full access with exact-plan approval.
- Local stdio MCP server, emergency CLI, and authenticated loopback Web UI.
- Structured diagnostics and a read-only built-in scenario catalog.
- Offline macOS x86_64 packaging, verification, and rollback contracts.
- Release-candidate gates for real stdio MCP, offline dependency resolution,
  Web monitoring, recovery, and corporate acceptance evidence.
- Root-level one-command offline installer for an already downloaded and
  extracted release ZIP.
