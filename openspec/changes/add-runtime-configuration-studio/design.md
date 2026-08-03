## Context

The runtime already bundles a Starlette/Uvicorn localhost dashboard with one-time fragment bootstrap authentication, HttpOnly cookies, CSRF protection, strict CSP, and no external assets. The dashboard is run-centric and its API only reads run state or performs bounded run controls. Runtime configuration is loaded once when the CLI or MCP process starts, while scenario, agent, and Skill catalogs discover files on demand. User-managed artifacts currently live in four roots: the selected runtime config file, the runtime user/project scenario catalogs, `~/.gigacode/agents`, and `~/.gigacode/skills`. Extension, bundled, and built-in sources are discoverable but not user-owned.

The runtime worktree already contains in-progress catalog changes that add user/extension/bundled Skill precedence and shadowing metadata. Studio must use those APIs and must not overwrite or weaken them. The development Mac does not have GigaCode CLI, so slash-command registration can be packaged and tested structurally here, but actual discovery must remain a corporate-laptop acceptance step.

## Goals / Non-Goals

**Goals:**

- Provide a catalog-driven browser UI for runtime configuration, scenarios/routes, reusable agents, and Skills.
- Keep monitoring and configuration entrypoints distinct, with configuration writes available only to a Studio-authenticated browser session.
- Reuse production parsers, schemas, catalogs, and semantic planning validation instead of duplicating format rules in JavaScript.
- Show the exact destination, source scope, conflict hash, diagnostics, and unified diff before applying a change.
- Confine writes to exact managed targets, reject symlinks and path escapes, and make every accepted write recoverable.
- Register `/open_studio` as a GigaCode custom command that asks the registered MCP server to call `open_studio`.
- Preserve offline installation, deterministic packaging, and the no-daemon lifecycle.

**Non-Goals:**

- Editing arbitrary third-party MCP server definitions or storing their credentials.
- Editing built-in scenarios or extension/bundled Skills in place.
- Replacing YAML/Markdown as the persisted source of truth.
- Hot-reloading an already constructed `EffectiveConfig`; config changes require MCP/GigaCode reconnection.
- Providing remote bind, reverse-proxy support, multi-user access, or unattended model-driven configuration changes.
- Proving corporate GigaCode slash-command discovery on the personal development Mac.

## Decisions

### 1. Add a separate Studio application and server lifecycle

`agent-runtime studio --open` and MCP `open_studio` will start a `LocalStudioServer` on `127.0.0.1`. It will reuse the existing authentication primitives and security headers, but use a distinct session-cookie name and a separate Starlette app from the run dashboard. This keeps a dashboard credential from implicitly authorizing configuration writes and keeps the route surfaces independently testable.

Alternative considered: add configuration routes directly to the dashboard app. Rejected because it couples a routinely opened run-monitoring credential to a more privileged filesystem editor and makes least-privilege review harder.

### 2. Treat Python catalogs and schemas as the source of truth

Studio's catalog endpoint will expose effective settings, exact managed paths, permission enums, model allowlist, scenario source levels, agent profiles, and Skill source/shadowing metadata. Browser controls will be populated from that payload. Candidate documents will be submitted to Python for preview and validated with the same config schema, scenario loader/plan compiler, agent parser, and Skill parser used by runtime execution.

Alternative considered: generate all browser forms directly from JSON Schema and validate only in JavaScript. Rejected because scenario compilation includes cross-resource, DAG, model, permission, and path semantics that JSON Schema alone cannot express.

### 3. Use structured resource drafts with canonical serialization

The API accepts JSON draft objects for four resource kinds: `config`, `scenario`, `agent`, and `skill`. Python serializes config/scenario drafts as stable UTF-8 YAML and agent/Skill drafts as YAML front matter plus Markdown body. The UI does not expose a raw-file editor, although output-schema fragments and free-form prompts remain structured text inputs where their domain is inherently open-ended.

Alternative considered: accept arbitrary YAML/Markdown from a textarea. Rejected because it fails the catalog-driven usability goal and broadens the injection and format-error surface.

### 4. Preview and apply are separate, hash-bound operations

`POST /api/studio/preview` validates a candidate, computes the current target hash, creates a bounded unified diff, and returns an opaque preview identifier stored in the Studio process. The preview record is bound to the authenticated session, exact target, candidate bytes, and observed target hash and expires after a short interval. `POST /api/studio/apply` accepts only that preview identifier.

