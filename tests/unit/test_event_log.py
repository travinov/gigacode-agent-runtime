from __future__ import annotations

from pathlib import Path

from gigacode_agent_runtime.event_log import EventLog


def test_event_ids_are_monotonic_across_instances(tmp_path: Path) -> None:
    first = EventLog(tmp_path)
    second = EventLog(tmp_path)

    event_one = first.append("run.created", {"status": "planned"})
    event_two = second.append("run.started", {"status": "running"})

    assert event_one.event_id == 1
    assert event_two.event_id == 2


def test_cursor_pagination_is_stable(tmp_path: Path) -> None:
    log = EventLog(tmp_path)
    for index in range(5):
        log.append("step.output", {"index": index}, step_instance_id=f"step-{index}")

    first_page = log.read(after=0, limit=2)
    second_page = log.read(after=first_page.next_cursor, limit=2)

    assert [event.event_id for event in first_page.events] == [1, 2]
    assert [event.event_id for event in second_page.events] == [3, 4]
    assert first_page.has_more is True
    assert second_page.next_cursor == 4


def test_event_log_is_append_only_json_lines(tmp_path: Path) -> None:
    log = EventLog(tmp_path)
    log.append("run.created", {"safe": True})
    log.append("run.started", {})

    lines = (tmp_path / "events.jsonl").read_text().splitlines()

    assert len(lines) == 2
    assert '"event_id":1' in lines[0]
    assert '"event_id":2' in lines[1]
