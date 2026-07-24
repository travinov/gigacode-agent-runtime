# Корпоративный acceptance checklist

Этот gate выполняется на корпоративном Mac с GigaCode CLI. Не вставляйте в
отчёт токены, cookies, внутренние URL, содержимое корпоративных файлов и
несанитизированные prompts.

## 1. Зафиксировать среду

```bash
uname -s
uname -m
sw_vers -productVersion
python3 --version
gigacode --version
gigacode mcp --help
```

Ожидается: `Darwin`, `x86_64`, macOS 10.15+ и Python 3.11–3.14. Сохраните
вывод без секретов.

## 2. Проверить и распаковать ZIP

```bash
shasum -a 256 -c gigacode-agent-runtime-v1.0.0-macos-x86_64.zip.sha256
unzip gigacode-agent-runtime-v1.0.0-macos-x86_64.zip
cd gigacode-agent-runtime-v1.0.0-macos-x86_64
```

## 3. Установить и проверить регистрацию

```bash
./install.sh
./installer/verify-installation.sh
agent-runtime --version
agent-runtime diagnose --json
gigacode mcp list
```

Ожидается версия `1.0.0`, успешная диагностика и
`gigacode-agent-runtime` в MCP list. Сохраните sanitized diagnostics.

## 4. Проверить MCP discovery

Откройте новый чат GigaCode и попросите вызвать `list_scenarios`, затем
`diagnose_runtime`. Убедитесь, что доступны все 16 tools из `docs/mcp-api.md`,
а ответы имеют envelope `ok/data` или `ok/error`.

## 5. Подготовить безопасные сценарии

Скопируйте два примера в пользовательский каталог и замените только placeholder
model ID на реальные разрешённые ID:

```bash
mkdir -p "$HOME/.gigacode/agent-runtime/scenarios"
cp examples/scenarios/sequential.yaml \
  "$HOME/.gigacode/agent-runtime/scenarios/acceptance-sequential.yaml"
cp examples/scenarios/parallel.yaml \
  "$HOME/.gigacode/agent-runtime/scenarios/acceptance-parallel.yaml"
```

Проверьте файлы до запуска:

```bash
agent-runtime scenario validate \
  "$HOME/.gigacode/agent-runtime/scenarios/acceptance-sequential.yaml" --json
agent-runtime scenario validate \
  "$HOME/.gigacode/agent-runtime/scenarios/acceptance-parallel.yaml" --json
```

## 6. Sequential и parallel через MCP

В GigaCode для каждого сценария потребуйте точную цепочку:

1. `validate_scenario`;
2. `plan_scenario` с временным workspace;
3. показать waves, модели, permissions и `plan_hash`;
4. `start_run`;
5. дождаться terminal status через `get_run_status`;
6. получить `get_run_events` и `get_run_result`.

Для parallel дополнительно вызовите `open_dashboard`. В Web UI обе ветви первой
wave должны работать одновременно, а synthesize — стартовать после обеих.
Зафиксируйте run IDs и screenshot без корпоративных данных.

## 7. Interruption и resume

Запустите безопасный read-only сценарий с задачей, которая выполняется достаточно
долго. Пока шаг активен, полностью закройте GigaCode. После повторного запуска:

1. получите status прежнего run ID;
2. убедитесь, что run сохранён как `interrupted`;
3. вызовите `resume_run`;
4. проверьте, что completed steps не запустились повторно;
5. получите terminal result.

Сохраните run ID и sanitized события `run.interrupted`/`run.resumed`.

## 8. Workspace-write confinement

Создайте два соседних временных каталога:

```bash
ACCEPT_ROOT=$(mktemp -d /private/tmp/gigacode-runtime-acceptance.XXXXXX)
mkdir "$ACCEPT_ROOT/workspace" "$ACCEPT_ROOT/outside"
```

В отдельной копии сценария задайте агенту `permissions: workspace_write`.
Сначала создайте безобидный файл внутри `workspace` — операция должна пройти.
Затем попросите создать файл в `outside` — GigaCode sandbox должен заблокировать
операцию. После проверки удалите только созданный `ACCEPT_ROOT`.

## 9. Full-access double gate

Не выполняйте разрушительных команд. Проверьте только управление разрешением:

1. при `allow_full_access: false` план должен быть отклонён;
2. включите `allow_full_access: true` и оставьте
   `require_full_access_confirmation: true`;
3. run должен перейти в `waiting_for_approval`;
4. неверный `plan_hash` должен быть отклонён;
5. точный hash должен приниматься через `approve_run`;
6. отмените run до выполнения agent step или используйте заведомо безобидную
   read-only задачу.

## 10. Rollback и uninstall

Если на машине есть предыдущая установленная версия:

```bash
./installer/rollback.sh
./installer/verify-installation.sh
```

На первой установке manual rollback неприменим; зафиксируйте `not applicable`.
Автоматический rollback всех стадий инсталлятора покрыт локальными failure
injection tests.

Завершите acceptance удалением runtime с сохранением данных:

```bash
./installer/uninstall-macos.sh
test -d "$HOME/.gigacode/agent-runtime"
```

## 11. Итоговый отчёт

Зафиксируйте:

- версии macOS, Python и GigaCode;
- `uname -m`;
- SHA-256 ZIP;
- MCP list/discovery result;
- sequential/parallel/resume run IDs;
- sanitized diagnostics;
- workspace confinement result;
- full-access gate result;
- rollback result или `not applicable`;
- uninstall result и подтверждение сохранности data directory.

Только после успешного отчёта разрешены Git-тег `v1.0.0` и публикация ZIP.
