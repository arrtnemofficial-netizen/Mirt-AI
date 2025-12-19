#!/usr/bin/env python
"""
Run Memory System Tests.
========================

Usage:
    python scripts/run_memory_tests.py         # Run all memory tests
    python scripts/run_memory_tests.py --fast  # Run only fast tests (no async)
    python scripts/run_memory_tests.py --unit  # Run only unit tests
    python scripts/run_memory_tests.py --e2e   # Run E2E tests

Coverage:
    python scripts/run_memory_tests.py --cov   # Run with coverage
"""

import argparse
import subprocess
import sys


def run_tests(args: argparse.Namespace) -> int:
    """Run memory tests with pytest."""

    cmd = ["python", "-m", "pytest"]

    # Select test files
    if args.unit:
        cmd.extend(
            [
                "tests/unit/test_memory_models.py",
                "tests/unit/test_memory_service.py",
            ]
        )
    elif args.e2e:
        cmd.extend(
            [
                "tests/integration/test_memory_integration.py",
                "tests/integration/test_memory_e2e.py",
            ]
        )
    else:
        # All memory tests
        cmd.extend(
            [
                "tests/unit/test_memory_models.py",
                "tests/unit/test_memory_service.py",
                "tests/integration/test_memory_integration.py",
                "tests/integration/test_memory_e2e.py",
            ]
        )

    # Options
    cmd.append("-v")  # Verbose

    if args.fast:
        cmd.append("-m")
        cmd.append("not asyncio")  # Skip async tests

    if args.cov:
        cmd.extend(
            [
                "--cov=src.agents.pydantic.memory_models",
                "--cov=src.agents.pydantic.memory_agent",
                "--cov=src.services.memory_service",
                "--cov=src.agents.langgraph.nodes.memory",
                "--cov-report=html",
                "--cov-report=term-missing",
            ]
        )

    if args.fail_fast:
        cmd.append("-x")  # Stop on first failure

    print(f"Running: {' '.join(cmd)}")
    print("-" * 60)

    return subprocess.call(cmd)


def main():
    parser = argparse.ArgumentParser(description="Run Memory System Tests")

    parser.add_argument(
        "--fast",
        action="store_true",
        help="Run only fast tests (skip async)",
    )
    parser.add_argument(
        "--unit",
        action="store_true",
        help="Run only unit tests",
    )
    parser.add_argument(
        "--e2e",
        action="store_true",
        help="Run only E2E/integration tests",
    )
    parser.add_argument(
        "--cov",
        action="store_true",
        help="Run with coverage report",
    )
    parser.add_argument(
        "--fail-fast",
        "-x",
        action="store_true",
        help="Stop on first failure",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("🧪 MIRT Memory System Test Suite")
    print("=" * 60)
    print()
    print("Test categories:")
    print("  • Unit Tests: Memory models, service, agent")
    print("  • Integration: Nodes, graph flow")
    print("  • E2E: Full production safety")
    print()
    print("Total tests: 100")
    print()

    result = run_tests(args)

    print()
    print("=" * 60)
    if result == 0:
        print("✅ ALL TESTS PASSED!")
    else:
        print("❌ SOME TESTS FAILED!")
    print("=" * 60)

    return result


if __name__ == "__main__":
    sys.exit(main())
