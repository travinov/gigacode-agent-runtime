# Changelog

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
