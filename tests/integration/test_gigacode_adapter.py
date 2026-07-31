from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest

from gigacode_agent_runtime.adapters.gigacode_qwen import (
    AgentExecutionError,
    AgentRequest,
    GigaCodeQwenAdapter,
)
from gigacode_agent_runtime.domain import PermissionMode
from gigacode_agent_runtime.errors import AgentRuntimeError, ErrorCode
from tests.helpers.fake_gigacode import FakeGigaCode

_FAKE_ENV_NAMES = (
    "PATH",
    "FAKE_GIGACODE_PROFILE",
    "FAKE_GIGACODE_TRACE_FILE",
    "FAKE_GIGACODE_STATE_FILE",
)


def _adapter(tmp_path: Path, profile: str) -> GigaCodeQwenAdapter:
    fake = FakeGigaCode(
        profile=profile,
        trace_file=tmp_path / "trace.jsonl",
        state_file=tmp_path / "state.txt",
    )
    return GigaCodeQwenAdapter(
        executable=fake.executable,
        environment_allowlist=_FAKE_ENV_NAMES,
        source_environment=fake.environment(),
        max_stdout_bytes=1024 * 1024,
        max_stderr_bytes=1024 * 1024,
        graceful_cancel_seconds=0.1,
    )


def _request(
    tmp_path: Path,
    *,
    permission: PermissionMode = PermissionMode.READ_ONLY,
) -> AgentRequest:
    return AgentRequest(
        model="code-model-id",
        system_prompt="system instructions",
        prompt="user task",
        permission=permission,
        allowed_tools=("read_file",),
        workspace=tmp_path,
        output_schema={
            "type": "object",
            "required": ["summary"],
            "properties": {"summary": {"type": "string"}},
        },
    )


@pytest.mark.anyio
async def test_adapter_detects_capabilities_and_returns_validated_output(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path, "success")
    capabilities = await adapter.detect_capabilities()

    result = await adapter.run_agent(
        _request(tmp_path),
        timeout_seconds=2,
        capabilities=capabilities,
    )

    assert result.output["summary"] == "fake success"
    assert result.process.returncode == 0
    assert "FAKE_GIGACODE_PROFILE" in result.environment_keys
    assert "CODEX_INTERNAL_ORIGINATOR_OVERRIDE" not in result.environment_keys
    trace = (tmp_path / "trace.jsonl").read_text()
    assert "system instructions" not in trace
    assert "user task" not in trace


@pytest.mark.anyio
async def test_workspace_write_uses_sandbox_and_workspace_cwd(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, "success")

    result = await adapter.run_agent(
        _request(tmp_path, permission=PermissionMode.WORKSPACE_WRITE),
        timeout_seconds=2,
    )

    traces = [
        json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()
    ]
    assert result.output["summary"] == "fake success"
    assert "--sandbox" in traces[-1]["argv"]
    approval_index = traces[-1]["argv"].index("--approval-mode")
    assert traces[-1]["argv"][approval_index + 1] == "auto-edit"


@pytest.mark.anyio
async def test_adapter_uses_prompt_stream_output_schema_and_no_tool_isolation(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path, "success")
    request = _request(tmp_path)
    request = AgentRequest(
        model=request.model,
        system_prompt=request.system_prompt,
        prompt=request.prompt,
        permission=request.permission,
        allowed_tools=(),
        workspace=request.workspace,
        output_schema=request.output_schema,
    )

    await adapter.run_agent(request, timeout_seconds=2)

    traces = [
        json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()
    ]
    invocation = traces[-1]
    argv = invocation["argv"]
    assert "--prompt" in argv
    assert "--input-format" not in argv
    assert "--output-format" in argv
    assert "--extensions" in argv
    assert "--core-tools" in argv
    assert "--allowed-mcp-server-names" in argv
    assert invocation["stdin_empty"] is True
    assert invocation["system_prompt_has_output_contract"] is True


@pytest.mark.anyio
async def test_executable_path_with_spaces_is_not_shell_interpreted(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "fixtures" / "fake_gigacode"
    copied = tmp_path / "fake cli with spaces"
    shutil.copytree(source, copied)
    fake = FakeGigaCode(
        profile="success",
        trace_file=tmp_path / "trace.jsonl",
        state_file=tmp_path / "state.txt",
    )
    environment = fake.environment()
    adapter = GigaCodeQwenAdapter(
        executable=copied / "gigacode",
        environment_allowlist=_FAKE_ENV_NAMES,
        source_environment=environment,
        max_stdout_bytes=1024 * 1024,
        max_stderr_bytes=1024 * 1024,
        graceful_cancel_seconds=0.1,
    )

    result = await adapter.run_agent(_request(tmp_path), timeout_seconds=2)

    assert result.output["summary"] == "fake success"


@pytest.mark.anyio
async def test_workspace_write_fails_closed_without_sandbox(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, "missing-sandbox")
    capabilities = await adapter.detect_capabilities()

    with pytest.raises(AgentRuntimeError) as captured:
        await adapter.run_agent(
            _request(tmp_path, permission=PermissionMode.WORKSPACE_WRITE),
            timeout_seconds=2,
            capabilities=capabilities,
        )

    assert captured.value.code is ErrorCode.CAPABILITY_UNAVAILABLE


@pytest.mark.anyio
async def test_invalid_json_is_never_returned_as_agent_output(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, "invalid-json")

    with pytest.raises(AgentRuntimeError) as captured:
        await adapter.run_agent(_request(tmp_path), timeout_seconds=2)

    assert captured.value.code is ErrorCode.STEP_OUTPUT_INVALID
    assert isinstance(captured.value, AgentExecutionError)
    assert captured.value.stdout == "{invalid-json\n"
    assert captured.value.stderr == ""


@pytest.mark.anyio
async def test_schema_validation_error_retains_corporate_stream_capture(
    tmp_path: Path,
) -> None:
    adapter = _adapter(tmp_path, "success")
    request = _request(tmp_path)
    invalid_contract = AgentRequest(
        model=request.model,
        system_prompt=request.system_prompt,
        prompt=request.prompt,
        permission=request.permission,
        allowed_tools=request.allowed_tools,
        workspace=request.workspace,
        output_schema={
            "type": "object",
            "required": ["missing"],
            "properties": {"missing": {"type": "string"}},
        },
    )

    with pytest.raises(AgentRuntimeError) as captured:
        await adapter.run_agent(invalid_contract, timeout_seconds=2)

    assert captured.value.code is ErrorCode.STEP_OUTPUT_INVALID
    assert isinstance(captured.value, AgentExecutionError)
    assert '"type":"result"' in captured.value.stdout
    terminal = json.loads(captured.value.stdout.splitlines()[-1])
    assert terminal["result"] == (
        '\n\n```json\n{"summary":"fake success","approved":true}\n```'
    )


@pytest.mark.anyio
async def test_timeout_terminates_process_group(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, "ignore-sigterm")
    started = time.monotonic()

    with pytest.raises(AgentRuntimeError) as captured:
        await adapter.run_agent(_request(tmp_path), timeout_seconds=0.1)

    assert captured.value.code is ErrorCode.PROCESS_TIMEOUT
    assert time.monotonic() - started < 2
    assert captured.value.details["forced_kill"] is True


@pytest.mark.anyio
async def test_nonzero_exit_is_a_typed_process_error(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, "permanent")

    with pytest.raises(AgentRuntimeError) as captured:
        await adapter.run_agent(_request(tmp_path), timeout_seconds=2)

    assert captured.value.code is ErrorCode.PROCESS_ERROR
    assert "permanent fake failure" in captured.value.details["stderr"]
