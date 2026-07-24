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
  `describe_scenario`.
- Accept a named catalog scenario or an inline scenario. Provide exactly one.
- Use `diagnose_runtime` when GigaCode, MCP, Web UI, model selection, or local
  permissions appear unavailable.
- Use `open_dashboard` when the user wants live monitoring.

## Prepare and start

1. Call `validate_scenario`.
2. Call `plan_scenario` with the exact workspace and inputs.
3. Inspect and summarize waves, model IDs, permissions, workspace, capability
   requirements, and `plan_hash`.
4. Call `start_run` only when the user asked to execute. Reuse a stable
   `idempotency_key` when retrying the same request.
5. Return the `run_id` and dashboard URL.

Never skip validation or planning. Never claim that parallel execution occurs
unless the plan places independent steps in the same wave.

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

## Scenario guidance

- Sequential: make each step depend on its predecessor through `needs`.
- Parallel: give independent steps the same satisfied dependencies.
- Fan-in: make the combining step depend on every parallel branch.
- Loop: use a bounded loop with `until`, `max_iterations` or timeout,
  `on_limit`, and preferably `no_progress`.
- Models: require exact corporate GigaCode model IDs; do not invent them.
- Full access: treat it as opt-in, verify the exact plan, and never imply root
  or a bypass of macOS or corporate controls.

If the MCP runtime is unavailable, report the diagnostic error and recovery
step. Do not fall back to an ad hoc multi-agent implementation.
