# MCP API

Транспорт v1 — локальный `stdio`. Все ответы имеют envelope:

```json
{"ok": true, "data": {}}
```

или typed error:

```json
{"ok": false, "error": {"code": "ERROR_CODE", "message": "..."}}
```

## Сценарии и диагностика

| Tool | Основные arguments | Назначение |
|---|---|---|
| `list_scenarios` | — | builtin/user/project catalog |
| `describe_scenario` | `scenario_name` | полный scenario contract: metadata, inputs, agents, step definitions, dependencies, output schemas и result |
| `list_agent_profiles` | — | агенты из `~/.gigacode/agents` с безопасными metadata |
| `describe_agent_profile` | `agent_name` | metadata и system prompt одного агента |
| `list_skill_profiles` | — | активные user/extension/bundled Skills, выбранный источник и `shadowed_sources` |
| `describe_skill_profile` | `skill_name` | metadata, источник и инструкции выбранного Skill |
| `validate_scenario` | ровно один из `scenario_name`, `inline_scenario_yaml` | schema validation |
| `plan_scenario` | `workspace`, scenario, `inputs_yaml` | неизменяемый ExecutionPlan |
| `diagnose_runtime` | `subprocess_smoke=false` | structured local diagnostics |

`inline_scenario_yaml` и `inputs_yaml` ограничены 2 MiB. `workspace` должен
существовать и быть каталогом. Оба параметра являются строками с YAML, а не
вложенными JSON objects:

```yaml
task: Проверить локальный MCP runtime
```

Не передавайте `inputs` и не кодируйте JSON object строкой. Это однозначный
wire-контракт для GigaCode/Qwen CLI.

## Lifecycle

| Tool | Основные arguments | Назначение |
|---|---|---|
| `start_run` | `workspace`, scenario, `inputs_yaml`, `idempotency_key` | создать и асинхронно запустить |
| `get_run_status` | `run_id` | состояние, steps и blocker |
| `get_run_events` | `run_id`, `after=0`, `limit=100` | cursor-based events |
| `get_run_result` | `run_id` | итог terminal run |
| `get_run_artifacts` | `run_id`, `after=0`, `limit=100` | bounded artifact metadata |
| `pause_run` | `run_id` | пауза после активной wave |
| `resume_run` | `run_id` | продолжить сохранённый run |
| `cancel_run` | `run_id` | отменить и завершить process groups |

`start_run` с одинаковым `idempotency_key` и теми же параметрами возвращает тот
же run. Повтор ключа с другим plan создаёт `IDEMPOTENCY_CONFLICT`.
`idempotency_key` не является `run_id`.

Для обычного пользовательского запуска `idempotency_key` можно не передавать.
MCP-клиент должен генерировать его автоматически только для защиты повторной
отправки одного и того же `start_run`; пользователь не обязан придумывать ключ.

Если клиентский timeout произошёл до получения ответа `start_run`, после
переподключения повторите тот же вызов с теми же scenario, `inputs_yaml`,
workspace и `idempotency_key`. Не передавайте idempotency key в
`get_run_status`.

## Gates и UI

| Tool | Основные arguments | Назначение |
|---|---|---|
| `approve_run` | `run_id`, `plan_hash`, `gate=full_access` | подтвердить точный план |
| `provide_input` | `run_id`, `gate_id`, `value` | передать schema-validated input |
| `open_dashboard` | необязательный `run_id` | получить локальную одноразовую URL |

После `approve_run` или `provide_input` вызовите `resume_run`, если runtime не
возобновил сценарий в текущем lifecycle автоматически.

Events читаются страницами: передавайте `next_cursor` как следующий `after`.
API ограничивает page size и размер данных; полное содержимое артефактов остаётся
в локальном run directory.
