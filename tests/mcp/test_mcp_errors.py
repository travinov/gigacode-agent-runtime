from __future__ import annotations

from pathlib import Path

import pytest

from gigacode_agent_runtime.mcp_errors import public_result
from gigacode_agent_runtime.mcp_tools import McpToolService
from tests.helpers.scheduler import scheduler_config


@pytest.mark.anyio
async def test_expected_error_has_stable_public_contract(tmp_path: Path) -> None:
    tools = McpToolService(scheduler_config(tmp_path))

    response = await tools.validate_scenario(
        scenario_name="missing",
        inline_scenario="also supplied",
    )

    assert response == {
        "ok": False,
        "error": {
            "code": "CONFIG_INVALID",
            "message": (
                "Provide exactly one of scenario_name or inline_scenario_yaml"
            ),
            "details": {},
            "retryable": False,
        },
    }


@pytest.mark.anyio
async def test_unexpected_error_does_not_expose_traceback() -> None:
    def explode() -> object:
        raise RuntimeError("private failure /secret/path")

    response = await public_result(explode)
    rendered = str(response)

    assert response["error"]["code"] == "INTERNAL_ERROR"
    assert "private failure" not in rendered
    assert "Traceback" not in rendered
