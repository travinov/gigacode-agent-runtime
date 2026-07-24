# Циклы review/repair

Loop — ограниченный DAG внутри одного top-level шага. Runtime не поддерживает
неограниченные циклы.

Готовый пример: [review-repair-loop.yaml](../examples/scenarios/review-repair-loop.yaml).

## Управление повторением

Loop задаёт как минимум `max_iterations` или `timeout_seconds`. Рекомендуется
указывать оба ограничения:

- `max_iterations`: максимальное число итераций;
- `timeout_seconds`: общий deadline loop;
- `until`: типизированное условие завершения;
- `on_limit`: `fail`, `pause` или `best_effort`;
- `no_progress`: остановка при неизменном fingerprint.

Внутренние шаги также образуют DAG через `needs`. Reviewer обычно работает
первым, repair зависит от reviewer и имеет `when`, чтобы не запускаться после
approval.

`no_progress.fingerprint` должен содержать стабильные структурированные поля,
например reviewer feedback или hash кандидата. После
`max_unchanged_iterations` одинаковых fingerprint runtime останавливает loop
вместо бесконечного повторения.

## Full access внутри loop

Если хотя бы один внутренний агент использует `full_access`, runtime применяет
дополнительный верхний предел
`permissions.max_full_access_loop_iterations`, даже если YAML запросил больше.
Параллельность таких агентов отдельно ограничена
`max_parallel_full_access_agents`.

После `on_limit: pause` оператор может изучить события и артефакты, изменить
сценарий и создать новый план либо продолжить допустимый сохранённый запуск.
Runtime не ослабляет пределы автоматически.
