## ADDED Requirements

### Requirement: Studio is an authenticated localhost-only application
The runtime SHALL serve Studio only on `127.0.0.1` with a one-time fragment bootstrap credential, a Studio-specific HttpOnly SameSite cookie, CSRF protection for state-changing requests, restrictive security headers, and no external assets.

#### Scenario: Studio opens with an issued URL
- **WHEN** an authorized CLI or MCP entrypoint starts Studio
- **THEN** the runtime returns a URL bound to `127.0.0.1` with a one-time fragment credential that is removed after browser bootstrap

#### Scenario: Non-local bind is rejected
- **WHEN** Studio is configured with a host other than `127.0.0.1`
- **THEN** startup fails with a typed configuration error before serving requests

### Requirement: Studio exposes catalog-backed configuration choices
Studio SHALL return effective runtime settings, exact managed paths, allowed permission values, configured model choices, scenario entries and source levels, reusable agent profiles, and active Skill profiles including source and shadowing metadata.

#### Scenario: Catalog is loaded
- **WHEN** an authenticated browser requests the Studio catalog
- **THEN** it receives the settings and all discoverable scenario, agent, and Skill choices without receiving secret environment values

### Requirement: Studio distinguishes writable and read-only sources
Studio SHALL permit drafts only for the selected config file, user/project scenarios, user agent profiles, and user Skills, and SHALL mark built-in scenarios plus extension/bundled Skills as read-only.

#### Scenario: Built-in scenario is selected
- **WHEN** a user views a built-in scenario
- **THEN** Studio shows its contents and source but does not offer in-place Apply

#### Scenario: Extension Skill is selected
- **WHEN** a user views an extension or bundled Skill
- **THEN** Studio offers read-only inspection and may offer creation of a separate user override without modifying the source Skill

### Requirement: Studio provides structured editors
Studio SHALL provide structured controls for runtime settings, route metadata, inputs, agents, steps, dependencies, prompts, result selection, reusable agent front matter, and user Skill front matter/instructions without requiring raw YAML or Markdown editing.

#### Scenario: Route references are selected
- **WHEN** a user configures a route agent
- **THEN** model, permission, reusable agent, and Skill references are selected from the current catalog and serialized into a scenario-v1 document

#### Scenario: Route topology is edited
- **WHEN** a user adds dependencies or loop structure
- **THEN** Studio renders the resulting topology and sends the structured scenario draft for authoritative validation

### Requirement: Authoritative validation remains server-side
Studio SHALL validate candidates using the runtime's production schemas, parsers, catalogs, and plan compiler and SHALL return field-addressable diagnostics and plan waves before Apply is enabled.

#### Scenario: Scenario contains a missing Skill reference
- **WHEN** a route draft references a Skill absent from the active catalog
- **THEN** preview fails with a typed diagnostic and Apply remains unavailable

#### Scenario: Valid parallel route is previewed
- **WHEN** a valid route draft has two independent steps followed by a fan-in step
- **THEN** preview succeeds and reports the same execution waves as the production plan compiler

### Requirement: Studio explains activation timing
Studio SHALL report whether an applied resource is visible to subsequent catalog loads or requires GigaCode/MCP reconnection.

#### Scenario: Runtime configuration is applied
- **WHEN** a valid config draft is persisted
- **THEN** Studio states that the file was saved and the active MCP process must be reconnected to use it

#### Scenario: User scenario is applied
- **WHEN** a valid user scenario is persisted
- **THEN** Studio states that it is available to subsequent catalog discovery and new plans
