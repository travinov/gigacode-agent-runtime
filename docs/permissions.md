# Permissions

Permission задаётся отдельно для каждого агента и преобразуется в реальные
флаги GigaCode/Qwen CLI только после capability detection.

| Режим | Назначение |
|---|---|
| `read_only` | анализ без изменения workspace |
| `propose_only` | подготовка текста/патча без применения |
| `workspace_write` | изменение файлов внутри workspace с sandbox GigaCode |
| `full_access` | расширенный режим GigaCode с явным разрешением runtime |

`read_only` и `propose_only` используют `--approval-mode default`, но runtime
одновременно передаёт пустой core-tool allowlist, пустой MCP allowlist,
`--extensions none` и denylist инструментов. Поэтому отсутствие изменений
обеспечивается фактическим нулевым набором инструментов, а не нативным Plan Mode
Qwen. Режим `plan` не применяется к дочерним структурированным агентам, потому
что он требует интерактивный `exit_plan_mode`.

## Full access

Возможность включается явно:

```yaml
schema_version: gigacode-agent-runtime/config-v1
permissions:
  allow_full_access: true
  require_full_access_confirmation: true
  max_parallel_full_access_agents: 1
  max_full_access_loop_iterations: 3
```

`full_access` не даёт root, не обходит macOS TCC, SIP, ACL, корпоративные
политики или ограничения самого GigaCode CLI. Он только выбирает более широкий
режим дочернего процесса.

Перед запуском runtime вычисляет `plan_hash`. Если требуется подтверждение:

1. запуск переходит в `waiting_for_approval`;
2. оператор проверяет workspace, model ID, инструменты, permissions и waves;
3. вызывает `approve_run` с тем же `run_id` и точным `plan_hash`;
4. вызывает `resume_run`.

Любое изменение сценария, inputs, workspace или effective config создаёт другой
hash. Старое подтверждение к нему не применяется.

`trusted_scenario_hashes` предназначен только для узко контролируемых сценариев.
Не добавляйте туда динамические или непроверенные планы. Диагностика всегда
показывает, включён ли опасный режим и требуется ли confirmation.

## Environment и секреты

Дочерний GigaCode получает только переменные из
`gigacode.environment_allowlist`. Runtime не записывает значения environment в
events, Web UI или diagnostic report. Не размещайте учётные данные в YAML,
prompt-файлах и inputs.
