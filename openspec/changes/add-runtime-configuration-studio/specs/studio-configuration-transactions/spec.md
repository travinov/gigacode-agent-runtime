## ADDED Requirements

### Requirement: Preview identifies the exact candidate and destination
The Studio API SHALL canonicalize and validate a structured draft, compute the exact target path and current SHA-256 state, produce a bounded unified diff, and return a short-lived opaque preview identifier bound to the authenticated Studio session.

#### Scenario: Existing agent profile is previewed
- **WHEN** an authenticated user previews a modified user agent draft
- **THEN** the response identifies the exact `.md` destination, current hash, candidate hash, validation result, and unified diff without changing the file

#### Scenario: New Skill override is previewed
- **WHEN** an authenticated user previews a user Skill whose name currently resolves to an extension Skill
- **THEN** the response identifies the new user path and labels the extension source that will become shadowed

### Requirement: Apply accepts only an unexpired preview
The Studio API SHALL apply only a one-shot preview identifier issued to the same authenticated session and SHALL reject missing, expired, already-used, or cross-session identifiers.

#### Scenario: Preview is replayed
- **WHEN** a previously applied preview identifier is submitted again
- **THEN** the API rejects it without performing another write

#### Scenario: Preview is used by another session
- **WHEN** a different Studio session submits a preview identifier
- **THEN** the API returns permission denied without revealing candidate content

### Requirement: Apply detects concurrent changes
The Studio API SHALL lock the managed target and recheck its current SHA-256 state against the state recorded by preview before replacing it.

#### Scenario: File changes after preview
- **WHEN** a managed file is edited outside Studio after preview and before Apply
- **THEN** Apply fails with a conflict diagnostic and preserves the external edit

### Requirement: Managed writes are confined and atomic
The Studio API SHALL derive target paths from validated resource names and configured roots, reject symlinks and path escapes, create parent directories safely, write UTF-8 content with mode `0600`, and atomically replace a single target.

#### Scenario: Resource name attempts traversal
- **WHEN** a draft name contains traversal or fails its resource identifier contract
- **THEN** preview fails before any managed directory or file is created

#### Scenario: Target is a symlink
- **WHEN** the derived target exists as a symbolic link
- **THEN** Apply fails with `PATH_NOT_ALLOWED` and does not follow or replace the link

### Requirement: Applied writes are recoverable
Before replacing an existing file, Studio SHALL create a timestamped backup under the runtime data directory and SHALL restore the prior file, or remove a newly created target, if persisted-content validation fails.

#### Scenario: Post-write validation fails
- **WHEN** the persisted target cannot be reloaded with its production parser after atomic replacement
- **THEN** Studio restores the previous valid state and returns a typed failure that includes the backup reference

### Requirement: Preview data is bounded and non-secret
Studio SHALL cap accepted draft size, diff size, preview count, and preview lifetime and SHALL not return environment-variable values or unrelated file contents.

#### Scenario: Oversized draft is submitted
- **WHEN** a candidate exceeds the configured Studio draft limit
- **THEN** preview rejects it before parsing or storing the candidate
