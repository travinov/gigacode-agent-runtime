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

## Agent profile not found или invalid

Проверьте единый пользовательский каталог:

```bash
agent-runtime agents list --json
ls "$HOME/.gigacode/agents"/*.md
```

`agent_ref` использует формат `gigacode:<name>`, где `<name>` должен совпадать с
полем `name` в YAML front matter, а не обязательно с именем файла. Runtime
отклоняет отсутствующий профиль, дубликаты `name`, пустой system prompt,
некорректный UTF-8 и symlink-файлы. Исправьте профиль и повторите
`validate_scenario`; уже созданные runs продолжают использовать сохранённый
снимок.

## Skill profile not found или invalid

Проверьте каталог и front matter:

```bash
agent-runtime skills list --json
ls "$HOME/.gigacode/skills"/*/SKILL.md
```

`skill_refs` использует формат `gigacode:<name>`, где `<name>` совпадает с
полем `name` в `SKILL.md`. Runtime отклоняет отсутствующие Skills, дубликаты,
пустые инструкции, некорректный UTF-8 и symlink-каталоги/файлы. После
исправления снова выполните `validate_scenario` и `plan_scenario`; изменение
Skill создаёт новый `plan_hash`.

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

## `GigaCode stream ended without a result event`

RC9 использует проверенный для GigaCode/Qwen Code 0.13.1 контракт: запрос
передаётся через `--prompt`, а `stream-json` включается только для вывода.
Терминальный `result` может быть объектом, JSON-строкой или точным Markdown
JSON-блоком.

Если ошибка повторилась, вызовите `get_run_artifacts` и сохраните файлы
`steps/<step>/attempt-<N>/stdout.jsonl` и `stderr.txt`. Оба файла создаются даже
при нулевом размере stderr. Они содержат redacted-вывод фактически завершившегося
дочернего GigaCode процесса.

## Result повторяет `I will output the JSON`

Это признак нативного Qwen Plan Mode: модель пытается вызвать
`exit_plan_mode`, которого нет в безопасном no-tool профиле, и повторяет
намерение вывести JSON до закрытия ответа API. RC10 запускает `read_only` и
`propose_only` с `--approval-mode default`, сохраняя пустые tools, MCP и
extensions. Не лечите этот случай извлечением случайного JSON-фрагмента из
оборванного ответа.

## Interrupted после закрытия GigaCode

Это ожидаемое сохранённое состояние. После повторного запуска вызовите
`get_run_status`, затем `resume_run`. Уже завершённые шаги не выполняются
повторно; running step восстанавливается с новой попытки.

## Corrupted state

Runtime не перезаписывает неизвестное или невалидное состояние. Повреждённый
`run.json` копируется в forensic-файл рядом с запуском, а API возвращает
`STATE_CORRUPTED`. Сохраните весь каталог run, восстановите из резервной копии
или создайте новый запуск. Не редактируйте state во время работающего runtime.
