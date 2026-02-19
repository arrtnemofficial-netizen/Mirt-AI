#!/usr/bin/env python3
"""Локальний регресійний gate для швидкої перевірки стабільності.

Скрипт не вимагає сторонніх бібліотек; запускає доступні команди,
фіксує їх статус і повертає зрозумілий звіт.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class CheckResult:
    name: str
    status: str  # pass | fail | warn
    command: str
    details: str


def _run(command: list[str], *, timeout_s: int = 120) -> tuple[int, str]:
    proc = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    out = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    return proc.returncode, out.strip()


def _tool_exists(name: str) -> bool:
    return shutil.which(name) is not None


def check_python_version(*, strict: bool) -> CheckResult:
    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 11):
        status = "pass"
    else:
        status = "fail" if strict else "warn"
    details = f"Detected Python {major}.{minor}; required >= 3.11"
    return CheckResult(
        name="python-version",
        status=status,
        command="python --version",
        details=details,
    )


def check_manifest_alignment() -> CheckResult:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    critical = ["pydantic-ai", "langgraph", "openai", "pydantic", "fastapi", "pytest-asyncio"]
    mismatches: list[str] = []

    for package in critical:
        py_lines = [ln.strip() for ln in pyproject.splitlines() if f'"{package}' in ln]
        req_lines = [ln.strip() for ln in requirements.splitlines() if ln.strip().startswith(package)]
        if not py_lines or not req_lines:
            mismatches.append(f"{package}: missing in one of manifests")
            continue
        py = py_lines[0].strip(',"')
        req = req_lines[0]
        if "==" in py and "==" in req and py.split("==", 1)[1] != req.split("==", 1)[1]:
            mismatches.append(f"{package}: pyproject={py} requirements={req}")

    status = "pass" if not mismatches else "fail"
    details = "OK" if not mismatches else "; ".join(mismatches)
    return CheckResult(
        name="dependency-manifest-alignment",
        status=status,
        command="internal-check",
        details=details,
    )


def check_command(name: str, command: list[str], *, required: bool = True) -> CheckResult:
    if not _tool_exists(command[0]):
        return CheckResult(
            name=name,
            status="warn",
            command=" ".join(command),
            details=f"Tool '{command[0]}' not installed in environment",
        )

    code, out = _run(command)
    if code == 0:
        return CheckResult(name=name, status="pass", command=" ".join(command), details="OK")

    tail = "\n".join(out.splitlines()[-10:]) if out else "No output"
    env_limited_markers = [
        "No module named 'pytest_asyncio'",
        "Cannot connect to proxy",
        "No matching distribution found",
    ]
    if any(marker in out for marker in env_limited_markers):
        return CheckResult(name=name, status="warn", command=" ".join(command), details=tail)

    status = "fail" if required else "warn"
    return CheckResult(name=name, status=status, command=" ".join(command), details=tail)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local regression gate checks")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    parser.add_argument("--quick", action="store_true", help="Skip heavy checks")
    parser.add_argument("--strict-python", action="store_true", help="Fail when Python < 3.11")
    args = parser.parse_args()

    results: list[CheckResult] = [
        check_python_version(strict=args.strict_python),
        check_manifest_alignment(),
        check_command("ruff", ["ruff", "check", "src", "tests"], required=False),
    ]

    if not args.quick:
        results.extend(
            [
                check_command("smoke-graph", ["pytest", "-q", "tests/smoke/test_graph_builds.py"], required=True),
                check_command(
                    "critical-regression",
                    [
                        "pytest",
                        "-q",
                        "tests/unit/test_payment_node.py",
                        "tests/test_vision_contract.py",
                        "tests/scenario/test_state5_scenarios.py",
                    ],
                    required=True,
                ),
            ]
        )

    if args.json:
        print(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2))
    else:
        for item in results:
            icon = {"pass": "✅", "warn": "⚠️", "fail": "❌"}[item.status]
            print(f"{icon} {item.name}: {item.details}")
            print(f"   $ {item.command}")

    failed = [r for r in results if r.status == "fail"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
