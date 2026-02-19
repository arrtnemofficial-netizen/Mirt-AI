"""Startup and smoke checks with explicit status/severity.

These checks are intentionally separated from FastAPI startup hot path.
Use them via:
- API endpoint (`/health/smoke`)
- CLI (`python -m src.server.startup_checks`)
- CI pre-deploy job
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class CheckStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


class CheckSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"


@dataclass(slots=True)
class CheckResult:
    name: str
    status: CheckStatus
    severity: CheckSeverity
    details: str


@dataclass(slots=True)
class SmokeCheckReport:
    status: str
    checks: list[CheckResult]

    @property
    def critical_failures(self) -> list[CheckResult]:
        return [
            item
            for item in self.checks
            if item.severity == CheckSeverity.CRITICAL and item.status == CheckStatus.FAIL
        ]

    @property
    def warnings(self) -> list[CheckResult]:
        return [item for item in self.checks if item.status == CheckStatus.WARN]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checks": [asdict(item) for item in self.checks],
            "summary": {
                "total": len(self.checks),
                "critical_failures": len(self.critical_failures),
                "warnings": len(self.warnings),
            },
        }


def run_state_router_checkpointer_compatibility() -> list[CheckResult]:
    """Validate compatibility of state/router/checkpointer integration."""
    results: list[CheckResult] = []

    try:
        from src.agents.langgraph.state import create_initial_state

        state = create_initial_state(session_id="SMOKE_CHECK")
    except Exception as exc:
        return [
            CheckResult(
                name="state_init",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                details=f"Failed to create initial state: {type(exc).__name__}",
            )
        ]

    try:
        state["smoke_check_key"] = "ok"
        results.append(
            CheckResult(
                name="state_mutability",
                status=CheckStatus.PASS,
                severity=CheckSeverity.CRITICAL,
                details="State supports dict assignment.",
            )
        )
    except TypeError as exc:
        results.append(
            CheckResult(
                name="state_mutability",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                details=f"State does not support dict assignment: {exc}",
            )
        )

    if hasattr(state, "step_number"):
        results.append(
            CheckResult(
                name="state_schema",
                status=CheckStatus.PASS,
                severity=CheckSeverity.CRITICAL,
                details="State contains required field 'step_number'.",
            )
        )
    else:
        results.append(
            CheckResult(
                name="state_schema",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                details="State missing required field 'step_number'.",
            )
        )

    try:
        from src.agents.langgraph.routers.base import to_schema

        _ = to_schema(state)
        results.append(
            CheckResult(
                name="router_to_schema",
                status=CheckStatus.PASS,
                severity=CheckSeverity.CRITICAL,
                details="Router conversion to_schema(state) succeeded.",
            )
        )
    except Exception as exc:
        results.append(
            CheckResult(
                name="router_to_schema",
                status=CheckStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                details=f"Router conversion failed: {type(exc).__name__}",
            )
        )

    try:
        from src.agents.langgraph.checkpointer import get_checkpointer

        _ = get_checkpointer()
        results.append(
            CheckResult(
                name="checkpointer_init",
                status=CheckStatus.PASS,
                severity=CheckSeverity.WARNING,
                details="Checkpointer initialized successfully.",
            )
        )
    except Exception as exc:
        results.append(
            CheckResult(
                name="checkpointer_init",
                status=CheckStatus.WARN,
                severity=CheckSeverity.WARNING,
                details=f"Checkpointer init warning: {type(exc).__name__}",
            )
        )

    return results


def run_smoke_checks() -> SmokeCheckReport:
    checks = run_state_router_checkpointer_compatibility()

    if any(
        item.status == CheckStatus.FAIL and item.severity == CheckSeverity.CRITICAL
        for item in checks
    ):
        status = "failed"
    elif any(item.status == CheckStatus.WARN for item in checks):
        status = "warning"
    else:
        status = "ok"

    return SmokeCheckReport(status=status, checks=checks)


def _print_report(report: SmokeCheckReport) -> None:
    print(f"smoke_status={report.status}")
    for item in report.checks:
        print(
            f"- {item.name}: status={item.status} severity={item.severity} details={item.details}"
        )
    print(
        "summary: "
        f"critical_failures={len(report.critical_failures)} warnings={len(report.warnings)}"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run startup smoke checks")
    parser.add_argument(
        "--fail-on-critical",
        action="store_true",
        help="Return exit code 1 only when critical checks fail.",
    )
    return parser.parse_args()


def main() -> int:
    _ = asyncio.get_event_loop_policy()
    args = _parse_args()
    report = run_smoke_checks()
    _print_report(report)

    if args.fail_on_critical and report.critical_failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
