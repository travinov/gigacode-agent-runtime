## 1. Studio domain and persistence

- [x] 1.1 Add structured Studio resource models, canonical config/scenario/agent/Skill serializers, and managed-path resolution.
- [x] 1.2 Add catalog/detail loading for effective settings, user/project/built-in scenarios, agent profiles, and composite Skill sources.
- [x] 1.3 Implement server-authoritative candidate validation with production parsers and scenario plan compilation.
- [x] 1.4 Implement session-bound preview records, bounded diffs, expiry, replay protection, and optimistic hashes.
- [x] 1.5 Implement locked atomic apply, backup creation, path/symlink guards, restrictive permissions, post-write validation, and rollback.

## 2. Studio Web server and entrypoints

- [x] 2.1 Generalize Web authentication for distinct dashboard and Studio cookies without weakening existing dashboard behavior.
- [x] 2.2 Add the authenticated localhost-only Studio API and static asset server with catalog, detail, preview, and apply routes.
- [x] 2.3 Add MCP `open_studio` lifecycle support that coexists with `open_dashboard` and remains non-mutating.
- [x] 2.4 Add `agent-runtime studio [--workspace] [--open]` foreground CLI behavior and JSON output.

## 3. Browser Studio experience

- [x] 3.1 Build the offline Studio shell, navigation, catalog overview, managed-path display, and runtime settings form.
- [x] 3.2 Build structured scenario route editing with catalog-backed agents/models/permissions/Skills, dependencies, plan-wave preview, inputs, prompts, schemas, and results.
- [x] 3.3 Build reusable agent and user Skill editors with read-only source labeling and user-override behavior.
- [x] 3.4 Build the diff/diagnostic preview and explicit one-shot Apply flow with activation/reconnection guidance.

## 4. GigaCode command packaging and documentation

- [x] 4.1 Add `corporate-profile/commands/open_studio.md` and seed it safely to `~/.gigacode/commands/open_studio.md` during install and failed-install rollback.
- [x] 4.2 Preserve user-modified command content during uninstall and cover command ownership in the release manifest/checks.
- [x] 4.3 Document Studio usage, `/open_studio`, managed file locations, reload semantics, security boundaries, and corporate-laptop acceptance.

## 5. Verification

- [x] 5.1 Add unit tests for serialization, validation, path confinement, preview expiry/replay/conflict, atomic apply, backup, and rollback.
- [x] 5.2 Add Web tests for authentication separation, CSRF, catalog/detail APIs, preview/apply flow, localhost bind, and static UI contracts.
- [x] 5.3 Add CLI and MCP tests for tool discovery, non-mutating `open_studio`, dashboard coexistence, workspace selection, and stdio cleanliness.
- [x] 5.4 Add installer, uninstaller, release-manifest, documentation, and clean-install tests for `/open_studio` packaging.
- [x] 5.5 Run formatting, static analysis, focused tests, the full source suite, OpenSpec validation, and release-aware verification; record corporate slash-command discovery as pending until run on the corporate laptop.
