# Диагностика и восстановление

Начните с:

```bash
agent-runtime diagnose --json
```

Каждый check возвращает `ok`, `warning` или `error`, стабильный code,
remediation и ограниченные details. По умолчанию выполняются только безопасные
GigaCode `--version/--help` probes — LLM-запрос не отправляется. Дополнительный
zero-data subprocess launch:

```bash
agent-runtime diagnose --subprocess-smoke --json
```

## MCP disconnected

1. Выполните `agent-runtime diagnose --json`.
2. Проверьте `gigacode mcp list`.
3. Запустите `agent-runtime mcp-serve` вручную и убедитесь, что stdout не
   содержит логов до MCP handshake.
4. Повторите `verify-installation.sh`.

Не пытайтесь заменить runtime ручным запуском subagents: это потеряет durable
state, лимиты и permission gates.

## Missing wheels

Если installer сообщает об отсутствующем wheel, не разрешайте ему обращаться в
сеть. Проверьте checksum ZIP и используйте полный архив для вашей Python minor.

## Invalid model

Для первого acceptance используйте автоматически установленные
`corporate-sequential`, `corporate-parallel`, `corporate-mixed` или
`corporate-review-repair-loop`. Они уже содержат точные корпоративные model ID.
Переносимые встроенные шаблоны с `REPLACE_WITH_GIGACODE_*` не предназначены для
запуска без настройки. Placeholder не подставляется автоматически и
отклоняется во время `plan_scenario`.

## `params/inputs must be object`

RC7 не выставляет неоднозначный MCP-параметр `inputs`. Передавайте значения
сценария через YAML-строку:

```text
inputs_yaml: "task: Проверить локальный MCP runtime"
```

Не передавайте вложенный JSON object и не передавайте JSON-encoded string.
Для inline-сценария используйте `inline_scenario_yaml` с YAML-текстом,
начинающимся с `schema_version`.

## Timeout ответа `start_run`

Клиентский timeout не доказывает, что run не был сохранён.

1. Переподключите MCP.
2. Повторите `start_run` с идентичными scenario, `inputs_yaml`, workspace и
   `idempotency_key`.
3. Возьмите возвращённый `run_id`.
4. Только после этого вызывайте `get_run_status` и `get_run_events`.

`idempotency_key` не является `run_id`. Если повторный вызов использует другой
план, runtime вернёт `IDEMPOTENCY_CONFLICT`.

Если пользователь потребовал использовать только MCP, не переходите к Shell,
ручному запуску GigaCode или ad hoc subagents.

## Waiting for approval

Получите status и ExecutionPlan. Сверьте `plan_hash`, workspace, модели,
permissions и tools; затем вызовите `approve_run` с точным hash и `resume_run`.
Не копируйте подтверждение от другого запуска.

## Silent или possibly stalled

Откройте Web UI и проверьте последний `step.heartbeat`, PID, events и timeout.
`SILENT` сам по себе не означает зависание. При достижении timeout runtime
завершает process group и сохраняет typed error.

## Interrupted после закрытия GigaCode

Это ожидаемое сохранённое состояние. После повторного запуска вызовите
`get_run_status`, затем `resume_run`. Уже завершённые шаги не выполняются
повторно; running step восстанавливается с новой попытки.

## Corrupted state

Runtime не перезаписывает неизвестное или невалидное состояние. Повреждённый
`run.json` копируется в forensic-файл рядом с запуском, а API возвращает
`STATE_CORRUPTED`. Сохраните весь каталог run, восстановите из резервной копии
или создайте новый запуск. Не редактируйте state во время работающего runtime.
