# GigaCode Agent Runtime

Локальный MCP-first runtime для декларативных сценариев из нескольких агентов,
которые выполняются через корпоративный GigaCode CLI на базе Qwen CLI.

Runtime позволяет описать в YAML:

- последовательные шаги creator → reviewer;
- параллельный fan-out и последующий fan-in;
- смешанные DAG-сценарии;
- условные шаги;
- ограниченные review/repair loops;
- разные GigaCode model ID и permission mode для каждого агента;
- явный allowlist установленных GigaCode Skills для каждого агента;
- retry, timeout, остановку при отсутствии прогресса и продолжение прерванного
  запуска.

Версия 1 предназначена для macOS `x86_64` версии 10.15+ и Python 3.11–3.14.
Linux не является поддерживаемой платформой v1. Runtime устанавливается офлайн
из ZIP.

## Содержание

1. [Как это работает](#как-это-работает)
2. [Рабочая установка от ZIP до первого запуска](#рабочая-установка-от-zip-до-первого-запуска)
3. [Глобальная конфигурация runtime](#глобальная-конфигурация-runtime)
4. [Где создавать сценарии и агентов](#где-создавать-сценарии-и-агентов)
5. [Первый последовательный сценарий](#первый-последовательный-сценарий)
6. [Проверка и запуск сценария](#проверка-и-запуск-сценария)
7. [Полный справочник формата сценария](#полный-справочник-формата-сценария)
8. [Виды шагов: `agent` и `loop`](#виды-шагов-agent-и-loop)
9. [Последовательность, параллельность и fan-in](#последовательность-параллельность-и-fan-in)
10. [Условия](#условия)
11. [Циклы и число итераций](#циклы-и-число-итераций)
12. [Вызов через MCP из GigaCode](#вызов-через-mcp-из-gigacode)
13. [Мониторинг и продолжение запуска](#мониторинг-и-продолжение-запуска)
14. [Диагностика типовых ошибок](#диагностика-типовых-ошибок)

## Как это работает

GigaCode запускает локальный MCP-сервер `agent-runtime mcp-serve` через `stdio`.
MCP-сервер:

1. находит именованный YAML-сценарий;
2. валидирует его по JSON Schema;
3. компилирует неизменяемый `ExecutionPlan`;
4. вычисляет волны последовательного и параллельного выполнения;
5. запускает отдельный процесс GigaCode CLI для каждого готового agent step;
6. проверяет структурированный результат агента по `output_schema`;
7. сохраняет план, состояние, события и результаты на локальном диске.

Модели не работают внутри Python runtime: каждый агент выполняется выбранной
моделью через корпоративный GigaCode CLI. Внешних LLM-провайдеров проект не
использует.

Постоянно работающего фонового демона нет. Если закрыть GigaCode, MCP-процесс
прерывает активные шаги и сохраняет запуск как `interrupted`. Продолжить его
можно после следующего запуска GigaCode через `resume_run` или
`agent-runtime resume`.

Состояние по умолчанию хранится в `~/.gigacode/agent-runtime/`. Локальный Web UI
привязывается только к `127.0.0.1` и показывает граф, волны, агентов, PID,
heartbeat, события, результаты и артефакты.

## Рабочая установка от ZIP до первого запуска

### Шаг 1. Проверить корпоративный Mac

До установки выполните:

```bash
uname -s
uname -m
sw_vers -productVersion
python3 --version
gigacode --version
gigacode --help
gigacode mcp --help
```

Для release v1 ожидаются:

- `Darwin`;
- `x86_64`;
- Python 3.11, 3.12, 3.13 или 3.14;
- работающий `gigacode`;
- поддержка MCP в GigaCode CLI.

### Шаг 2. Проверить и распаковать ZIP

Рядом с архивом поставляется файл `.sha256`:

```bash
shasum -a 256 -c gigacode-agent-runtime-VERSION-macos-x86_64.zip.sha256
unzip gigacode-agent-runtime-VERSION-macos-x86_64.zip
cd gigacode-agent-runtime-VERSION-macos-x86_64
```

Не продолжайте установку, если checksum не совпал.

### Шаг 3. Установить runtime и зарегистрировать MCP

Из распакованного каталога:

```bash
./install.sh
```

Если macOS не сохранила executable bit:

```bash
sh ./install.sh
```

Installer ничего не скачивает. Он создаёт изолированное Python-окружение,
устанавливает зависимости из ZIP и регистрирует пользовательский stdio
MCP-сервер с именем `gigacode-agent-runtime`. На чистой установке он также
создаёт готовый корпоративный профиль:

- `~/.gigacode/agent-runtime/config.yaml`;
- `~/.gigacode/agent-runtime/scenarios/corporate-sequential.yaml`;
- `~/.gigacode/agent-runtime/scenarios/corporate-parallel.yaml`;
- `~/.gigacode/agent-runtime/scenarios/corporate-mixed.yaml`;
- `~/.gigacode/agent-runtime/scenarios/corporate-review-repair-loop.yaml`;
- `~/.gigacode/agent-runtime/scenarios/corporate-agent-ref.yaml`;
- `~/.gigacode/agent-runtime/scenarios/corporate-skill-ref.yaml`;
- `~/.gigacode/agents/business-analyst-proactive.md`.
- `~/.gigacode/skills/runtime-skill-probe/SKILL.md`.

Если файл уже существует, installer сохраняет его без изменений. Поэтому
обновление runtime не перезаписывает пользовательскую конфигурацию или сценарий.

### Шаг 4. Проверить установку

```bash
./installer/verify-installation.sh
agent-runtime diagnose --subprocess-smoke --json
agent-runtime scenarios list --json
agent-runtime agents list --json
agent-runtime skills list --json
gigacode mcp list
```

В открытом GigaCode вызовите `/mcp`. Сервер `gigacode-agent-runtime` должен
иметь статус «Подключен», а его инструменты не должны быть помечены как
недействительные. В `agent-runtime scenarios list --json` должны присутствовать
шесть сценариев `corporate-*`, `agent-runtime agents list --json` должен найти
`business-analyst-proactive`, а `agent-runtime skills list --json` —
`runtime-skill-probe`.

### Шаг 5. Проверить установленные model ID

В интерактивном GigaCode используйте:

```text
/model
```

Готовый корпоративный профиль уже использует точные ID:

- `vllm/Qwen3.6-35B-262k`;
- `vllm/DeepSeek-V4-Flash-262k`;
- `vllm/MiniMax-M3-161k`;
- `GigaChat-3.1-Ultra-128k`.

Наличие ID в этом списке не гарантирует доступ в любой корпоративной установке.
Сверьте их с `/model`. Для текущего acceptance ручное копирование и
редактирование YAML не требуется, если все четыре ID доступны.

### Шаг 6. Проверить автоматически установленные файлы

```bash
test -f "$HOME/.gigacode/agent-runtime/config.yaml"
ls "$HOME/.gigacode/agent-runtime/scenarios"/corporate-*.yaml
test -f "$HOME/.gigacode/agents/business-analyst-proactive.md"
test -f "$HOME/.gigacode/skills/runtime-skill-probe/SKILL.md"
```

Все команды должны завершиться успешно. Эти файлы устанавливаются прямо из
проверенного ZIP; каталог `examples/` для первого acceptance не нужен.

## Глобальная конфигурация runtime

Обычный MCP-запуск автоматически читает:

```text
~/.gigacode/agent-runtime/config.yaml
```

Минимальный файл может содержать только `schema_version`. Для предсказуемой
рабочей установки рекомендуется указать параметры явно:

```yaml
schema_version: gigacode-agent-runtime/config-v1

runtime:
  data_dir: ~/.gigacode/agent-runtime
  max_parallel_agents: 4
  default_step_timeout_seconds: 900
  graceful_cancel_seconds: 10
  max_stdout_bytes_per_step: 52428800
  max_stderr_bytes_per_step: 10485760

gigacode:
  executable: auto
  model_allowlist:
    - vllm/Qwen3.6-35B-262k
    - vllm/DeepSeek-V4-Flash-262k
    - vllm/MiniMax-M3-161k
    - GigaChat-3.1-Ultra-128k
  environment_allowlist:
    - PATH
    - HOME
    - LANG
    - LC_ALL
    - SSL_CERT_FILE
    - REQUESTS_CA_BUNDLE
    - HTTPS_PROXY
    - HTTP_PROXY
    - NO_PROXY

permissions:
  default: read_only
  allow_full_access: true
  require_full_access_confirmation: true
  max_parallel_full_access_agents: 1
  max_full_access_loop_iterations: 3
  trusted_scenario_hashes: {}

web:
  enabled: true
  host: 127.0.0.1
  port: auto
  open_automatically: false
```

После изменения конфигурации перезапустите GigaCode/MCP и снова выполните:

```bash
agent-runtime diagnose --subprocess-smoke --json
```

### Параметры `runtime`

| Параметр | Допустимое значение | Значение по умолчанию | Назначение |
|---|---|---:|---|
| `data_dir` | Непустой путь | `~/.gigacode/agent-runtime` | Каталог config, scenarios, runs и artifacts. |
| `max_parallel_agents` | Целое число `>= 1` | `4` | Глобальный максимум одновременно работающих agent subprocess. |
| `default_step_timeout_seconds` | Целое число `>= 1` | `900` | Timeout agent step, если шаг не задал свой. Участвует в расчёте timeout loop. |
| `graceful_cancel_seconds` | Целое число `>= 1` | `10` | Сколько runtime ждёт мягкого завершения процесса перед принудительной остановкой. |
| `max_stdout_bytes_per_step` | Целое число `>= 1024` | `52428800` | Максимум stdout одного шага: 50 MiB. |
| `max_stderr_bytes_per_step` | Целое число `>= 1024` | `10485760` | Максимум stderr одного шага: 10 MiB. |

### Параметры `gigacode`

| Параметр | Допустимое значение | Значение по умолчанию | Назначение |
|---|---|---|---|
| `executable` | `auto` или непустой путь | `auto` | `auto` ищет `gigacode` в `PATH`, затем `~/.gigacode/bin/gigacode`. Явный путь должен вести к executable-файлу. |
| `model_allowlist` | Список уникальных model ID | `[]` | Если список непустой, сценарии могут использовать только эти модели. Пустой список не ограничивает модели и вызывает diagnostic warning. |
| `environment_allowlist` | Уникальные имена environment variables | Безопасный системный список | Только перечисленные переменные передаются дочернему GigaCode CLI. Значения не сохраняются в событиях и Web UI. |

Не помещайте токены, пароли и другие секреты в scenario YAML, prompts или
inputs. Если корпоративному GigaCode нужна дополнительная environment variable,
добавляйте только её имя в `environment_allowlist`; значение остаётся во
внешнем окружении.

### Параметры `permissions`

| Параметр | Допустимое значение | Значение по умолчанию | Назначение |
|---|---|---|---|
| `default` | `read_only`, `propose_only`, `workspace_write`, `full_access` | `read_only` | Глобальная safety-настройка, отражаемая в effective config и diagnostics. В scenario v1 она не подставляется автоматически: `agents.*.permissions` обязательно и всегда задаётся явно. |
| `allow_full_access` | `true` / `false` | `false` | Разрешает сценариям запрашивать `full_access`. |
| `require_full_access_confirmation` | `true` / `false` | `true` | Требует подтверждения точного `plan_hash` перед full-access запуском. Рекомендуется оставлять `true`. |
| `max_parallel_full_access_agents` | Целое число `>= 1` | `1` | Отдельный предел параллельных full-access агентов. Не может быть больше `runtime.max_parallel_agents`. |
| `max_full_access_loop_iterations` | Целое число `>= 1` | `3` | Жёсткий верхний предел итераций loop, содержащего full-access агента. |
| `trusted_scenario_hashes` | `имя: sha256:<64 hex>` | `{}` | Узкое исключение подтверждения только для точного заранее проверенного плана. Изменение inputs, workspace, config или сценария меняет hash. |

Чтобы сделать `full_access` доступным, но не автоматическим:

```yaml
permissions:
  allow_full_access: true
  require_full_access_confirmation: true
  max_parallel_full_access_agents: 1
  max_full_access_loop_iterations: 3
```

`full_access` не даёт root и не обходит macOS TCC, SIP, ACL, корпоративные
политики или ограничения GigaCode CLI.

### Параметры `web`

| Параметр | Допустимое значение | Значение по умолчанию | Назначение |
|---|---|---|---|
| `enabled` | `true` / `false` | `true` | Включает локальный Web UI. |
| `host` | Только `127.0.0.1` | `127.0.0.1` | Web UI v1 не публикуется в локальную сеть. |
| `port` | `auto` или `1024..65535` | `auto` | `auto` выбирает свободный локальный порт. |
| `open_automatically` | Только `false` | `false` | Браузер открывается только по явному `open_dashboard` или CLI `--open`. |

## Где создавать сценарии и агентов

Runtime объединяет три каталога сценариев:

1. `<workspace>/.gigacode/scenarios/` — сценарии конкретного проекта;
2. `~/.gigacode/agent-runtime/scenarios/` — пользовательские сценарии для всех
   проектов;
3. встроенный каталог runtime — четыре базовых примера.

При совпадении `metadata.name` приоритет имеет проектный сценарий, затем
пользовательский, затем встроенный.

Переиспользуемые агенты GigaCode находятся в пользовательском каталоге
`~/.gigacode/agents/*.md`. Их можно создавать штатной командой GigaCode
`/agents create`, а runtime обнаруживает те же файлы через
`list_agent_profiles` или `agent-runtime agents list --json`.

Сценарий может либо объявить prompt локально, либо сослаться на готового агента
через `agent_ref: gigacode:<name>`. Один и тот же профиль можно использовать в
разных сценариях, последовательных шагах, параллельных ветвях и петлях.

Установленные пользовательские Skills находятся в
`~/.gigacode/skills/<name>/SKILL.md`. Runtime обнаруживает их через
`list_skill_profiles` или `agent-runtime skills list --json`. Сценарий не
наследует весь каталог автоматически: каждый агент получает только явно
перечисленные `skill_refs`.

Роль агента задаётся:

- именем YAML-ключа, например `creator`;
- точным `model`;
- `permissions`;
- ровно одним из `system_prompt`, `system_prompt_file` или `agent_ref`;
- при необходимости списком `allowed_tools`.
- при необходимости allowlist `skill_refs`.

`metadata.description` описывает весь сценарий, а `system_prompt` описывает роль
конкретного агента.

### Переиспользование агента из GigaCode

Installer уже создаёт безопасный пример:

```text
~/.gigacode/agents/business-analyst-proactive.md
~/.gigacode/agent-runtime/scenarios/corporate-agent-ref.yaml
```

Ссылка в сценарии выглядит так:

```yaml
agents:
  business_analyst:
    agent_ref: gigacode:business-analyst-proactive
    model: vllm/Qwen3.6-35B-262k
    permissions: propose_only
```

Runtime читает Markdown front matter и текст системной инструкции, затем
фиксирует полное содержимое и SHA-256 профиля в `ExecutionPlan`. Уже созданный
run продолжает использовать снимок даже после изменения исходного `.md`;
следующий план получит новый hash. `model` и `permissions` остаются явными в
сценарии: профиль не может незаметно повысить права или заменить модель.

Если в профиле есть `tools` и `disallowedTools`, runtime применяет их как
исходный allowlist только когда сценарий не задал собственный `allowed_tools`.
Явный список сценария имеет приоритет.

### Явное назначение Skills агенту

```yaml
agents:
  business_analyst:
    agent_ref: gigacode:business-analyst-proactive
    model: vllm/Qwen3.6-35B-262k
    permissions: propose_only
    skill_refs:
      - gigacode:business-analysis
      - gigacode:requirements-review
```

`skill_refs` — список до 16 уникальных ссылок формата `gigacode:<name>`.
Отсутствующий или пустой список означает, что runtime не предоставляет агенту
Skills. До запуска runtime проверяет каждый `SKILL.md`, фиксирует его текст и
SHA-256 в плане и добавляет только выбранные инструкции в system prompt агента.
Изменение `SKILL.md` меняет `plan_hash` следующего запуска.

При наличии `skill_refs` runtime отключает нативный GigaCode tool `skill` для
дочернего процесса: это не позволяет механизму автоматического discovery
подмешать остальные установленные Skills. Выбранные ссылки и hashes видны в
ExecutionPlan, событиях и Web UI.

Для `read_only` и `propose_only` доступны только инструкции из `SKILL.md`:
скрипты, файловые операции и MCP по-прежнему запрещены. `workspace_write` или
`full_access` могут выполнять разрешённые инструменты и обращаться к файлам
выбранного Skill относительно показанного `base_dir`. `skill_refs` ограничивает
канал выбора Skills runtime, но не является файловой ACL: агент с
`full_access` технически может читать другие доступные ему файлы.

Installer кладёт безопасную проверку в готовые пути:

```text
~/.gigacode/skills/runtime-skill-probe/SKILL.md
~/.gigacode/agent-runtime/scenarios/corporate-skill-ref.yaml
```

## Готовый последовательный сценарий

Installer уже создаёт файл:

```text
~/.gigacode/agent-runtime/scenarios/corporate-sequential.yaml
```

Содержимое:

```yaml
schema_version: gigacode-agent-runtime/scenario-v1
kind: Scenario

metadata:
  name: corporate-sequential
  title: Corporate creator and independent reviewer
  description: Create a structured draft, then review it with a second model.

inputs:
  task:
    type: string
    required: true
    description: Task for creator and reviewer.

agents:
  creator:
    model: vllm/Qwen3.6-35B-262k
    permissions: propose_only
    system_prompt: |
      Ты автор решения.
      Подготовь практичный структурированный результат.
      Не изменяй файлы рабочего каталога.

  reviewer:
    model: vllm/DeepSeek-V4-Flash-262k
    permissions: read_only
    system_prompt: |
      Ты независимый reviewer.
      Проверь результат на полноту, безопасность и выполнимость.
      Не изменяй файлы рабочего каталога.

steps:
  create:
    kind: agent
    agent: creator
    needs: []
    prompt:
      template: "Подготовь решение задачи: ${inputs.task}"
    output_schema:
      type: object
      required: [draft]
      properties:
        draft:
          type: string
      additionalProperties: false

  review:
    kind: agent
    agent: reviewer
    needs: [create]
    prompt:
      template: |
        Проверь решение для задачи "${inputs.task}":

        ${steps.create.output.draft}
    output_schema:
      type: object
      required: [approved, feedback]
      properties:
        approved:
          type: boolean
        feedback:
          type: string
      additionalProperties: false

result:
  from: "${steps.review.output}"
```

Почему шаги выполняются последовательно:

- `create.needs: []` — шаг готов в первой волне;
- `review.needs: [create]` — шаг запускается только после успешного `create`;
- `${steps.create.output.draft}` передаёт структурированный результат
  creator в prompt reviewer.

Точная версия файла поставляется в
`corporate-profile/scenarios/corporate-sequential.yaml` и автоматически
устанавливается в user catalog.

## Проверка и запуск сценария

### 1. Убедиться, что runtime видит сценарий

```bash
agent-runtime scenarios list --json
```

Через MCP аналогичную операцию выполняет `list_scenarios`.

### 2. Проверить синтаксис и JSON Schema

```bash
agent-runtime scenario validate \
  "$HOME/.gigacode/agent-runtime/scenarios/corporate-sequential.yaml" \
  --json
```

Через MCP: `validate_scenario`.

### 3. Скомпилировать план без запуска моделей

```bash
agent-runtime scenario plan \
  "$HOME/.gigacode/agent-runtime/scenarios/corporate-sequential.yaml" \
  --workspace . \
  --input task='"Составить чек-лист безопасной офлайн-установки Python CLI"' \
  --json
```

Проверьте в плане:

- `workspace`;
- `agents.*.model`;
- `agents.*.permissions`;
- `waves`;
- `max_parallel_agents`;
- `capability_requirements`;
- `plan_hash`.

Для последовательного примера ожидаются две волны:

```text
wave 1: create
wave 2: review
```

### 4. Запустить

```bash
agent-runtime run corporate-sequential \
  --workspace . \
  --input task='"Составить чек-лист безопасной офлайн-установки Python CLI"' \
  --idempotency-key corporate-sequential-smoke-v1 \
  --json
```

Для повторной отправки той же задачи используйте тот же `idempotency_key`.
Повтор ключа с другим планом отклоняется как `IDEMPOTENCY_CONFLICT`.

## Полный справочник формата сценария

### Верхний уровень

| Параметр | Обязателен | Допустимое значение | Назначение |
|---|---:|---|---|
| `schema_version` | Да | Только `gigacode-agent-runtime/scenario-v1` | Версия контракта YAML. |
| `kind` | Да | Только `Scenario` | Тип документа. Не путать с `steps.*.kind`. |
| `metadata` | Да | Object | Имя, заголовок и описание сценария. |
| `inputs` | Нет | Object | Входные параметры, которые пользователь передаёт при запуске. |
| `agents` | Да | Непустой object | Определения агентов, моделей, ролей и прав. |
| `steps` | Да | Непустой object | DAG из шагов `agent` и `loop`. |
| `max_parallel_agents` | Нет | Целое число `>= 1` | Лимит этого сценария. Не может превышать глобальный лимит runtime. |
| `result` | Да | Object с `from` | Ссылка на итоговый структурированный output. |

Неизвестные поля запрещены. Это помогает находить опечатки до запуска моделей.

Имена scenario, input, agent и step должны соответствовать:

```text
^[a-z][a-z0-9_-]{0,63}$
```

То есть имя начинается со строчной латинской буквы, затем содержит строчные
буквы, цифры, `_` или `-`, максимум 64 символа.

### `metadata`

| Параметр | Обязателен | Ограничение | Назначение |
|---|---:|---|---|
| `name` | Да | Identifier | Стабильное имя для `list_scenarios`, CLI и MCP. |
| `title` | Да | 1..200 символов | Человекочитаемый заголовок. |
| `description` | Нет | До 4000 символов | Назначение и границы всего сценария. |

### `inputs`

Каждый ключ `inputs.<имя>` поддерживает:

| Параметр | Обязателен | Допустимое значение | Назначение |
|---|---:|---|---|
| `type` | Да | `string`, `integer`, `number`, `boolean`, `object`, `array` | Тип входного значения. |
| `required` | Нет | `true` / `false` | Нужно ли обязательно передать input. |
| `description` | Нет | До 1000 символов | Подсказка пользователю и вызывающему агенту. |
| `default` | Нет | Значение типа input | Используется, если значение не передано. |

Пример:

```yaml
inputs:
  task:
    type: string
    required: true
  severity:
    type: string
    default: medium
  include_tests:
    type: boolean
    default: true
  max_findings:
    type: integer
    default: 10
```

Неизвестный input или значение неправильного типа отклоняется при
`plan_scenario`, до запуска GigaCode.

### `agents`

Каждый `agents.<имя>` поддерживает:

| Параметр | Обязателен | Допустимое значение | Назначение |
|---|---:|---|---|
| `model` | Да | Непустой точный model ID | Модель GigaCode для всех шагов этого агента. |
| `permissions` | Да | Один из четырёх режимов | Реальный approval/sandbox режим дочернего GigaCode CLI. |
| `system_prompt` | Один из трёх | Непустая строка | Встроенное описание роли агента. |
| `system_prompt_file` | Один из трёх | Относительный путь | Роль из отдельного UTF-8 файла рядом со сценарием. |
| `agent_ref` | Один из трёх | `gigacode:<name>` | Переиспользуемый агент из `~/.gigacode/agents`. |
| `allowed_tools` | Нет | Список уникальных строк | Точные tool ID, передаваемые через `--allowed-tools` для `full_access`, если GigaCode поддерживает capability. |
| `skill_refs` | Нет | До 16 уникальных `gigacode:<name>` | Skills из `~/.gigacode/skills`, явно доступные только этому агенту. Пустой или отсутствующий список ничего не наследует. |

Режимы `permissions`:

| Значение | Поведение |
|---|---|
| `read_only` | Анализ без изменения workspace; GigaCode запускается в обычном approval mode `default`, но без tools, MCP и extensions. |
| `propose_only` | Подготовка текста или структурированного предложения без применения изменений; используется тот же изолированный режим `default`. |
| `workspace_write` | Разрешены изменения внутри workspace; GigaCode запускается в auto-edit с sandbox. |
| `full_access` | Расширенный auto-edit режим. Требует глобального разрешения и, как правило, подтверждения точного `plan_hash`. |

В v1 `read_only` и `propose_only` используют одинаковый технический профиль,
но сохраняются как разные намерения сценария. Нативный `approval-mode plan` не
используется: он включает интерактивный Plan Mode Qwen и требует
`exit_plan_mode`, что несовместимо с изолированным структурированным агентом.
Ограничение `allowed_tools` применяется адаптером только к `full_access`.

Для `read_only` и `propose_only` runtime отключает наследуемые extensions,
глобальные MCP, skills и core tools. Это предотвращает рекурсивный вызов самого
runtime и не расходует контекст модели на схемы посторонних инструментов. Для
такого запуска GigaCode CLI должен поддерживать `--extensions`,
`--max-session-turns`, `--core-tools`, `--allowed-mcp-server-names` и
`--exclude-tools`; отсутствие любой из этих возможностей приводит к fail-closed
`CAPABILITY_UNAVAILABLE`.

Роль можно вынести в файл рядом со сценарием:

```yaml
agents:
  reviewer:
    model: vllm/DeepSeek-V4-Flash-262k
    permissions: read_only
    system_prompt_file: prompts/reviewer.md
```

Runtime разрешает читать prompt/schema resources только из допустимых корней,
фиксирует их содержимое в плане и включает hash ресурса в `plan_hash`. Путь
задаётся относительно каталога scenario YAML и не должен выходить за
разрешённый корень.

Для `agent_ref` произвольные пути запрещены: runtime ищет имя только в
`~/.gigacode/agents`, отклоняет symlink-файлы и дубликаты имён и включает
снимок профиля в `scenario_hash`, `resource_hashes` и `plan_hash`.

Для `skill_refs` произвольные пути также запрещены: runtime ищет
`~/.gigacode/skills/<каталог>/SKILL.md`, проверяет front matter, UTF-8,
дубликаты и symlink-пути. Корневой `SKILL.md` сохраняется в snapshot; его
соседние scripts/references остаются файлами установленного Skill и требуют
соответствующих permissions.

### `result`

| Параметр | Обязателен | Назначение |
|---|---:|---|
| `from` | Да | Интерполяционная ссылка на итоговый output, обычно `${steps.<имя>.output}`. |

Пример:

```yaml
result:
  from: "${steps.review.output}"
```

## Виды шагов: `agent` и `loop`

Имя `improve` в записи:

```yaml
steps:
  improve:
    kind: loop
```

является произвольным именем шага. Оно могло называться `quality_gate`,
`review_cycle` или иначе.

У `steps.<имя>.kind` в scenario v1 есть только два значения:

| `kind` | Что делает |
|---|---|
| `agent` | Один раз запускает указанного агента через отдельный GigaCode CLI subprocess. |
| `loop` | Повторяет внутренний DAG из agent steps до выполнения `until` или защитного лимита. |

Отдельных `kind: parallel`, `kind: sequential`, `kind: branch` или
`kind: reviewer` нет. Последовательность и параллельность вычисляются по
`needs`, а условная ветка задаётся через `when`.

Внутри `loop.body.steps` разрешены только `kind: agent`. Вложенный
`kind: loop` в v1 не поддерживается.

### Параметры шага `kind: agent`

| Параметр | Обязателен | Допустимое значение | Назначение |
|---|---:|---|---|
| `kind` | Да | Только `agent` | Тип шага. |
| `agent` | Да | Имя из `agents` | Какой agent definition выполнить. |
| `needs` | Да | Список имён top-level шагов | Прямые зависимости. Пустой список означает готовность в первой волне. |
| `prompt` | Да | Object | Пользовательская задача для этого запуска агента. |
| `output_schema` | Да | JSON Schema object или путь к JSON-файлу | Контракт результата. Невалидный output не принимается. |
| `when` | Нет | Condition object | Если условие ложно, шаг получает статус `skipped`. |
| `timeout_seconds` | Нет | Целое число `>= 1` | Timeout этого agent subprocess; иначе используется глобальный default. |
| `retry` | Нет | Retry object | Управляемые повторы только для перечисленных типов ошибок. |

`needs` определяет только зависимости. Оно не передаёт данные автоматически.
Для передачи результата используйте ссылку в `prompt`.

### `prompt`

Нужно задать ровно одно:

| Параметр | Назначение |
|---|---|
| `template` | Текст prompt непосредственно в YAML. |
| `template_file` | Относительный путь к отдельному UTF-8 prompt-файлу. |

Дополнительно можно задать:

| Параметр | Назначение |
|---|---|
| `context` | Object с дополнительными значениями. Прямые строковые значения object поддерживают интерполяцию; runtime добавляет результат к prompt как канонический JSON-блок `Context`. |

Пример:

```yaml
prompt:
  template: "Проанализируй задачу ${inputs.task}"
  context:
    workspace: "${workspace.root}"
    severity: "${inputs.severity}"
```

### `output_schema`

Каждый agent step обязан вернуть JSON object, соответствующий JSON Schema
Draft 2020-12.

Встроенная схема:

```yaml
output_schema:
  type: object
  required: [approved, feedback]
  properties:
    approved:
      type: boolean
    feedback:
      type: string
  additionalProperties: false
```

Или отдельный JSON-файл:

```yaml
output_schema: schemas/review.json
```

Если модель вернула обычный текст, пропустила обязательное поле или изменила
тип поля, шаг завершается как `invalid_output`. Эту ошибку можно явно включить
в retry policy.

### `retry`

| Параметр | Обязателен | Допустимое значение | Назначение |
|---|---:|---|---|
| `max_attempts` | Да, если есть `retry` | `1..20` | Общее число попыток, включая первую. |
| `backoff_seconds` | Нет | До 19 чисел `>= 0` | Задержки после неуспешных попыток. Если список короче, повторяется последняя задержка. |
| `on` | Нет | Список failure reason | Повторять только указанные категории. |

Допустимые значения `retry.on`:

| Значение | Причина |
|---|---|
| `process_error` | GigaCode subprocess завершился с ошибкой, не классифицированной как transient. |
| `transient_cli_error` | GigaCode CLI вернул временную retryable ошибку. |
| `invalid_output` | Результат не прошёл `output_schema`. |
| `timeout` | Agent step превысил `timeout_seconds`. |

Пример:

```yaml
retry:
  max_attempts: 3
  backoff_seconds: [2, 10]
  on:
    - transient_cli_error
    - invalid_output
    - timeout
```

Без `retry` выполняется одна попытка. Ошибки, отсутствующие в `retry.on`,
автоматически не повторяются.

## Последовательность, параллельность и fan-in

Runtime строит DAG по `needs` и разбивает его на волны.

### Последовательно

```yaml
steps:
  create:
    kind: agent
    agent: creator
    needs: []
    # prompt и output_schema

  review:
    kind: agent
    agent: reviewer
    needs: [create]
    # prompt и output_schema

  publish:
    kind: agent
    agent: publisher
    needs: [review]
    # prompt и output_schema
```

Волны: `[create]` → `[review]` → `[publish]`.

### Параллельно

```yaml
steps:
  technical_analysis:
    kind: agent
    agent: analyst
    needs: []
    # prompt и output_schema

  security_analysis:
    kind: agent
    agent: security_reviewer
    needs: []
    # prompt и output_schema
```

Оба шага попадают в одну волну и могут выполняться одновременно, если
`max_parallel_agents >= 2`.

### Параллельно с объединением результата

```yaml
steps:
  technical_analysis:
    kind: agent
    agent: analyst
    needs: []
    # prompt и output_schema

  security_analysis:
    kind: agent
    agent: security_reviewer
    needs: []
    # prompt и output_schema

  synthesize:
    kind: agent
    agent: synthesizer
    needs: [technical_analysis, security_analysis]
    prompt:
      template: |
        Объедини результаты:
        technical=${steps.technical_analysis.output.findings}
        security=${steps.security_analysis.output.findings}
    # output_schema
```

Волны: `[technical_analysis, security_analysis]` → `[synthesize]`.

### Смешанный граф

```text
prepare
   │
   ├── branch_a ──┐
   └── branch_b ──┴── consolidate
```

В YAML:

```yaml
prepare:
  needs: []
branch_a:
  needs: [prepare]
branch_b:
  needs: [prepare]
consolidate:
  needs: [branch_a, branch_b]
```

Циклическая зависимость в `needs` отклоняется до запуска.

## Условия

`when` у agent step и `until` у loop используют один тип condition.

### Простое условие

```yaml
when:
  ref: "${steps.review.output.approved}"
  op: eq
  value: false
```

| Параметр | Обязателен | Назначение |
|---|---:|---|
| `ref` | Да | Одна интерполяционная ссылка `${...}`. |
| `op` | Да | Оператор сравнения. |
| `value` | Для всех, кроме обычного `exists` | Значение для сравнения. У `exists` по умолчанию `true`. |

Допустимые `op`:

| `op` | Значение |
|---|---|
| `eq` | Равно; типы операндов должны быть совместимы. |
| `ne` | Не равно. |
| `lt` | Меньше; поддерживаются два числа или две строки. |
| `lte` | Меньше или равно. |
| `gt` | Больше. |
| `gte` | Больше или равно. |
| `contains` | Строка содержит строку, array содержит элемент или object содержит ключ. |
| `exists` | Ссылка доступна (`value: true`) или отсутствует (`value: false`). |

### Составные условия

Все условия должны выполняться:

```yaml
when:
  all:
    - ref: "${steps.review.output.approved}"
      op: eq
      value: false
    - ref: "${steps.review.output.severity}"
      op: gte
      value: 2
```

Достаточно одного:

```yaml
when:
  any:
    - ref: "${steps.review.output.blocking}"
      op: eq
      value: true
    - ref: "${steps.review.output.score}"
      op: lt
      value: 80
```

Отрицание:

```yaml
when:
  not:
    ref: "${steps.review.output.approved}"
    op: eq
    value: true
```

### Доступные ссылки

| Ссылка | Где доступна | Значение |
|---|---|---|
| `${inputs.name}` | Везде | Input сценария; можно обращаться к вложенным полям. |
| `${steps.step_name.output}` | После top-level шага | Весь output шага или вложенное поле. |
| `${run.id}` | В prompt/context | Текущий `run_id`. |
| `${workspace.root}` | В prompt/context | Абсолютный workspace запуска. |
| `${loop.iteration}` | Внутри loop | Номер итерации, начиная с 1. |
| `${loop.steps.step_name.output}` | Внутри loop | Output внутреннего шага текущей итерации. |
| `${loop.previous.step_name.output}` | Внутри loop | Output внутреннего шага предыдущей итерации. |
| `${loop.previous_or_initial.step_name.output}` | Внутри loop | Предыдущая итерация; на первой итерации — output одноимённого top-level шага. |

Если template целиком состоит из одной ссылки, исходный JSON-тип сохраняется.
Если ссылка встроена в текст, object/array сериализуется в JSON.

## Циклы и число итераций

Loop — ограниченный внутренний DAG. Неограниченных циклов в v1 нет.

### Параметры шага `kind: loop`

| Параметр | Обязателен | Допустимое значение | Назначение |
|---|---:|---|---|
| `kind` | Да | Только `loop` | Тип шага. |
| `needs` | Да | Список top-level шагов | Когда можно начать весь loop. |
| `body.steps` | Да | Непустой набор `kind: agent` | Внутренний DAG одной итерации. Вложенные loops не разрешены. |
| `until` | Да | Condition | Условие успешного завершения loop. Проверяется после каждой внутренней wave. |
| `max_iterations` | Одно из двух ограничений | Целое число `>= 1` | Максимум итераций. Если указан только timeout, используется default `10`. |
| `timeout_seconds` | Одно из двух ограничений | Целое число `>= 1` | Общий deadline всего loop. Если указаны только iterations, default равен `default_step_timeout_seconds * max_iterations`. |
| `on_limit` | Нет | `fail`, `pause`, `best_effort` | Что делать при iterations limit, timeout или no-progress. Default: `fail`. |
| `no_progress` | Нет | Object | Остановить loop при повторении одинакового структурированного fingerprint. |

Нужно указать хотя бы одно: `max_iterations` или `timeout_seconds`.
Рекомендуется указывать оба.

`on_limit`:

| Значение | Поведение |
|---|---|
| `fail` | Loop и весь зависимый запуск завершаются ошибкой. |
| `pause` | Запуск приостанавливается, сохраняя последнюю итерацию для анализа. |
| `best_effort` | Последний доступный результат принимается, запуск отмечается как best effort. |

`no_progress`:

| Параметр | Обязателен | Назначение |
|---|---:|---|
| `max_unchanged_iterations` | Да | После скольких повторных совпадений fingerprint остановить loop. |
| `fingerprint` | Да | Непустой список ссылок на стабильные структурированные поля. |

Если loop содержит хотя бы одного `full_access` агента, фактическое
`max_iterations` дополнительно ограничивается глобальным
`permissions.max_full_access_loop_iterations`.

### Полный review/repair loop

Этот сценарий:

1. создаёт начальный candidate;
2. reviewer проверяет candidate;
3. при `approved: false` creator исправляет его;
4. следующая итерация проверяет исправленную версию;
5. loop останавливается при approval, лимите, timeout или отсутствии прогресса.

```yaml
schema_version: gigacode-agent-runtime/scenario-v1
kind: Scenario

metadata:
  name: corporate-review-repair
  title: Bounded review and repair
  description: Create, review and repair a candidate until approved.

inputs:
  task:
    type: string
    required: true

agents:
  creator:
    model: vllm/Qwen3.6-35B-262k
    permissions: propose_only
    system_prompt: |
      Создавай и исправляй candidate по задаче и замечаниям reviewer.
      Всегда возвращай структурированный JSON.

  reviewer:
    model: vllm/DeepSeek-V4-Flash-262k
    permissions: read_only
    system_prompt: |
      Проверяй candidate независимо.
      Ставь approved=true только при отсутствии существенных замечаний.

steps:
  candidate:
    kind: agent
    agent: creator
    needs: []
    prompt:
      template: "Создай начальный результат для задачи: ${inputs.task}"
    output_schema:
      type: object
      required: [candidate]
      properties:
        candidate:
          type: string
      additionalProperties: false

  improve:
    kind: loop
    needs: [candidate]
    max_iterations: 4
    timeout_seconds: 1800
    on_limit: pause
    no_progress:
      max_unchanged_iterations: 2
      fingerprint:
        - "${loop.steps.review.output.feedback}"
        - "${loop.steps.candidate.output.candidate}"

    body:
      steps:
        review:
          kind: agent
          agent: reviewer
          needs: []
          prompt:
            template: |
              Проверь результат для задачи "${inputs.task}":

              ${loop.previous_or_initial.candidate.output.candidate}
          output_schema:
            type: object
            required: [approved, feedback]
            properties:
              approved:
                type: boolean
              feedback:
                type: string
            additionalProperties: false

        candidate:
          kind: agent
          agent: creator
          needs: [review]
          when:
            ref: "${loop.steps.review.output.approved}"
            op: eq
            value: false
          prompt:
            template: |
              Исправь результат для задачи "${inputs.task}".

              Предыдущий результат:
              ${loop.previous_or_initial.candidate.output.candidate}

              Замечания:
              ${loop.steps.review.output.feedback}
          output_schema:
            type: object
            required: [candidate]
            properties:
              candidate:
                type: string
            additionalProperties: false

    until:
      ref: "${loop.steps.review.output.approved}"
      op: eq
      value: true

result:
  from: "${steps.improve.output}"
```

На первой итерации
`${loop.previous_or_initial.candidate.output.candidate}` берёт output
top-level шага `candidate`. На последующих итерациях она берёт исправленный
candidate из предыдущей итерации.

Внутренние шаги loop также используют `needs`, поэтому внутри одной итерации
можно создавать параллельные проверки и общий repair/fan-in.

## Вызов через MCP из GigaCode

Обычная автоматизация использует последовательность:

1. при необходимости `list_agent_profiles` или `describe_agent_profile`, чтобы
   найти переиспользуемые роли из `~/.gigacode/agents`;
2. при необходимости `list_skill_profiles` или `describe_skill_profile`, чтобы
   выбрать точные `skill_refs` из `~/.gigacode/skills`;
3. `list_scenarios` или `describe_scenario`; `describe_scenario` возвращает
   полный YAML-контракт агентов, шагов, зависимостей и output schemas;
4. `validate_scenario`;
5. `plan_scenario` с `inputs_yaml`;
6. проверка waves, моделей, permissions, Skills, workspace и `plan_hash`;
7. `start_run`;
8. `get_run_status` и `get_run_events`;
9. `get_run_result`;
10. при необходимости `get_run_artifacts` или `open_dashboard`.

Пример запроса в чат GigaCode:

```text
Используй MCP-сервер gigacode-agent-runtime.

Запусти именованный сценарий corporate-sequential.
Рабочий каталог: текущий проект.
task: "Составить чек-лист безопасной офлайн-установки Python CLI".

Передай входные значения только через inputs_yaml как YAML-текст:
task: Составить чек-лист безопасной офлайн-установки Python CLI
Не используй параметр inputs и не кодируй JSON-объект строкой.

Сначала выполни validate_scenario и plan_scenario с inputs_yaml.
Покажи waves, модели, permissions, workspace и plan_hash.
Если план валиден, вызови start_run с тем же inputs_yaml. Не проси меня
придумывать idempotency_key и не переходи к Shell при ошибке MCP.
Опрашивай get_run_status до конечного состояния, затем вызови
get_run_events, get_run_result и open_dashboard.
```

`start_run` возвращает `run_id` сразу, а выполнение продолжается внутри
локального MCP-процесса.

`idempotency_key` не является `run_id`. Для `get_run_status`,
`get_run_events`, `get_run_result` и `open_dashboard` используйте только
`run_id` из ответа `start_run`.

Обычный пользователь не задаёт `idempotency_key`. MCP-клиент может
автоматически сгенерировать безопасный уникальный ключ для нового действия и
сохранить его только для возможного retry этого же `start_run`.

`inputs_yaml` — строка с YAML mapping, а не вложенный JSON object и не
JSON-encoded string. Например:

```yaml
task: Составить чек-лист проверки локального MCP-сервера
```

Для inline-сценария используйте `inline_scenario_yaml` и передавайте YAML,
начинающийся с `schema_version`, а не JSON. Это wire-контракт совместимости с
GigaCode/Qwen CLI.

Если MCP-клиент оборвал запрос по timeout до получения ответа, после
переподключения повторите `start_run` с теми же scenario, `inputs_yaml`,
workspace и `idempotency_key`. Runtime вернёт уже созданный run вместо
дублирования. Не делайте вывод, что run не существует, только по клиентскому
timeout.

### Full-access approval через MCP

Если план содержит `permissions: full_access` и требует подтверждения:

1. запуск переходит в `waiting_for_approval`;
2. проверьте точные workspace, models, tools, permissions, waves и `plan_hash`;
3. вызовите `approve_run` с тем же `run_id`, `plan_hash` и
   `gate: full_access`;
4. вызовите `resume_run`.

Изменение сценария, config, inputs или workspace создаёт другой `plan_hash`;
старое подтверждение не применяется.

## Мониторинг и продолжение запуска

Открыть Web UI существующего запуска:

```bash
agent-runtime dashboard RUN_ID --open
```

Через MCP:

```text
open_dashboard(run_id=RUN_ID)
```

Основные lifecycle tools:

| Tool | Назначение |
|---|---|
| `get_run_status` | Текущий status, steps и blocker. |
| `get_run_events` | События с cursor-based pagination. |
| `get_run_result` | Итог terminal run. |
| `get_run_artifacts` | Метаданные сохранённых артефактов. |
| `pause_run` | Пауза после активной wave. |
| `resume_run` | Продолжение `paused`, `interrupted` или подтверждённого запуска. |
| `cancel_run` | Отмена и завершение process groups. |
| `open_dashboard` | Одноразовый локальный URL Web UI. |

CLI-эквиваленты:

```bash
agent-runtime status RUN_ID --json
agent-runtime events RUN_ID --json
agent-runtime result RUN_ID --json
agent-runtime resume RUN_ID --json
agent-runtime cancel RUN_ID --json
```

Если GigaCode закрыт во время выполнения, после повторного запуска сначала
проверьте сохранённый status и используйте `resume_run`. Не создавайте дубликат
того же запуска без необходимости.

## Диагностика типовых ошибок

### MCP подключен, но tools недействительны

Проверьте:

```bash
agent-runtime diagnose --json
gigacode mcp list
agent-runtime mcp-serve
```

У каждого MCP tool должны быть непустые `name`, `description` и корректная
input schema.

### `MODEL_NOT_ALLOWED`

Model ID сценария отсутствует в непустом
`gigacode.model_allowlist`. Исправьте allowlist или agent model и
перезапустите MCP.

### GigaCode не знает модель

Сверьте точное имя через `/model`. Runtime передаёт значение без переименования
в `gigacode --model <ID>`.

### План не показывает параллельность

Посмотрите `waves`:

- независимые шаги должны иметь одинаковые уже выполненные зависимости;
- для первой параллельной волны используйте `needs: []`;
- сценарный и глобальный `max_parallel_agents` должны быть больше 1.

Наличие нескольких агентов само по себе не означает параллельность.

### `invalid_output`

Модель вернула результат, не соответствующий `output_schema`. Упростите и
уточните schema/system prompt либо добавьте ограниченный retry на
`invalid_output`.

Runtime сам добавляет точный `output_schema` в system prompt агента. Корпоративный
GigaCode/Qwen может вернуть итоговый объект внутри строкового Markdown-блока
`json`; такой точный блок поддерживается. Текст до или после JSON намеренно не
извлекается.

При ошибке дочернего процесса проверьте `get_run_artifacts`. Для каждой
неуспешной попытки сохраняются redacted-файлы:

```text
runs/RUN_ID/artifacts/steps/STEP/attempt-N/stdout.jsonl
runs/RUN_ID/artifacts/steps/STEP/attempt-N/stderr.txt
```

Файлы создаются даже при пустом stderr. Это позволяет отличить ошибку transport,
отсутствующий terminal `result` и ошибку локальной проверки `output_schema`.

### Loop не завершается

Проверьте:

- возвращает ли reviewer поле, указанное в `until`;
- совпадают ли типы в condition;
- получает ли следующая итерация предыдущий candidate;
- заданы ли `max_iterations` и `timeout_seconds`;
- используется ли стабильный `no_progress.fingerprint`.

### Full access отклонён

Убедитесь, что:

- `permissions.allow_full_access: true`;
- GigaCode CLI поддерживает нужные capabilities;
- подтверждён точный текущий `plan_hash`;
- full-access loop не превышает
  `permissions.max_full_access_loop_iterations`.

## Готовые примеры и дополнительная документация

Для корпоративной проверки installer автоматически размещает шесть готовых
сценариев с проверенными model ID:

- `corporate-sequential`;
- `corporate-parallel`;
- `corporate-mixed`;
- `corporate-review-repair-loop`;
- `corporate-agent-ref`;
- `corporate-skill-ref`.

Их исходники находятся в `corporate-profile/scenarios/`.

В репозитории также находятся пять переносимых шаблонов:

- [sequential.yaml](examples/scenarios/sequential.yaml);
- [parallel.yaml](examples/scenarios/parallel.yaml);
- [mixed.yaml](examples/scenarios/mixed.yaml);
- [review-repair-loop.yaml](examples/scenarios/review-repair-loop.yaml);
- [agent-ref.yaml](examples/scenarios/agent-ref.yaml).

Переносимые встроенные шаблоны используют `REPLACE_WITH_GIGACODE_*`, потому что
доступные model ID могут различаться между корпоративными установками. Для
первого корпоративного acceptance используйте готовые `corporate-*`, поэтому
копировать или исправлять шаблоны не требуется. Runtime намеренно отклоняет
`plan_scenario` и `start_run`, пока хотя бы один agent model начинается с
`REPLACE_WITH_`; автоматической подстановки модели по умолчанию нет.

Дополнительные документы:

- [Формат сценария](docs/scenario-format.md);
- [Permissions и full access](docs/permissions.md);
- [Циклы и защита от зацикливания](docs/loops.md);
- [MCP API](docs/mcp-api.md);
- [Web UI](docs/web-ui.md);
- [Офлайн-установка](docs/offline-installation.md);
- [Корпоративный acceptance](docs/corporate-acceptance-checklist.md);
- [Диагностика и восстановление](docs/troubleshooting.md).

Optional Skill находится в [optional-skill/SKILL.md](optional-skill/SKILL.md).
Он объясняет GigaCode правильный порядок MCP-вызовов, но не требуется для работы
MCP, CLI или Web UI.

JSON Schema являются источником истины для допустимых параметров:

- [config-v1.schema.json](schemas/config-v1.schema.json);
- [scenario-v1.schema.json](schemas/scenario-v1.schema.json).

Архитектурная спецификация и план разработки сохранены в
`docs/superpowers/`.
