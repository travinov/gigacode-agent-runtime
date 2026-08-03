# Changelog

## [1.0.0-rc.19] - 2026-08-03

### Documentation

- Add a practical Runtime Studio guide for JSON values, comma-separated and
  line-separated lists, input defaults, prompt context, conditions, Runtime
  expressions, and result mappings.
- Add a step-by-step JSON Schema guide with typed fields, required and optional
  values, arrays, nested objects, enums, nullable values, retry policy, and
  common validation errors.
- Add copyable GigaCode prompts for discovering, describing, planning, running,
  and monitoring named Runtime scenarios without exposing internal
  idempotency details to ordinary users.
- Explain that execution models are fixed by Runtime scenario aliases, how one
  reusable agent can run under different models, and how nested native
  subagents inherit the parent process model.

## [1.0.0-rc.18] - 2026-08-03

### Added

- Install complete safe examples for Config, reusable Agent, Skill, and
  Scenario objects with every supported field populated.
- Demonstrate native agent `tools` and `disallowedTools`, all Runtime
  permission values, every input type, all prompt sources, retry, external
  prompt/schema resources, composite conditions, and loop no-progress guards.
- Add Studio controls and help for retry, prompt context, external prompt/schema
  files, and no-progress fingerprints.

### Changed

- Explain in Studio and documentation that native agent `approvalMode: yolo`
  applies to direct GigaCode subagent invocation but is not inherited by Runtime
  scenarios, which use their own permission and approval contract.

## [1.0.0-rc.17] - 2026-08-03

### Added

- Add accessible `?` popovers to every managed Studio field with purpose,
  accepted values, examples, and live catalog values where applicable.
- Add a dedicated offline `Описание` section with step-by-step guides for
  Runtime settings, agents, Skills, scenarios, DAG execution, loops,
  permissions, Preview, Apply, and activation.

### Fixed

- Align Studio input constraints with the production schemas and expose the
  supported `best_effort` loop limit policy.

## [1.0.0-rc.16] - 2026-08-03

### Fixed

- Open the exact Studio bootstrap URL from the local MCP process by default so
  GigaCode link rendering cannot drop the token fragment.
- Restore an authenticated Studio page from its HttpOnly session cookie after
  refresh instead of requiring a second one-time bootstrap token.

### Added

- Render Dashboard and Studio terminal URLs as OSC 8 hyperlinks with a plain
  URL fallback.

## [1.0.0-rc.15] - 2026-08-03

### Fixed

- Update the ready corporate profile to the deployed
  `vllm/DeepSeek-V4-Flash-0731-262k` model ID.
- Migrate the exact previous DeepSeek ID in existing corporate config and
  scenarios during upgrade, preserving other content and rolling back on an
  installation failure.
- Classify GigaCode success envelopes containing `[API Error: ...]` as typed
  process failures instead of misleading structured-output validation errors.
- Mark `404 Model not found` as non-retryable and include the requested model
  ID in the persisted error details.

## [1.0.0-rc.14] - 2026-08-03

### Added

- Add the isolated Runtime Configuration Studio, the `open_studio` MCP tool,
  CLI entrypoint, and host-native `/open_studio` command.
- Add the optional ready-to-run `corporate-simple-skills` proof: `doc-review`
  and `secure-coding` execute in parallel under `propose_only`, followed by a
  no-Skill synthesis step.
- Seed the proof automatically only when both external text Skills are already
  discoverable, keeping a clean community installation valid without them.

### Security

- Keep the simple Skills proof tool-free and file-free; it does not invoke
  Draw.io, BPMN, shell, or external MCP tools.

## [1.0.0-rc.13] - 2026-07-31

### Added

- Discover active Skills from `~/.gigacode/skills`, `~/.gigacode/extensions`,
  and `~/.gigacode/bin/bundled` without scanning historical
  `~/.gigacode/extension-sources` copies.
- Report the selected `source_level`, exact source path, catalog roots, and
  shadowed candidates through MCP, CLI, scenario descriptions, and execution
  plans.

### Fixed

- Resolve duplicate Skill names deterministically instead of blocking the whole
  catalog: user overrides extension, extension overrides bundled, and a
  canonical directory name wins ties within one source level.

## [1.0.0-rc.12] - 2026-07-31

### Added

- Add per-agent `skill_refs` allowlists for installed Skills from
  `~/.gigacode/skills/<name>/SKILL.md`.
- Validate and snapshot selected Skill instructions and SHA-256 values into the
  immutable execution plan, events, and Web UI.
- Add `list_skill_profiles` and `describe_skill_profile` MCP tools plus
  `agent-runtime skills list|describe` CLI commands.
- Install a safe `runtime-skill-probe` and ready `corporate-skill-ref` scenario
  for acceptance without copying or editing files.

### Security

- Disable the native GigaCode `skill` tool whenever explicit `skill_refs` are
  present, preventing automatic discovery of unlisted Skills through that tool.
- Keep `read_only` and `propose_only` agents tool-free even when Skill
  instructions are assigned.

## [1.0.0-rc.11] - 2026-07-31

### Added

- Reuse native Markdown agents from `~/.gigacode/agents` through explicit
  `agent_ref: gigacode:<name>` scenario declarations.
- Snapshot each referenced agent prompt and SHA-256 into the immutable plan so
  resume remains stable after profile edits.
- Add `list_agent_profiles` and `describe_agent_profile` MCP tools plus
  `agent-runtime agents list|describe` CLI commands.
- Install a non-destructive `business-analyst-proactive` profile and ready
  `corporate-agent-ref` acceptance scenario.
- Validate agent front matter, duplicate names, catalog paths, symlinks, tools,
  and profile availability before execution.

## [1.0.0-rc.10] - 2026-07-31

### Fixed

- Run `read_only` and `propose_only` child agents with GigaCode approval mode
  `default` instead of native `plan`, while retaining the empty tool, MCP, and
  extension profile that makes those agents effectively read-only.
- Prevent native Qwen Plan Mode from requesting the unavailable
  `exit_plan_mode` tool and repeating output intentions until the API closes the
  response.
- Add an explicit bounded-child instruction that prohibits Plan Mode,
  delegation, tools, shell, and filesystem operations for safe agents.
- Correct execution-plan capability requirements to describe `--prompt`, JSON
  output, default approval, and no-tool isolation instead of the removed
  stream-JSON input contract.

## [1.0.0-rc.9] - 2026-07-31

### Fixed

- Use the verified GigaCode/Qwen Code 0.13.1 non-interactive contract:
  `--prompt` input with `--output-format stream-json`, without the incompatible
  stream-JSON stdin message envelope.
- Normalize terminal `result` payloads returned as an object, a JSON-encoded
  string, or an exact Markdown JSON fence, while rejecting surrounding prose.
- Append the concrete step `output_schema` to every child agent system prompt
  before validating the returned object locally.
- Isolate agents without an effective full-access tool allowlist from inherited
  extensions, global MCP servers, skills, and core tools.
- Preserve redacted stdout and stderr as per-attempt artifacts when a child
  process exits, times out, emits invalid JSON, or fails output-schema validation.

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