On apply, Studio locks the target, rechecks its hash, rejects symlinks/path escapes, creates a timestamped backup when a prior file exists, atomically replaces the file with mode `0600`, and revalidates the persisted target. If post-write validation fails, it restores the backup or removes the newly created file. Preview records are one-shot.

Alternative considered: have apply resubmit the candidate document. Rejected because the user could preview one byte sequence and apply another due to UI bugs or tampering.

### 5. Limit writable scopes explicitly

- Config: the exact `EffectiveConfig.source_path` selected when Studio starts.
- User scenario: `<data_dir>/scenarios/<validated-name>.yaml`.
- Project scenario: `<workspace>/.gigacode/scenarios/<validated-name>.yaml`, only when Studio was started with a validated workspace.
- Agent: `~/.gigacode/agents/<validated-name>.md`.
- Skill: `~/.gigacode/skills/<validated-name>/SKILL.md`.

Built-in scenarios and extension/bundled Skills are read-only. A user may create a user Skill with the same declared name as an extension/bundled Skill; the preview must label this as an override and show the shadowed source rather than mutating the lower-precedence source.

### 6. Use a lightweight route builder rather than a general graph framework

The initial UI will render route steps and `needs` edges with DOM/CSS and provide add/remove/reorder controls plus catalog-backed selectors. It supports agent and loop steps represented by the existing scenario schema. The client builds a scenario document and asks the backend for authoritative validation and plan waves. No third-party graph dependency or CDN is added.

Alternative considered: add a React graph library. Rejected to preserve offline packaging, reduce release size, and avoid introducing a frontend build toolchain for the current static UI.

### 7. Package `/open_studio` as a user custom command

The release will contain `corporate-profile/commands/open_studio.md`. The installer seeds it only when absent at `~/.gigacode/commands/open_studio.md`, records it for failed-install rollback, and the uninstaller removes it only when it still matches the release-owned checksum/content. The command body instructs GigaCode to invoke MCP tool `open_studio` and not to mutate configuration itself. The MCP tool starts Studio and returns an authenticated local URL; only the browser endpoints can preview/apply changes.

Alternative considered: make `/open_studio` execute a shell command. Rejected because custom-command shell interpolation requires extra approval, a foreground server would block command expansion, and it bypasses the already registered MCP lifecycle.

### 8. Report reload semantics instead of pretending to hot-reload config

Scenario, agent, and Skill changes are reported as available to subsequent catalog loads and new plans. Config changes are reported as persisted but requiring GigaCode/MCP reconnection because the running `McpToolService` holds an immutable `EffectiveConfig` snapshot.

## Risks / Trade-offs

- [Corporate GigaCode build may use a different custom-command directory or reload command] → Package the Qwen-compatible user command, verify file ownership locally, and keep corporate CLI discovery as an explicit acceptance step with a documented extension-directory fallback.
- [A browser bug could construct an invalid or incomplete route] → Keep Python preview validation authoritative and disable Apply until preview succeeds.
- [Concurrent manual edits could be overwritten] → Bind previews to the observed SHA-256 and recheck under a lock immediately before replace.
- [Atomic replacement cannot provide a cross-filesystem multi-file transaction] → Apply one managed resource per preview; each write is independently atomic and recoverable.
- [A custom config path may be outside the default runtime data directory] → Permit only the exact config path supplied to `load_config`, never an arbitrary browser-supplied path.
- [User Skill overrides can change agent behavior unexpectedly] → Label precedence and shadowed sources in both catalog and preview responses.
- [The Studio process exits when its owner exits] → Preserve the current no-daemon contract and make the URL lifecycle explicit in UI and docs.

## Migration Plan

1. Add Studio code and tests without changing existing dashboard routes or config/scenario schema versions.
2. Add CLI and MCP entrypoints and verify the MCP tool schema/stdio cleanliness with the fake runtime.
3. Add the custom command to the corporate profile and extend installer rollback/uninstall ownership tests.
4. Update the offline release manifest and documentation, then run source, installer, Web UI, and clean-install acceptance suites.
5. On the corporate laptop, install the new release, restart GigaCode, confirm `/open_studio` autocomplete/help, invoke it, preview a harmless scenario edit, and verify reconnection behavior after a config change.

Rollback removes the versioned runtime, restores the prior launcher/MCP registration, and removes only newly seeded or still-release-owned command/profile files. User-modified Studio-managed configuration remains user data and is not deleted by runtime rollback.

## Open Questions

- Which exact corporate GigaCode build first guarantees `~/.gigacode/commands/*.md` discovery? This does not block implementation; acceptance will detect whether the documented extension-command fallback is required.
