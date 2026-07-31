"""GigaCode/Qwen CLI discovery and feature-based capability parsing."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..errors import AgentRuntimeError, ErrorCode


@dataclass(frozen=True, slots=True)
class GigaCodeCapabilities:
    executable: Path
    version: str
    model_selection: bool
    system_prompt: bool
    prompt: bool
    approval_modes: frozenset[str]
    allowed_tools: bool
    sandbox: bool
    stream_input: bool
    json_output: bool
    stream_output: bool
    agent_isolation: bool
    mcp: bool

    @classmethod
    def empty(cls, executable: Path) -> GigaCodeCapabilities:
        return cls(
            executable=executable,
            version="unknown",
            model_selection=False,
            system_prompt=False,
            prompt=False,
            approval_modes=frozenset(),
            allowed_tools=False,
            sandbox=False,
            stream_input=False,
            json_output=False,
            stream_output=False,
            agent_isolation=False,
            mcp=False,
        )

    def available(self, name: str) -> bool:
        checks = {
            "model_selection": self.model_selection,
            "system_prompt": self.system_prompt,
            "prompt": self.prompt,
            "approval_plan": "plan" in self.approval_modes,
            "approval_auto_edit": "auto-edit" in self.approval_modes,
            "allowed_tools": self.allowed_tools,
            "sandbox": self.sandbox,
            "stream_json": self.stream_input and self.stream_output,
            "json_output": self.json_output,
            "stream_output": self.stream_output,
            "agent_isolation": self.agent_isolation,
            "mcp": self.mcp,
        }
        return checks.get(name, False)

    def require(self, names: set[str]) -> None:
        missing = sorted(name for name in names if not self.available(name))
        if missing:
            raise AgentRuntimeError(
                ErrorCode.CAPABILITY_UNAVAILABLE,
                f"GigaCode CLI is missing required capabilities: {', '.join(missing)}",
                details={
                    "missing": missing,
                    "version": self.version,
                    "executable": str(self.executable),
                },
            )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "executable": str(self.executable),
            "version": self.version,
            "model_selection": self.model_selection,
            "system_prompt": self.system_prompt,
            "prompt": self.prompt,
            "approval_modes": sorted(self.approval_modes),
            "allowed_tools": self.allowed_tools,
            "sandbox": self.sandbox,
            "stream_input": self.stream_input,
            "json_output": self.json_output,
            "stream_output": self.stream_output,
            "agent_isolation": self.agent_isolation,
            "mcp": self.mcp,
        }


def parse_capabilities(
    executable: Path,
    version: str,
    help_text: str,
    mcp_help_text: str,
) -> GigaCodeCapabilities:
    approval_modes = frozenset(
        mode for mode in ("plan", "default", "auto-edit") if mode in help_text
    )
    return GigaCodeCapabilities(
        executable=executable,
        version=version.strip() or "unknown",
        model_selection="--model" in help_text,
        system_prompt="--system-prompt" in help_text,
        prompt="--prompt" in help_text,
        approval_modes=approval_modes,
        allowed_tools="--allowed-tools" in help_text,
        sandbox="--sandbox" in help_text,
        stream_input="--input-format" in help_text and "stream-json" in help_text,
        json_output="--output-format" in help_text and "json" in help_text,
        stream_output="--output-format" in help_text and "stream-json" in help_text,
        agent_isolation=all(
            flag in help_text
            for flag in (
                "--extensions",
                "--max-session-turns",
                "--core-tools",
                "--allowed-mcp-server-names",
                "--exclude-tools",
            )
        ),
        mcp="mcp" in mcp_help_text.lower(),
    )


def find_gigacode_executable(
    configured: str,
    *,
    home: Path,
    path: str | None = None,
) -> Path:
    if configured != "auto":
        explicit = Path(configured).resolve(strict=False)
        if explicit.is_file() and os.access(explicit, os.X_OK):
            return explicit
        raise AgentRuntimeError(
            ErrorCode.CAPABILITY_UNAVAILABLE,
            f"Configured GigaCode executable is unavailable: {explicit}",
            details={"executable": str(explicit)},
        )

    discovered = shutil.which("gigacode", path=path)
    if discovered:
        return Path(discovered).resolve(strict=True)
    fallback = (home / ".gigacode" / "bin" / "gigacode").resolve(strict=False)
    if fallback.is_file() and os.access(fallback, os.X_OK):
        return fallback
    raise AgentRuntimeError(
        ErrorCode.CAPABILITY_UNAVAILABLE,
        "GigaCode executable was not found",
        details={"searched": ["PATH", str(fallback)]},
    )
