"""Module entry point with a dependency-light version fast path."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from .version import __version__


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["--version"]:
        print(f"agent-runtime {__version__}")
        return 0

    from .cli import main as cli_main

    return cli_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
