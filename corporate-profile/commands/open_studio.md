---
description: Открыть локальный Web UI настройки GigaCode Agent Runtime
---

Вызови MCP tool `open_studio` сервера `gigacode-agent-runtime` с
`open_browser: true`.

Не редактируй config, YAML-сценарии, файлы агентов или Skills напрямую и не
заменяй MCP-вызов shell-командой. После успешного вызова сообщи пользователю,
что в браузере открыта локальная Runtime Studio. Если tool недоступен, объясни,
что нужно переподключить MCP; как резервный ручной способ укажи
`agent-runtime studio --open`.
