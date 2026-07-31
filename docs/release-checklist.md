# Release checklist v1

Статус `v1.0.0`: release candidate. RC-тег и ZIP разрешено публиковать для
корпоративного acceptance. Финальный стабильный тег разрешён только после
прохождения checklist на реальном Mac `x86_64` с реальным GigaCode CLI.

## Автоматический локальный gate

Выполняется из корня репозитория:

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy src
PYTHONPATH=src .venv/bin/python -m pytest -m 'not corporate_acceptance'
.venv/bin/python -m build
./scripts/build-offline-release.sh
./scripts/verify-offline-release.sh \
  dist/gigacode-agent-runtime-v1.0.0-macos-x86_64.zip
GIGACODE_AGENT_RUNTIME_RELEASE_ZIP="$PWD/dist/gigacode-agent-runtime-v1.0.0-macos-x86_64.zip" \
  PYTHONPATH=src .venv/bin/python -m pytest \
  tests/acceptance/test_clean_offline_install.py -q
```

Повторный запуск `build-offline-release.sh` из одного source state должен дать
тот же SHA-256.

## Матрица доказательств

| Контракт | Автоматическое доказательство |
|---|---|
| sequential шаги не перекрываются | `test_scheduler_sequential.py` |
| parallel шаги перекрываются | `test_scheduler_parallel.py`, real stdio acceptance |
| mixed fan-in ждёт upstream | `test_scheduler_mixed.py` |
| retry и loop имеют отдельные counters | `test_retry.py`, loop integration tests |
| resume не повторяет completed | `test_resume.py` |
| full access имеет global и exact-plan gates | `test_permissions.py` |
| `skill_refs` разрешает только выбранные Skills и меняет plan hash | `test_skill_catalog.py`, `test_plan_compiler.py`, adapter/MCP tests |
| MCP stdout — только protocol, Qwen wire использует YAML strings | real `ClientSession` в `test_end_to_end_fake.py`, MCP schema tests |
| Web auth, SSE, status и control | `tests/web/` и headed browser smoke |
| installer не использует package index и атомарно размещает corporate profile | installer contract и ZIP resolution test |
| rollback/uninstall сохраняют согласованность | `tests/installer/` |

## Артефакты

Обязательная пара:

```text
gigacode-agent-runtime-v1.0.0-macos-x86_64.zip
gigacode-agent-runtime-v1.0.0-macos-x86_64.zip.sha256
```

ZIP должен проходить manifest/hash/architecture verification, содержать ровно
один корневой каталог и не содержать sdist, `.DS_Store`, symlink или wheel
другой архитектуры. В корне ZIP должен находиться executable `install.sh`,
который не использует сеть и делегирует штатному macOS installer.

## Неподменяемый внешний gate

Локальный fake GigaCode подтверждает scheduler, protocol и recovery contracts,
но не подтверждает реальные флаги корпоративного GigaCode/Qwen CLI. Для выпуска
обязателен [корпоративный checklist](corporate-acceptance-checklist.md).
