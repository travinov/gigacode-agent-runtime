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
| `describe_scenario` | `scenario_name` | metadata, inputs, agents и steps |
| `validate_scenario` | ровно один из `scenario_name`, `inline_scenario` | schema validation |
| `plan_scenario` | `workspace`, scenario, `inputs` | неизменяемый ExecutionPlan |
| `diagnose_runtime` | `subprocess_smoke=false` | structured local diagnostics |

`inline_scenario` ограничен 2 MiB. `workspace` должен существовать и быть
каталогом.

## Lifecycle

| Tool | Основные arguments | Назначение |
|---|---|---|
| `start_run` | `workspace`, scenario, `inputs`, `idempotency_key` | создать и асинхронно запустить |
| `get_run_status` | `run_id` | состояние, steps и blocker |
| `get_run_events` | `run_id`, `after=0`, `limit=100` | cursor-based events |
| `get_run_result` | `run_id` | итог terminal run |
| `get_run_artifacts` | `run_id`, `after=0`, `limit=100` | bounded artifact metadata |
| `pause_run` | `run_id` | пауза после активной wave |
| `resume_run` | `run_id` | продолжить сохранённый run |
| `cancel_run` | `run_id` | отменить и завершить process groups |

`start_run` с одинаковым `idempotency_key` и теми же параметрами возвращает тот
же run. Повтор ключа с другим plan создаёт `IDEMPOTENCY_CONFLICT`.

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
