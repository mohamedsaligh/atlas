"""Cross-platform task runner.

Mirrors the Make targets so Windows / Linux / macOS contributors run
the same gates locally and against CI. No external dependency — invoke
with the project's Python interpreter:

    python tasks.py check     # full CI gate
    python tasks.py lint
    python tasks.py typecheck
    python tasks.py test
    python tasks.py cov
    python tasks.py cov-api
    python tasks.py format
    python tasks.py sbom

Each target shells out via subprocess; failures propagate the
underlying exit code. Use ``-h`` to list available targets.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from collections.abc import Callable

PY = sys.executable

TARGETS: dict[str, list[str]] = {
    "lint": [
        f"{PY} -m ruff check src tests tasks.py",
        f"{PY} -m ruff format --check src tests tasks.py",
    ],
    "format": [
        f"{PY} -m ruff format src tests tasks.py",
        f"{PY} -m ruff check --fix src tests tasks.py",
    ],
    "typecheck": [
        f"{PY} -m mypy src/atlas",
    ],
    "test": [
        f"{PY} -m pytest",
    ],
    "cov": [
        f"{PY} -m pytest --cov --cov-report=term-missing --cov-report=xml",
    ],
    "cov-api": [
        f"{PY} -m pytest tests/api --cov=src/atlas/api --cov-report=term-missing --cov-fail-under=85",
    ],
    "sbom": [
        f"{PY} -m cyclonedx_py environment --output-file sbom.cdx.json",
    ],
    "docker": [
        "docker build -t atlas-lite:dev .",
    ],
}

CHECK_ORDER = ["lint", "typecheck", "cov", "cov-api"]


def _run(cmd: str) -> int:
    print(f"$ {cmd}", flush=True)
    args = shlex.split(cmd, posix=sys.platform != "win32")
    return subprocess.run(args, check=False).returncode


def _runner(name: str) -> Callable[[], int]:
    def fn() -> int:
        for cmd in TARGETS[name]:
            rc = _run(cmd)
            if rc != 0:
                return rc
        return 0

    return fn


def _check() -> int:
    for name in CHECK_ORDER:
        rc = _runner(name)()
        if rc != 0:
            print(f"check: {name} failed (rc={rc})", file=sys.stderr)
            return rc
    print("check: all gates passed", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    available = [*sorted(TARGETS), "check"]
    parser.add_argument("target", choices=available, help="Task to run.")
    args = parser.parse_args(argv)
    if args.target == "check":
        return _check()
    return _runner(args.target)()


if __name__ == "__main__":
    raise SystemExit(main())
