from __future__ import annotations

import json
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest

from gigacode_agent_runtime import cli
from gigacode_agent_runtime.cli import _studio_foreground, build_parser
from tests.helpers.scheduler import scheduler_config


def test_studio_parser_accepts_workspace_open_and_json(tmp_path: Path) -> None:
    arguments = build_parser().parse_args(
        ["studio", "--workspace", str(tmp_path), "--open", "--json"]
    )

    assert arguments.command == "studio"
    assert arguments.workspace == tmp_path
    assert arguments.open_browser is True
    assert arguments.as_json is True


@pytest.mark.anyio
async def test_studio_foreground_selects_workspace_and_emits_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    observed: dict[str, Any] = {}

    class FakeTools:
        def __init__(self, config: object, *, project_scenarios: Path) -> None:
            observed["config"] = config
            observed["project_scenarios"] = project_scenarios

        async def __aenter__(self) -> FakeTools:
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

        async def open_studio(self, open_browser: bool = True) -> dict[str, object]:
            observed["open_browser"] = open_browser
            return {
                "ok": True,
                "data": {
                    "url": "http://127.0.0.1:43210/#token=test",
                    "browser_opened": open_browser,
                },
            }

    async def return_immediately() -> None:
        return None

    monkeypatch.setattr(cli, "McpToolService", FakeTools)
    monkeypatch.setattr(cli.anyio, "sleep_forever", return_immediately)
    config = scheduler_config(tmp_path)

    result = await _studio_foreground(
        config,
        tmp_path,
        open_browser=True,
        as_json=True,
    )
    output = json.loads(capsys.readouterr().out)

    assert result == 0
    assert observed["project_scenarios"] == tmp_path / ".gigacode" / "scenarios"
    assert observed["open_browser"] is True
    assert output == {
        "url": "http://127.0.0.1:43210/#token=test",
        "workspace": str(tmp_path),
    }
