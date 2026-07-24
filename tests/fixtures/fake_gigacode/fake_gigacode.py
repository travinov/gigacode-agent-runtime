#!/usr/bin/env python3
"""Deterministic, network-free stand-in for the corporate GigaCode CLI."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

_VALUE_OPTIONS = {
    "--model",
    "--system-prompt",
    "--approval-mode",
    "--allowed-tools",
    "--input-format",
    "--output-format",
}
_SENSITIVE_OPTIONS = {"--system-prompt"}


def _load_profile() -> dict[str, Any]:
    path = os.environ.get("FAKE_GIGACODE_PROFILE")
    if not path:
        return {"delay_seconds": 0, "exit_code": 0, "result": {"summary": "default"}}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _option_value(arguments: list[str], name: str, default: str) -> str:
    try:
        index = arguments.index(name)
    except ValueError:
        return default
    if index + 1 >= len(arguments):
        return default
    return arguments[index + 1]


def _sanitized_arguments(arguments: list[str]) -> list[str]:
    sanitized: list[str] = []
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in _VALUE_OPTIONS and index + 1 < len(arguments):
            sanitized.append(argument)
            value = arguments[index + 1]
            sanitized.append("<redacted>" if argument in _SENSITIVE_OPTIONS else value)
            index += 2
            continue
        if argument.startswith("-") or argument in {"mcp", "list", "add"}:
            sanitized.append(argument)
        else:
            sanitized.append("<prompt>")
        index += 1
    return sanitized


def _append_trace(record: dict[str, object]) -> None:
    trace_path = os.environ.get("FAKE_GIGACODE_TRACE_FILE")
    if not trace_path:
        return
    path = Path(trace_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    try:
        os.write(
            descriptor,
            (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode(),
        )
    finally:
        os.close(descriptor)


def _next_attempt() -> int:
    state_path = os.environ.get("FAKE_GIGACODE_STATE_FILE")
    if not state_path:
        return 1
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        content = handle.read().strip()
        attempt = int(content) + 1 if content else 1
        handle.seek(0)
        handle.truncate()
        handle.write(str(attempt))
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return attempt


def _help(profile: dict[str, Any]) -> str:
    lines = [
        "Usage: qwen [options] [prompt]",
        "  --model <model>",
        "  --system-prompt <prompt>",
        "  --approval-mode <plan|default|auto-edit>",
        "  --allowed-tools <tools>",
        "  --sandbox",
        "  --input-format <text|stream-json>",
        "  --output-format <text|json|stream-json>",
    ]
    omitted = set(profile.get("omit_help_flags", []))
    return "\n".join(line for line in lines if not any(flag in line for flag in omitted))


def _emit_result(profile: dict[str, Any], output_format: str) -> None:
    if profile.get("no_output"):
        return
    if profile.get("invalid_json"):
        print("{invalid-json", flush=True)
        return
    result = profile.get("result", {"summary": "fake success"})
    if output_format == "stream-json":
        print(
            json.dumps(
                {"type": "message", "role": "assistant", "content": "fake response"},
                separators=(",", ":"),
            ),
            flush=True,
        )
        print(
            json.dumps({"type": "result", "result": result}, separators=(",", ":")),
            flush=True,
        )
    elif output_format == "json":
        print(json.dumps({"result": result}, separators=(",", ":")), flush=True)
    else:
        print(json.dumps(result, separators=(",", ":")), flush=True)


def main() -> int:
    arguments = sys.argv[1:]
    profile = _load_profile()
    started = time.monotonic()
    stdin_text = ""
    exit_code = 0
    try:
        if arguments == ["--version"]:
            print("26.5.17-fake")
            return 0
        if arguments == ["--help"]:
            print(_help(profile))
            return 0
        if arguments[:2] == ["mcp", "--help"]:
            print("Usage: qwen mcp <add|remove|list>")
            return 0
        if arguments[:2] == ["mcp", "list"]:
            print("gigacode-agent-runtime: Connected")
            return 0

        stdin_text = sys.stdin.read()
        if profile.get("ignore_sigterm"):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        delay = float(profile.get("delay_seconds", 0))
        if delay:
            time.sleep(delay)

        attempt = _next_attempt() if "fail_attempts" in profile else 1
        fail_attempts = int(profile.get("fail_attempts", 0))
        if attempt <= fail_attempts:
            exit_code = int(profile.get("exit_code", 75))
            print("transient fake failure", file=sys.stderr, flush=True)
            return exit_code

        stderr = profile.get("stderr")
        if stderr:
            print(str(stderr), file=sys.stderr, flush=True)
        exit_code = 0 if fail_attempts else int(profile.get("exit_code", 0))
        if exit_code == 0:
            _emit_result(profile, _option_value(arguments, "--output-format", "text"))
        return exit_code
    finally:
        _append_trace(
            {
                "argv": _sanitized_arguments(arguments),
                "end_monotonic": time.monotonic(),
                "exit_code": exit_code,
                "input_sha256": hashlib.sha256(stdin_text.encode()).hexdigest(),
                "pgid": os.getpgid(0),
                "pid": os.getpid(),
                "start_monotonic": started,
            }
        )
