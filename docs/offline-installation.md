# Офлайн-установка на macOS

V1 поддерживает корпоративный Mac с macOS 10.15+, архитектурой `x86_64` и
Python 3.11–3.14. Установка не обращается к PyPI: ZIP содержит wheel runtime,
совместимый wheelhouse, документацию, примеры и installer scripts.

## Предварительная проверка

На корпоративном Mac:

```bash
uname -s
uname -m
sw_vers -productVersion
python3 --version
gigacode --version
gigacode --help
gigacode mcp --help
```

Ожидаются `Darwin`, `x86_64`, поддерживаемый Python и работающий GigaCode CLI.

## Проверка архива

Рядом с ZIP поставляется `.sha256`:

```bash
shasum -a 256 -c gigacode-agent-runtime-VERSION-macos-x86_64.zip.sha256
unzip gigacode-agent-runtime-VERSION-macos-x86_64.zip
cd gigacode-agent-runtime-VERSION-macos-x86_64
```

## Установка и verification

```bash
./install.sh
./installer/verify-installation.sh
```

Корневой `install.sh` ничего не скачивает и передаёт управление штатному
`installer/install-macos.sh`. Installer создаёт versioned runtime environment,
создаёт Python `venv` сразу по окончательному content-addressed versioned path,
переключает атомарный `current` symlink и регистрирует локальный stdio MCP.
Новая сборка с той же публичной версией получает отдельный path по SHA-256
project wheel, поэтому release candidate можно безопасно обновлять с
сохранением rollback. При сбое до commit выполняется rollback.

На чистой установке installer также размещает `config.yaml`, шесть сценариев
`corporate-*` в `~/.gigacode/agent-runtime/`, пример переиспользуемого агента
`~/.gigacode/agents/business-analyst-proactive.md` и безопасный Skill
`~/.gigacode/skills/runtime-skill-probe/SKILL.md`. Он также регистрирует
custom command `~/.gigacode/commands/open_studio.md`, доступную в GigaCode как
`/open_studio`. Существующие файлы с теми же именами сохраняются без изменений.

Если runtime обнаруживает уже установленные `doc-review` и `secure-coding`, он
также размещает `corporate-simple-skills.yaml`. При отсутствии любого из них
пример пропускается и базовая установка остаётся работоспособной.

После установки:

```bash
agent-runtime diagnose --json
agent-runtime scenarios list --json
agent-runtime agents list --json
agent-runtime skills list --json
test -f "$HOME/.gigacode/commands/open_studio.md"
gigacode mcp list
```

На корпоративной машине с `doc-review` и `secure-coding` дополнительно:

```bash
test -f "$HOME/.gigacode/agent-runtime/scenarios/corporate-simple-skills.yaml"
```

Пути установки и точный registration result выводятся installer. Пользовательские
config, runs и scenarios не удаляются при обновлении.

## Rollback и удаление

```bash
./installer/rollback.sh
./installer/uninstall-macos.sh
```

Rollback переключает `current` на предыдущую полностью установленную версию.
Uninstaller удаляет регистрацию MCP и файлы программы, но по умолчанию
сохраняет `~/.gigacode/agent-runtime/`. Удаляйте data directory отдельно только
после резервного копирования нужных runs и artifacts.

Installer хранит checksum созданной им `/open_studio`. При uninstall команда
удаляется только если её содержимое осталось неизменным; пользовательская
правка или заранее существовавшая команда сохраняется.
