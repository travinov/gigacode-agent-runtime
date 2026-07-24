# GigaCode Agent Runtime

Локальный MCP-first runtime для декларативных сценариев из нескольких агентов,
которые выполняются через корпоративный GigaCode CLI на базе Qwen CLI.

Runtime позволяет описать в YAML:

- последовательные шаги creator → reviewer;
- параллельный fan-out и последующий fan-in;
- смешанные DAG-сценарии;
- ограниченные review/repair loops;
- разные GigaCode model ID и permission mode для каждого агента.

Версия 1 предназначена для macOS `x86_64` версии 10.15+ и Python 3.11–3.14.
Linux не является поддерживаемой платформой v1. Runtime устанавливается офлайн
из ZIP.

## Как это работает

GigaCode запускает локальный MCP-сервер `agent-runtime mcp-serve` через `stdio`.
MCP-сервер компилирует YAML в неизменяемый `ExecutionPlan`, запускает отдельные
процессы GigaCode CLI для готовых DAG-шагов и сохраняет состояние на локальном
диске.

Модели не работают внутри Python runtime: каждый агент выполняется выбранной
моделью через корпоративный GigaCode CLI. Внешних LLM-провайдеров проект не
использует.

Постоянно работающего фонового демона нет. Если закрыть GigaCode, MCP-процесс
корректно прерывает активные шаги и сохраняет запуск как `interrupted`.
Продолжить его можно после следующего запуска GigaCode через `resume_run` или
`agent-runtime resume`.

Состояние по умолчанию хранится в `~/.gigacode/agent-runtime/`. Локальный Web UI
привязывается только к `127.0.0.1` и показывает граф, волны, агентов, PID,
heartbeat, события, результаты и артефакты.

## Быстрый старт

Онлайн-установка release candidate одной командой:

```bash
curl -fsSL https://github.com/travinov/gigacode-agent-runtime/releases/download/v1.0.0-rc.2/install.sh | sh
```

Bootstrap поддерживает macOS 10.15+ `x86_64`, скачивает ZIP и `.sha256`,
сверяет checksum с закреплённым SHA-256 и только затем запускает штатный
installer. Если корпоративная сеть не открывает GitHub, используйте
[офлайн-установку](docs/offline-installation.md).

После офлайн-установки:

```bash
agent-runtime diagnose --json
agent-runtime scenarios list --json
```

Встроенные примеры используют очевидные placeholder model ID. Скопируйте
сценарий в `~/.gigacode/agent-runtime/scenarios/` или
`.gigacode/scenarios/`, затем замените `REPLACE_WITH_GIGACODE_*` на реальные
разрешённые корпоративные model ID.

```bash
agent-runtime scenario validate examples/scenarios/parallel.yaml --json
agent-runtime scenario plan examples/scenarios/parallel.yaml \
  --workspace . \
  --input task='"Проверить архитектуру"' \
  --json
agent-runtime run examples/scenarios/parallel.yaml \
  --workspace . \
  --input task='"Проверить архитектуру"' \
  --json
```

Открыть мониторинг существующего запуска:

```bash
agent-runtime dashboard RUN_ID --open
```

## Вызов через MCP

Обычная автоматизация использует стабильную последовательность:

1. `validate_scenario`;
2. `plan_scenario`;
3. проверка waves, моделей, permissions, workspace и `plan_hash`;
4. `start_run`;
5. `get_run_status` / `get_run_events` или `open_dashboard`;
6. `get_run_result`.

`start_run` возвращает сразу, а агенты продолжают выполняться в процессе
локального MCP-сервера. Для full access runtime требует точный `plan_hash`;
подтверждение другого плана не принимается.

## Документация

- [Формат сценария](docs/scenario-format.md)
- [Permissions и full access](docs/permissions.md)
- [Циклы и защита от зацикливания](docs/loops.md)
- [MCP API](docs/mcp-api.md)
- [Web UI](docs/web-ui.md)
- [Офлайн-установка](docs/offline-installation.md)
- [Release checklist](docs/release-checklist.md)
- [Корпоративный acceptance](docs/corporate-acceptance-checklist.md)
- [Диагностика и восстановление](docs/troubleshooting.md)

Optional Skill находится в `optional-skill/SKILL.md`. Он объясняет агенту
правильный порядок MCP-вызовов, но не требуется для работы MCP, CLI или Web UI.

Архитектурная спецификация и план разработки сохранены в `docs/superpowers/`.
