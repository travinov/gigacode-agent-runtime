"""Command-line entry point.

The complete command tree is added after the runtime core. Keeping this module
dependency-light makes package and installer diagnostics available early.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-runtime",
        description="Local multi-agent runtime for GigaCode CLI",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
