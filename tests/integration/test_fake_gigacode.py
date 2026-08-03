from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from tests.helpers.fake_gigacode import FakeGigaCode


def _fake(tmp_path: Path, profile: str = "success") -> FakeGigaCode:
    return FakeGigaCode(
        profile=profile,
        trace_file=tmp_path / "trace.jsonl",
        state_file=tmp_path / "state.json",
    )


def test_fake_reports_version_and_qwen_compatible_help(tmp_path: Path) -> None:
    fake = _fake(tmp_path)

    version = subprocess.run(
        [fake.executable, "--version"],
        env=fake.environment(),
        capture_output=True,
        text=True,
        check=True,
    )
    help_result = subprocess.run(
        [fake.executable, "--help"],
        env=fake.environment(),
        capture_output=True,
        text=True,
        check=True,
    )

    assert version.stdout.strip() == "26.5.17-fake"
    assert "--output-format" in help_result.stdout
    assert "--input-format" in help_result.stdout
    assert "--sandbox" in help_result.stdout


def test_fake_emits_stream_json_and_redacts_prompt_from_trace(tmp_path: Path) -> None:
    fake = _fake(tmp_path)
    secret_prompt = "confidential prompt body"

    completed = subprocess.run(
        [
            fake.executable,
            "--model",
            "code-model-id",
            "--prompt",
            secret_prompt,
            "--output-format",
            "stream-json",
        ],
        env=fake.environment(),
        capture_output=True,
        text=True,
        check=True,
    )

    events = [json.loads(line) for line in completed.stdout.splitlines()]
    trace = fake.trace_file.read_text()
    assert events[-1]["type"] == "result"
    assert json.loads(events[-1]["result"].split("\n")[3])["approved"] is True
    assert secret_prompt not in trace
    assert "input_sha256" in trace


def test_delayed_fake_processes_overlap(tmp_path: Path) -> None:
    fake = _fake(tmp_path, "delayed")
    environment = fake.environment()
    command = [
        fake.executable,
        "--prompt",
        "safe prompt",
        "--output-format",
        "stream-json",
    ]

    started = time.monotonic()
    first = subprocess.Popen(
        command,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    second = subprocess.Popen(
        command,
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    first.communicate(timeout=3)
    second.communicate(timeout=3)
    elapsed = time.monotonic() - started

    assert first.returncode == 0
    assert second.returncode == 0
    traces = [json.loads(line) for line in fake.trace_file.read_text().splitlines()]
    starts = [float(trace["start_monotonic"]) for trace in traces]
    ends = [float(trace["end_monotonic"]) for trace in traces]
    assert max(starts) < min(ends)
    assert elapsed < 1.5


def test_transient_profile_fails_once_then_succeeds(tmp_path: Path) -> None:
    fake = _fake(tmp_path, "transient")
    command = [fake.executable, "--output-format", "json", "safe prompt"]

    first = subprocess.run(
        command,
        env=fake.environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    second = subprocess.run(
        command,
        env=fake.environment(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert first.returncode == 75
    assert second.returncode == 0
