"""Primary GigaCode/Qwen CLI agent adapter."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from jsonschema import Draft202012Validator

from ..domain import PermissionMode
from ..errors import AgentRuntimeError, ErrorCode
from ..hashing import canonical_json
from ..process_supervisor import ProcessResult, ProcessSupervisor
from ..redaction import Redactor
from .capabilities import GigaCodeCapabilities, parse_capabilities
from .stream_parser import ParsedStream, StreamJsonParser, parse_json_result


@dataclass(frozen=True, slots=True)
class AgentRequest:
    model: str
    system_prompt: str
    prompt: str
    permission: PermissionMode
    allowed_tools: tuple[str, ...]
    workspace: Path
    output_schema: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class AgentExecutionResult:
    output: Mapping[str, object]
    events: tuple[Mapping[str, object], ...]
    process: ProcessResult
    environment_keys: tuple[str, ...]
    capabilities: GigaCodeCapabilities


class GigaCodeQwenAdapter:
    def __init__(
        self,
        *,
        executable: Path,
        environment_allowlist: tuple[str, ...],
        source_environment: Mapping[str, str] | None = None,
        max_stdout_bytes: int,
        max_stderr_bytes: int,
        graceful_cancel_seconds: float,
    ) -> None:
        self._executable = executable.resolve(strict=True)
        source = os.environ if source_environment is None else source_environment
        self._environment = {
            name: source[name] for name in environment_allowlist if name in source
        }
        secret_values = [
            value
            for name, value in self._environment.items()
            if re.search(r"(TOKEN|SECRET|PASSWORD|API_?KEY)", name, re.IGNORECASE)
        ]
        self._redactor = Redactor(secret_values)
        self._supervisor = ProcessSupervisor(
            max_stdout_bytes=max_stdout_bytes,
            max_stderr_bytes=max_stderr_bytes,
            graceful_cancel_seconds=graceful_cancel_seconds,
        )

    async def _diagnostic_command(self, arguments: tuple[str, ...]) -> ProcessResult:
        result = await self._supervisor.run(
            (self._executable, *arguments),
            input_text="",
            cwd=self._executable.parent,
            environment=self._environment,
            timeout_seconds=10,
        )
        if result.returncode != 0:
            raise AgentRuntimeError(
                ErrorCode.CAPABILITY_UNAVAILABLE,
                f"GigaCode capability command failed: {' '.join(arguments)}",
                details={
                    "returncode": result.returncode,
                    "stderr": self._redactor.redact_text(result.stderr),
                },
            )
        return result

    async def detect_capabilities(self) -> GigaCodeCapabilities:
        version = await self._diagnostic_command(("--version",))
        help_result = await self._diagnostic_command(("--help",))
        mcp_help = await self._diagnostic_command(("mcp", "--help"))
        return parse_capabilities(
            self._executable,
            version.stdout.strip(),
            help_result.stdout + help_result.stderr,
            mcp_help.stdout + mcp_help.stderr,
        )

    def _required_capabilities(self, request: AgentRequest) -> set[str]:
        required = {"model_selection", "system_prompt"}
        if request.permission in {PermissionMode.READ_ONLY, PermissionMode.PROPOSE_ONLY}:
            required.add("approval_plan")
        elif request.permission is PermissionMode.WORKSPACE_WRITE:
            required.update({"approval_auto_edit", "sandbox"})
        elif request.permission is PermissionMode.FULL_ACCESS:
            required.update({"approval_auto_edit", "allowed_tools"})
        return required

    def _command(
        self,
        request: AgentRequest,
        capabilities: GigaCodeCapabilities,
    ) -> tuple[list[str | Path], str, str]:
        capabilities.require(self._required_capabilities(request))
        argv: list[str | Path] = [
            self._executable,
            "--model",
            request.model,
            "--system-prompt",
            request.system_prompt,
            "--approval-mode",
        ]
        if request.permission in {PermissionMode.READ_ONLY, PermissionMode.PROPOSE_ONLY}:
            argv.append("plan")
        else:
            argv.append("auto-edit")
        if request.permission is PermissionMode.WORKSPACE_WRITE:
            argv.append("--sandbox")
        if request.permission is PermissionMode.FULL_ACCESS and request.allowed_tools:
            argv.extend(["--allowed-tools", ",".join(request.allowed_tools)])

        if capabilities.stream_input and capabilities.stream_output:
            argv.extend(
                [
                    "--input-format",
                    "stream-json",
                    "--output-format",
                    "stream-json",
                ]
            )
            input_text = canonical_json(
                {"type": "message", "role": "user", "content": request.prompt}
            )
            return argv, input_text + "\n", "stream-json"

        capabilities.require({"json_output"})
        argv.extend(["--output-format", "json", request.prompt])
        return argv, "", "json"

    def _validate_output(
        self,
        output: Mapping[str, object],
        schema: Mapping[str, object],
    ) -> None:
        errors = sorted(
            Draft202012Validator(schema).iter_errors(dict(output)),
            key=lambda error: tuple(str(part) for part in error.absolute_path),
        )
        if not errors:
            return
        error = errors[0]
        raise AgentRuntimeError(
            ErrorCode.STEP_OUTPUT_INVALID,
            f"Agent output failed schema validation: {error.message}",
            details={"path": "/" + "/".join(str(part) for part in error.absolute_path)},
            retryable=True,
        )

    async def run_agent(
        self,
        request: AgentRequest,
        *,
        timeout_seconds: float,
        capabilities: GigaCodeCapabilities | None = None,
    ) -> AgentExecutionResult:
        detected = capabilities or await self.detect_capabilities()
        argv, input_text, output_format = self._command(request, detected)
        process = await self._supervisor.run(
            argv,
            input_text=input_text,
            cwd=request.workspace.resolve(strict=True),
            environment=self._environment,
            timeout_seconds=timeout_seconds,
        )
        redacted_stderr = self._redactor.redact_text(process.stderr)
        if process.timed_out:
            raise AgentRuntimeError(
                ErrorCode.PROCESS_TIMEOUT,
                "GigaCode agent process timed out",
                details={
                    "pid": process.pid,
                    "forced_kill": process.forced_kill,
                    "stderr": redacted_stderr,
                },
                retryable=True,
            )
        if process.returncode != 0:
            raise AgentRuntimeError(
                ErrorCode.PROCESS_ERROR,
                f"GigaCode agent process exited with code {process.returncode}",
                details={
                    "returncode": process.returncode,
                    "stderr": redacted_stderr,
                    "stdout_truncated": process.stdout_truncated,
                    "stderr_truncated": process.stderr_truncated,
                },
                retryable=process.returncode == 75,
            )

        events: tuple[Mapping[str, object], ...] = ()
        if output_format == "stream-json":
            parser = StreamJsonParser()
            parser.feed(process.stdout)
            parsed: ParsedStream = parser.finish()
            output = parsed.result
            events = parsed.events
        else:
            output = parse_json_result(process.stdout)
        self._validate_output(output, request.output_schema)
        return AgentExecutionResult(
            output=MappingProxyType(dict(cast(Mapping[str, Any], output))),
            events=events,
            process=process,
            environment_keys=tuple(sorted(self._environment)),
            capabilities=detected,
        )
