#!/usr/bin/env python3
"""Локальний регресійний gate із фокусом на AI-шар.

Запускає стабільний набір перевірок, відокремлює інфраструктурні обмеження
від дефектів коду та підтримує окремий режим `--ai-layer-only`.
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


def _run(command: list[str], *, timeout_s: int = 180) -> tuple[int, str]:
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


def _tail(text: str, n: int = 12) -> str:
    return "\n".join(text.splitlines()[-n:]) if text else "No output"


def check_python_version(*, strict: bool) -> CheckResult:
    major, minor = sys.version_info[:2]
    if (major, minor) >= (3, 11):
        status = "pass"
    else:
        status = "fail" if strict else "warn"
    return CheckResult(
        name="python-version",
        status=status,
        command="python --version",
        details=f"Detected Python {major}.{minor}; required >= 3.11",
    )


def check_manifest_alignment() -> CheckResult:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    critical = [
        "pydantic-ai",
        "langgraph",
        "openai",
        "pydantic",
        "fastapi",
        "pytest",
        "pytest-asyncio",
    ]
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

    return CheckResult(
        name="dependency-manifest-alignment",
        status="pass" if not mismatches else "fail",
        command="internal-check",
        details="OK" if not mismatches else "; ".join(mismatches),
    )


def run_command_check(name: str, command: list[str], *, required: bool = True) -> CheckResult:
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

    env_limited_markers = [
        "No module named 'pytest_asyncio'",
        "Cannot connect to proxy",
        "No matching distribution found",
        "cannot import name 'UTC' from 'datetime'",
    ]
    if any(marker in out for marker in env_limited_markers):
        return CheckResult(name=name, status="warn", command=" ".join(command), details=_tail(out))

    return CheckResult(
        name=name,
        status="fail" if required else "warn",
        command=" ".join(command),
        details=_tail(out),
    )


def build_ai_layer_checks() -> list[CheckResult]:
    checks = [
        run_command_check("ai-smell-comments", ["python", "scripts/check_ai_smell_comments.py"], required=True),
        run_command_check(
            "pydantic-ai-import-smoke",
            ["python", "-c", "from src.agents.pydantic.shared.model_factory import build_pydantic_model; print('ok')"],
            required=True,
        ),
        run_command_check(
            "langgraph-state-import-smoke",
            ["python", "-c", "from src.agents.langgraph.state import create_initial_state; create_initial_state(session_id='SMOKE')"],
            required=True,
        ),
        run_command_check("prompt-compliance", ["pytest", "-q", "tests/unit/test_prompt_compliance.py"], required=True),
        run_command_check("prompt-contract-snapshot", ["pytest", "-q", "tests/unit/test_prompt_contract_snapshot.py"], required=True),
        run_command_check("vision-contract", ["pytest", "-q", "tests/test_vision_contract.py"], required=True),
    ]
    return checks


def build_general_checks(*, quick: bool) -> list[CheckResult]:
    checks = [
        run_command_check("ruff", ["ruff", "check", "src", "tests"], required=False),
    ]
    if not quick:
        checks.extend(
            [
                run_command_check("smoke-graph", ["pytest", "-q", "tests/smoke/test_graph_builds.py"], required=True),
                run_command_check(
                    "critical-regression",
                    [
                        "pytest",
                        "-q",
                        "tests/unit/test_payment_node.py",
                        "tests/scenario/test_state5_scenarios.py",
                    ],
                    required=True,
                ),
            ]
        )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local regression gate checks")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    parser.add_argument("--quick", action="store_true", help="Skip heavy non-AI checks")
    parser.add_argument("--strict-python", action="store_true", help="Fail when Python < 3.11")
    parser.add_argument("--ai-layer-only", action="store_true", help="Run only AI-layer quality gates")
    args = parser.parse_args()

    results: list[CheckResult] = [check_python_version(strict=args.strict_python), check_manifest_alignment()]

    if args.ai_layer_only:
        results.extend(build_ai_layer_checks())
    else:
        results.extend(build_ai_layer_checks())
        results.extend(build_general_checks(quick=args.quick))

    if args.json:
        print(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2))
    else:
        for item in results:
            icon = {"pass": "✅", "warn": "⚠️", "fail": "❌"}[item.status]
            print(f"{icon} {item.name}: {item.details}")
            print(f"   $ {item.command}")

    return 1 if any(r.status == "fail" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
