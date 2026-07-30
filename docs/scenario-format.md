# Формат сценария

Сценарий — YAML или JSON с `schema_version:
gigacode-agent-runtime/scenario-v1`. Неизвестные поля запрещены. Перед
выполнением runtime всегда валидирует документ и компилирует канонический
`ExecutionPlan`.

## Каталоги и приоритет

Runtime объединяет три read-only представления:

1. `project`: `.gigacode/scenarios/` текущего проекта;
2. `user`: `~/.gigacode/agent-runtime/scenarios/`;
3. `builtin`: четыре сценария, установленные вместе с runtime.

Проектный сценарий перекрывает пользовательский и встроенный сценарий с тем же
`metadata.name`. Исходный встроенный файл не изменяется.

## Агенты

Каждый элемент `agents` задаёт:

- `model`: точный model ID из корпоративного GigaCode;
- `permissions`: `read_only`, `propose_only`, `workspace_write` или
  `full_access`;
- ровно один `system_prompt` или `system_prompt_file`;
- необязательный `allowed_tools`.

Installer размещает готовые сценарии `corporate-*` с корпоративными model ID в
user catalog. Переносимые встроенные примеры используют
`REPLACE_WITH_GIGACODE_MODEL_ID`, потому что доступные model ID различаются
между установками. Placeholder никогда не заменяется моделью по умолчанию:
runtime отклоняет такой план с `MODEL_NOT_ALLOWED`.

## DAG и `needs`

`steps` — именованные узлы графа. `needs` содержит прямые зависимости.

- `needs: []` — шаг готов в первой волне;
- одинаковые зависимости позволяют шагам работать параллельно;
- шаг с `needs: [a, b]` начинается только после обоих шагов — это fan-in;
- цикл зависимостей отклоняется до запуска.

Например, [parallel.yaml](../examples/scenarios/parallel.yaml) содержит два
независимых анализа в первой волне и `synthesize` во второй. В
[mixed.yaml](../examples/scenarios/mixed.yaml) сначала работает `prepare`,
затем параллельно `branch_a` и `branch_b`, после чего — `consolidate`.

Глобальный лимит задаётся `runtime.max_parallel_agents`; сценарий может только
уменьшить его через `max_parallel_agents`.

## Inputs, prompts и outputs

`inputs` описывает типы, обязательность и default. Через MCP значения
передаются строкой `inputs_yaml`:

```yaml
task: Подготовить проектное решение
```

Не передавайте MCP-параметр `inputs` и не кодируйте JSON object строкой. Через
CLI значения передаются так:

```bash
agent-runtime scenario plan examples/scenarios/sequential.yaml \
  --workspace . \
  --input task='"Подготовить проектное решение"' \
  --json
```

В `prompt.template`, условиях и `result.from` разрешены только ограниченные
ссылки:

- `${inputs.name}`;
- `${steps.step_name.output}`;
- `${loop.iteration}`;
- `${loop.steps.step_name.output}`;
- `${loop.previous.step_name.output}`;
- `${run.id}` и `${workspace.root}`.

Каждый agent step обязан задать JSON Schema в `output_schema`. Runtime принимает
результат шага только после проверки по этой схеме. Итог сценария указывает
`result.from: "${steps.final_step.output}"`.

## Retry и timeout

`timeout_seconds` ограничивает один шаг. `retry.max_attempts`,
`retry.backoff_seconds` и `retry.on` разрешают повторы только для перечисленных
типизированных сбоев. Permanent failure не повторяется автоматически.

Полные готовые примеры:

- `~/.gigacode/agent-runtime/scenarios/corporate-sequential.yaml`
- `~/.gigacode/agent-runtime/scenarios/corporate-parallel.yaml`
- `~/.gigacode/agent-runtime/scenarios/corporate-mixed.yaml`
- `~/.gigacode/agent-runtime/scenarios/corporate-review-repair-loop.yaml`

Переносимые шаблоны:

- [sequential.yaml](../examples/scenarios/sequential.yaml)
- [parallel.yaml](../examples/scenarios/parallel.yaml)
- [mixed.yaml](../examples/scenarios/mixed.yaml)
- [review-repair-loop.yaml](../examples/scenarios/review-repair-loop.yaml)
