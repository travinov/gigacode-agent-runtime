---
name: gigacode-agent-runtime
description: Run, monitor, resume, and troubleshoot declarative sequential, parallel, mixed, or looped multi-agent scenarios through the local GigaCode Agent Runtime MCP. Use when a user asks to coordinate GigaCode/Qwen CLI agents under different models, encode dependencies or review-repair loops, inspect an ExecutionPlan, control a durable run, or open the local agent dashboard.
---

# GigaCode Agent Runtime

Use the MCP runtime as the execution authority. Do not recreate its scheduler,
parallelism, retries, loops, permission logic, or durable state with manual
subagent calls.

## Select the operation

- Discover reusable scenarios with `list_scenarios` and
  `describe_scenario`. The latter returns complete agent, step, dependency,
  output-schema, and result definitions; use those definitions as the source of
  truth instead of guessing YAML fields.
- Discover native user agents with `list_agent_profiles` and
  `describe_agent_profile`. Reuse them with
  `agent_ref: gigacode:<name>` instead of copying their system prompts into a
  scenario. Keep model IDs and permissions explicit in the scenario.
- Discover installed GigaCode Skills with `list_skill_profiles` and
  `describe_skill_profile`. Grant only the required Skills to each agent with
  `skill_refs: [gigacode:<name>]`; inspect `source_level`, `source_path`, and
  `shadowed_sources`, and never assume the full active catalog is inherited.
- Prefer the installed `corporate-sequential`, `corporate-parallel`,
  `corporate-mixed`, `corporate-review-repair-loop`, `corporate-agent-ref`, or
  `corporate-skill-ref`
  scenario for corporate acceptance. They already contain approved model IDs.
- Accept a named catalog scenario or `inline_scenario_yaml`. Provide exactly
  one. Pass an inline scenario as YAML text beginning with `schema_version`,
  never as JSON text.
- Use `diagnose_runtime` when GigaCode, MCP, Web UI, model selection, or local
  permissions appear unavailable.
- Use `open_dashboard` when the user wants live monitoring.

## Prepare and start

1. Call `validate_scenario`.
2. Encode scenario input values as YAML mapping text in `inputs_yaml`. For
   example: `task: Check the local MCP runtime`. Never call the removed
   `inputs` parameter and never JSON-encode the mapping.
3. Call `plan_scenario` with the exact workspace and `inputs_yaml`.
4. Inspect and summarize waves, model IDs, permissions, workspace, capability
   requirements, assigned Skills and hashes, and `plan_hash`.
5. Call `start_run` with the identical `inputs_yaml` only when the user asked
   to execute. Generate a unique safe `idempotency_key` internally for the new
   action and reuse it only when retrying that exact request. Never ask the user
   to invent or manage this key.
6. Return the `run_id` and dashboard URL.

Never skip validation or planning. Never claim that parallel execution occurs
unless the plan places independent steps in the same wave.

`idempotency_key` is not a `run_id`. Poll only the `run_id` returned by
`start_run`. If the MCP connection times out before returning it, reconnect and
repeat `start_run` with the identical scenario, `inputs_yaml`, workspace, and
`idempotency_key`; the runtime returns the existing run. Do not assume the run
was not created.

## Monitor and finish

Poll `get_run_status` at a bounded cadence. Use `get_run_events` with its
cursor for incremental detail. When terminal, call `get_run_result` and, when
useful, `get_run_artifacts`.

For `waiting_for_approval`, show the exact plan summary and obtain user
authorization before calling `approve_run` with the returned `plan_hash`, then
call `resume_run`.

For `waiting_for_input`, show the prompt/schema and obtain a value before
calling `provide_input` with the active `gate_id`, then call `resume_run`.

Use `pause_run`, `resume_run`, or `cancel_run` only for the named `run_id`.
After a disconnected MCP process, reconnect, inspect status, and resume an
`interrupted` run instead of starting a duplicate.

If validation fails, report the typed error and correct only the fields it
identifies. Do not probe arbitrary YAML shapes. If the user restricted the task
to this MCP server, never fall back to Shell, manual GigaCode subprocesses, or
ad hoc subagents.

## Scenario guidance

- Sequential: make each step depend on its predecessor through `needs`.
- Parallel: give independent steps the same satisfied dependencies.
- Fan-in: make the combining step depend on every parallel branch.
- Loop: use a bounded loop with `until`, `max_iterations` or timeout,
  `on_limit`, and preferably `no_progress`.
- Models: require exact corporate GigaCode model IDs; do not invent them.
- Full access: treat it as opt-in, verify the exact plan, and never imply root
  or a bypass of macOS or corporate controls.

Scenario v1 uses this exact structure:

```yaml
schema_version: gigacode-agent-runtime/scenario-v1
kind: Scenario
metadata:
  name: creator-reviewer
  title: Creator and reviewer
inputs:
  task:
    type: string
    required: true
agents:
  creator:
    model: EXACT_GIGACODE_MODEL_ID
    permissions: propose_only
    system_prompt: Create a structured proposal.
    skill_refs: []
  reviewer:
    model: EXACT_GIGACODE_REVIEW_MODEL_ID
    permissions: read_only
    system_prompt: Review the proposal.
steps:
  create:
    kind: agent
    agent: creator
    needs: []
    prompt:
      template: "Create: ${inputs.task}"
    output_schema:
      type: object
      required: [draft]
      properties:
        draft: {type: string}
      additionalProperties: false
  review:
    kind: agent
    agent: reviewer
    needs: [create]
    prompt:
      template: "Review: ${steps.create.output.draft}"
    output_schema:
      type: object
      required: [approved, feedback]
      properties:
        approved: {type: boolean}
        feedback: {type: string}
      additionalProperties: false
result:
  from: "${steps.review.output}"
```

- Put `output_schema` on each agent step, not in `agents`.
- Define `steps` as a mapping keyed by step name, not as an array.
- Set `kind: agent` or `kind: loop`; v1 has no other step kinds.
- Use `needs`, not `depends_on`.
- Use `${...}`, not `{{ ... }}`.
- A model beginning with `REPLACE_WITH_` or another placeholder is not a
  runnable model and is never replaced automatically.

If the MCP runtime is unavailable, report the diagnostic error and recovery
step. Do not fall back to an ad hoc multi-agent implementation.
