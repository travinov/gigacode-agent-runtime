# Локальный Web UI

Web UI запускается внутри того же процесса runtime и не является отдельным
daemon:

```bash
agent-runtime dashboard RUN_ID --open
```

Через MCP используйте `open_dashboard`. `start_run` также возвращает
`dashboard_url`, если `web.enabled: true`.

## Что отображается

- статус запуска и последняя активность;
- DAG waves и зависимости;
- agent, model ID, permission, attempt и step status;
- PID/PGID дочернего процесса и heartbeat;
- события, результат и список артефактов;
- причины `waiting_for_approval` и `waiting_for_input`.

Состояния `SILENT` и `POSSIBLY_STALLED` означают отсутствие новых heartbeat в
заданный период. Это сигнал проверить события и процесс, а не автоматическое
доказательство зависания.

## Защита

Сервер принимает только `127.0.0.1`; внешний bind отклоняется. Ссылка содержит
одноразовый fragment bootstrap credential, который браузер обменивает на
`HttpOnly`, `SameSite=Strict` cookie. Fragment удаляется из адресной строки.
Изменяющие запросы дополнительно требуют CSRF credential.

Не публикуйте dashboard через reverse proxy и не пересылайте стартовую ссылку.
Статические assets входят в офлайн-пакет; CDN и внешние скрипты не используются.

## Configuration Studio

Studio запускается тем же локальным runtime, но использует отдельный порт,
отдельную auth-сессию и cookie:

```text
/open_studio
```

или из терминала:

```bash
agent-runtime studio --workspace "$PWD" --open
```

MCP tool `open_studio` только создаёт authenticated URL и сам по себе не меняет
файлы. Studio содержит пять разделов:

- effective runtime settings;
- user/project/built-in routes;
- reusable agents из `~/.gigacode/agents`;
- user/extension/bundled Skills с видимым active source и overrides;
- встроенное офлайн-описание со справкой по полям, допустимым значениям,
  созданию ресурсов, DAG, loops, permissions и безопасному сохранению.

Каждое управляемое поле имеет кнопку `?`. Всплывающая подсказка показывает
назначение, допустимые значения, пример и, где применимо, текущие model, agent,
Skill, permission или approval-mode значения из каталога Studio.

Маршрут собирается структурированно: inputs, agents, model/permission/Skill
справочники, `needs`, prompts, output schemas, agent steps, loop body, `until` и
result. Built-in routes и extension/bundled Skills помечаются как read-only.

Каждая запись проходит две явные стадии:

1. `Preview`: production parser/schema, plan compilation, target path, текущий
   и кандидатный SHA-256, bounded unified diff;
2. `Apply`: одноразовый preview ID, session binding, optimistic conflict check,
   file lock, backup, atomic write `0600`, post-write validation и rollback.

Studio отклоняет traversal и symlink в управляемых путях. Она не отображает
значения environment variables и не предназначена для ввода произвольных MCP
секретов. Config применяется после reconnect MCP; сценарии, agents и Skills —
для последующих catalog discovery и новых планов.
