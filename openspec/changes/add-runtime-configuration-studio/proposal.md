## Why

GigaCode Agent Runtime currently exposes a protected Web dashboard for observing runs, but configuring runtime settings, orchestration routes, reusable agents, and Skills still requires manual YAML or Markdown editing. A local configuration Studio will make those contracts discoverable and editable through validated catalogs while preserving the runtime's offline, localhost-only, and fail-closed security model.

## What Changes

- Add a dedicated `agent-runtime studio --open` command and an MCP `open_studio` tool that launch a configuration-focused Web UI independently of a run dashboard.
- Add a GigaCode custom slash command named `/open_studio` that invokes the MCP tool and opens or returns the authenticated local Studio URL.
- Add Studio catalog views for effective runtime settings, model and permission choices, user/project scenarios, reusable agent profiles, and active user/extension/bundled Skills.
- Add form and visual route editing for user and project scenarios, with agent and Skill references selected from runtime catalogs.
- Add create/update support for runtime configuration, writable scenarios, user agent profiles, and user Skills while keeping built-in, extension, and bundled sources read-only.
- Validate complete candidate documents before saving and show the exact target, diagnostics, and diff before a user-confirmed apply.
- Save configuration changes with path confinement, optimistic conflict detection, locking, backups, rollback, restrictive permissions, and atomic replacement.
- Report which changes are immediately visible to catalogs and which require GigaCode/MCP reconnection.

## Capabilities

### New Capabilities

- `runtime-configuration-studio`: Authenticated localhost Web UI for catalog-backed editing and validation of runtime settings, scenarios, agents, and Skills.
- `studio-configuration-transactions`: Safe preview, validation, conflict detection, and transactional persistence for Studio-managed files.
- `gigacode-studio-entrypoints`: CLI, MCP, and `/open_studio` entrypoints that open the Studio without granting the model direct configuration-write authority.

### Modified Capabilities

None.

## Impact

- Affects the Python CLI, MCP server/tool service, local Starlette Web application, static assets, runtime configuration serializers, catalogs, installer, uninstaller, release manifest, documentation, and acceptance tests.
- Adds OpenSpec planning artifacts to the runtime repository but does not change the existing scenario or configuration schema versions.
- Reuses existing bundled Starlette/Uvicorn/PyYAML/JSON Schema dependencies and introduces no CDN, remote service, or continuously running daemon.
- Corporate GigaCode slash-command discovery remains a corporate-laptop acceptance item because GigaCode CLI is not installed on the development Mac.
