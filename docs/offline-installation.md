# Офлайн-установка на macOS

V1 поддерживает корпоративный Mac с macOS 10.15+, архитектурой `x86_64` и
Python 3.11–3.14. Установка не обращается к PyPI: ZIP содержит wheel runtime,
совместимый wheelhouse, документацию, примеры и installer scripts.

Если на машине разрешён доступ к GitHub Releases, тот же проверяемый installer
можно запустить одной командой:

```bash
curl -fsSL https://github.com/travinov/gigacode-agent-runtime/releases/download/v1.0.0-rc.2/install.sh | sh
```

Этот bootstrap использует сеть только для получения release assets. После
скачивания он проверяет опубликованный checksum и закреплённый SHA-256.

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
./installer/install-macos.sh
./installer/verify-installation.sh
```

Installer создаёт versioned runtime environment, переключает атомарный
`current` symlink и регистрирует локальный stdio MCP. При сбое до commit
выполняется rollback.

После установки:

```bash
agent-runtime diagnose --json
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
