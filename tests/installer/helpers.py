from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

ROOT = Path(__file__).parents[2]


def make_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def synthetic_release(tmp_path: Path) -> tuple[Path, Path, Path]:
    release = tmp_path / "release with spaces"
    shutil.copytree(ROOT / "installer", release / "installer")
    (release / "scripts").mkdir(parents=True)
    (release / "scripts" / "release_tool.py").write_text("# synthetic\n")
    for minor in ("311", "312", "313", "314"):
        lock = release / "requirements" / f"runtime-py{minor}.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("# synthetic lock\n")
        (release / "wheelhouse" / f"py{minor}").mkdir(parents=True)
    common = release / "wheelhouse" / "common"
    common.mkdir(parents=True)
    (common / "gigacode_agent_runtime-1.0.0-py3-none-any.whl").write_bytes(
        b"synthetic"
    )

    fake_python = tmp_path / "tools with spaces" / "python3.14"
    make_executable(
        fake_python,
        r"""#!/bin/sh
set -eu
if [ "${1:-}" = "-c" ]; then
  if [ "$#" -eq 2 ]; then
    echo 314
  else
    /usr/bin/shasum -a 256 "$3" | /usr/bin/awk '{print $1}'
  fi
  exit 0
fi
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "venv" ]; then
  target=$3
  mkdir -p "$target/bin"
  cp "$0" "$target/bin/python"
  cat > "$target/bin/agent-runtime" <<EOF
#!/bin/sh
set -eu
venv_python='$target/bin/python'
if [ ! -x "\$venv_python" ]; then
  echo "bad interpreter: \$venv_python: No such file or directory" >&2
  exit 126
fi
case "\${1:-}" in
  --version) echo "agent-runtime 1.0.0" ;;
  diagnose) echo '{"status":"ok","checks":[]}' ;;
  mcp-serve) exit 0 ;;
  *) exit 0 ;;
esac
EOF
  chmod 755 "$target/bin/agent-runtime"
  exit 0
fi
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "pip" ]; then
  exit 0
fi
exit 0
""",
    )

    fake_gigacode = tmp_path / "tools with spaces" / "gigacode"
    make_executable(
        fake_gigacode,
        """#!/bin/sh
set -eu
if [ "${1:-}" = "mcp" ] && [ "${2:-}" = "list" ]; then
  echo "gigacode-agent-runtime: Connected"
fi
exit 0
""",
    )
    return release, fake_python, fake_gigacode


def installer_environment(
    tmp_path: Path,
    fake_python: Path,
    fake_gigacode: Path,
) -> dict[str, str]:
    home = tmp_path / "corporate home with spaces"
    home.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "GAR_PYTHON": str(fake_python),
            "GIGACODE_BIN": str(fake_gigacode),
            "GAR_TEST_SYSTEM": "Darwin",
            "GAR_TEST_MACHINE": "x86_64",
            "GIGACODE_AGENT_RUNTIME_INSTALL_ROOT": str(
                home / "Library" / "Application Support" / "GigaCode Agent Runtime"
            ),
            "GIGACODE_AGENT_RUNTIME_BIN_DIR": str(home / "bin with spaces"),
            "GIGACODE_AGENT_RUNTIME_DATA_DIR": str(
                home / ".gigacode" / "agent-runtime"
            ),
        }
    )
    return environment
