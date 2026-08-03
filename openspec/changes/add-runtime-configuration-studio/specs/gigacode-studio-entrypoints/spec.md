## ADDED Requirements

### Requirement: CLI can open Studio without a run
The runtime SHALL provide `agent-runtime studio` with optional `--open`, `--workspace`, and existing global `--config` behavior, and the foreground command SHALL keep Studio alive until interrupted.

#### Scenario: CLI opens the default workspace Studio
- **WHEN** the user runs `agent-runtime studio --open`
- **THEN** the runtime starts an authenticated localhost Studio, opens the default browser, prints the URL, and remains in the foreground

#### Scenario: CLI selects a project workspace
- **WHEN** the user passes `--workspace /path/to/project`
- **THEN** Studio exposes that project's `.gigacode/scenarios` as the writable project scenario catalog

### Requirement: MCP exposes a non-mutating open_studio tool
The MCP server SHALL expose `open_studio` with a non-empty description and valid input schema, and calling it SHALL only start or locate Studio and return an authenticated local URL.

#### Scenario: GigaCode invokes open_studio
- **WHEN** the registered MCP client calls `open_studio`
- **THEN** it receives `{url}` and no configuration file is previewed or modified by the tool call

### Requirement: Studio and dashboard lifecycles coexist
The MCP runtime SHALL be able to serve Studio and the run dashboard during the same process without sharing session authority or stopping one server when the other starts.

#### Scenario: Both Web UIs are opened
- **WHEN** `open_dashboard` and `open_studio` are called in either order
- **THEN** both URLs remain usable with separate authentication sessions until the MCP runtime exits

### Requirement: Release installs the exact slash command
The offline release SHALL include a GigaCode user custom command whose installed filename registers `/open_studio` and whose prompt instructs GigaCode to call MCP tool `open_studio` without changing configuration directly.

#### Scenario: Clean install seeds the command
- **WHEN** the runtime is installed into a home without an existing `open_studio.md`
- **THEN** the installer writes `~/.gigacode/commands/open_studio.md` with restrictive permissions and records it for rollback

#### Scenario: Existing command is preserved
- **WHEN** `~/.gigacode/commands/open_studio.md` already exists
- **THEN** install and upgrade preserve it unchanged and report that it was preserved

### Requirement: Command ownership is safe during rollback and uninstall
Failed installation SHALL remove a newly seeded command, and uninstall SHALL remove the command only when it still matches release-owned content.

#### Scenario: User modifies the installed command
- **WHEN** the user edits `open_studio.md` after installation and then uninstalls runtime
- **THEN** the uninstaller preserves the modified file and reports it as user-owned

### Requirement: Corporate discovery remains explicitly verifiable
The release documentation SHALL provide corporate-laptop steps to restart or reload GigaCode, confirm `/open_studio` in command help/autocomplete, invoke it, and verify the returned local Studio URL.

#### Scenario: Source tests complete without GigaCode CLI
- **WHEN** release tests run on the development Mac where GigaCode is absent
- **THEN** structural command packaging and MCP behavior are verified while actual slash-command discovery remains marked pending corporate acceptance
