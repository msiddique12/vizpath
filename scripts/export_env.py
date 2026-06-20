from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.check_env import parse_env_file  # noqa: E402


def shell_exports(values: dict[str, str], *, preserve_existing: bool) -> list[str]:
    """Return POSIX shell export statements for parsed env values."""
    exports: list[str] = []
    for key in sorted(values):
        if preserve_existing and key in os.environ:
            continue
        exports.append(f"export {key}={shlex.quote(values[key])}")
    return exports


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit shell-safe exports from a .env file")
    parser.add_argument("--env", default=".env", help="Path to .env file")
    parser.add_argument(
        "--preserve-existing",
        action="store_true",
        help="Do not overwrite variables already present in the current environment",
    )
    args = parser.parse_args()

    values = parse_env_file(Path(args.env))
    for line in shell_exports(values, preserve_existing=args.preserve_existing):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
