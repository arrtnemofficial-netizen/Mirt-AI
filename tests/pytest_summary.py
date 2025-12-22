"""Pytest plugin for production-grade test summary with root cause analysis.

This plugin provides:
- Beautiful summary statistics
- Slowest tests identification
- Grouping by markers
- Root cause analysis for failed tests
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import pytest


class TestSummaryPlugin:
    """Pytest plugin for enhanced test reporting."""

    def __init__(self, config: pytest.Config):
        self.config = config
        self.test_results: list[dict[str, Any]] = []
        self.marker_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"passed": 0, "failed": 0, "skipped": 0})

    @pytest.hookimpl(tryfirst=True, hookwrapper=True)
    def pytest_runtest_makereport(self, item: pytest.Item, call: Any) -> Any:
        """Capture test results for summary."""
        outcome = yield
        report = outcome.get_result()

        if report.when == "call":
            markers = [marker.name for marker in item.iter_markers()]
            self.test_results.append(
                {
                    "name": item.nodeid,
                    "outcome": report.outcome,
                    "duration": getattr(report, "duration", 0.0),
                    "markers": markers,
                    "longrepr": str(report.longrepr) if hasattr(report, "longrepr") else None,
                }
            )

            # Update marker statistics
            for marker in markers:
                self.marker_stats[marker][report.outcome] += 1

    def pytest_terminal_summary(self, terminalreporter: Any, exitstatus: int, config: pytest.Config) -> None:
        """Print enhanced summary at the end of test run."""
        if not self.test_results:
            return

        terminalreporter.write_sep("=", "TEST SUMMARY REPORT", green=True)

        # Overall statistics
        total = len(self.test_results)
        passed = sum(1 for r in self.test_results if r["outcome"] == "passed")
        failed = sum(1 for r in self.test_results if r["outcome"] == "failed")
        skipped = sum(1 for r in self.test_results if r["outcome"] == "skipped")

        terminalreporter.write_line(f"\n📊 Overall Statistics:")
        terminalreporter.write_line(f"   Total:   {total}")
        terminalreporter.write_line(f"   Passed:  {passed} ✅" if passed > 0 else f"   Passed:  {passed}")
        terminalreporter.write_line(f"   Failed:  {failed} ❌" if failed > 0 else f"   Failed:  {failed}")
        terminalreporter.write_line(f"   Skipped: {skipped} ⏭️" if skipped > 0 else f"   Skipped: {skipped}")

        # Slowest tests
        slow_tests = sorted(
            [r for r in self.test_results if r["duration"] > 0.5],
            key=lambda x: x["duration"],
            reverse=True,
        )[:10]

        if slow_tests:
            terminalreporter.write_line(f"\n⏱️  Slowest Tests (>0.5s):")
            for i, test in enumerate(slow_tests, 1):
                duration = test["duration"]
                color = "yellow" if duration > 2.0 else "white"
                terminalreporter.write_line(
                    f"   {i:2d}. {duration:6.2f}s - {test['name']}",
                    **{color: True},
                )

        # Marker statistics
        if self.marker_stats:
            terminalreporter.write_line(f"\n🏷️  Statistics by Marker:")
            for marker, stats in sorted(self.marker_stats.items()):
                total_marker = sum(stats.values())
                if total_marker > 0:
                    terminalreporter.write_line(
                        f"   {marker:20s}: {stats['passed']:3d} passed, "
                        f"{stats['failed']:3d} failed, {stats['skipped']:3d} skipped "
                        f"(total: {total_marker})"
                    )

        # Failed tests with root cause analysis
        failed_tests = [r for r in self.test_results if r["outcome"] == "failed"]
        if failed_tests:
            terminalreporter.write_sep("-", "FAILED TESTS ANALYSIS", red=True)
            for test in failed_tests:
                terminalreporter.write_line(f"\n❌ {test['name']}")
                if test["longrepr"]:
                    # Extract root cause if present
                    root_cause_match = re.search(r"\[ROOT_CAUSE:\s*([^\]]+)\]", test["longrepr"])
                    if root_cause_match:
                        root_cause = root_cause_match.group(1)
                        terminalreporter.write_line(f"   [ROOT_CAUSE: {root_cause}]", red=True)
                    else:
                        # Try to classify from error message
                        error_lines = test["longrepr"].split("\n")[:5]
                        terminalreporter.write_line("   Error preview:")
                        for line in error_lines[:3]:
                            terminalreporter.write_line(f"      {line[:100]}")

        terminalreporter.write_sep("=", "", green=True)


def pytest_configure(config: pytest.Config) -> None:
    """Register the plugin."""
    config.pluginmanager.register(TestSummaryPlugin(config), "test_summary")

