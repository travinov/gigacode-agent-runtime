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

На чистой установке installer также размещает готовый корпоративный профиль в
`~/.gigacode/agent-runtime/`: `config.yaml` и четыре сценария `corporate-*`.
Существующие файлы с теми же именами сохраняются без изменений.

После установки:

```bash
agent-runtime diagnose --json
agent-runtime scenarios list --json
gigacode mcp list
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
