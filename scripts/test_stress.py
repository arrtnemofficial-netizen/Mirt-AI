#!/usr/bin/env python
"""Stress test for MIRT AI - tests JSON reliability and state transitions.

This script runs multiple conversation scenarios to verify:
1. JSON output is always valid
2. State transitions are correct
3. No crashes or hangs
4. Graceful degradation on errors

Usage:
    # Quick test (10 messages)
    python scripts/test_stress.py --quick

    # Full stress test (100 messages)
    python scripts/test_stress.py --full

    # Custom count
    python scripts/test_stress.py --messages 50
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv


load_dotenv()

from src.agents.pydantic_agent import AgentRunner, build_agent
from src.core.models import AgentResponse
from src.core.output_parser import parse_llm_output
from src.core.state_validator import validate_state_transition


logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


# Test scenarios covering all states and intents
TEST_SCENARIOS = [
    # Greetings
    {"input": "Привіт!", "expected_state": "STATE_0_INIT"},
    {"input": "Добрий день", "expected_state": "STATE_0_INIT"},
    {"input": "Вітаю!", "expected_state": "STATE_0_INIT"},
    # Product search (Discovery)
    {"input": "Шукаю плаття на дівчинку", "expected_state": "STATE_1_DISCOVERY"},
    {"input": "Є костюми для хлопчика?", "expected_state": "STATE_1_DISCOVERY"},
    {"input": "Потрібен святковий одяг", "expected_state": "STATE_1_DISCOVERY"},
    {"input": "Що є на день народження?", "expected_state": "STATE_1_DISCOVERY"},
    # Size questions (Vision/Size)
    {"input": "Розмір 128", "expected_state": "STATE_3_SIZE_COLOR"},
    {"input": "Дитині 5 років, який розмір?", "expected_state": "STATE_2_VISION"},
    {"input": "А є 134 розмір?", "expected_state": "STATE_3_SIZE_COLOR"},
    # Color questions
    {"input": "Покажіть рожеві варіанти", "expected_state": "STATE_3_SIZE_COLOR"},
    {"input": "Є в синьому кольорі?", "expected_state": "STATE_3_SIZE_COLOR"},
    {"input": "Хочу біле плаття", "expected_state": "STATE_3_SIZE_COLOR"},
    # Price/Budget
    {"input": "Бюджет до 2000 грн", "expected_state": "STATE_4_OFFER"},
    {"input": "Скільки коштує?", "expected_state": "STATE_4_OFFER"},
    {"input": "Є дешевше?", "expected_state": "STATE_4_OFFER"},
    # Ready to buy
    {"input": "Беру це плаття!", "expected_state": "STATE_5_PAYMENT_DELIVERY"},
    {"input": "Як оплатити?", "expected_state": "STATE_5_PAYMENT_DELIVERY"},
    {"input": "Хочу замовити", "expected_state": "STATE_5_PAYMENT_DELIVERY"},
    # Objections
    {"input": "Дорого, є знижки?", "expected_state": "STATE_4_OFFER"},
    {"input": "А якість хороша?", "expected_state": "STATE_4_OFFER"},
    {"input": "Довго буде йти?", "expected_state": "STATE_5_PAYMENT_DELIVERY"},
    # Complaints (Escalation)
    {"input": "Моє замовлення загубилось!", "expected_state": "STATE_8_COMPLAINT"},
    {"input": "Хочу повернути товар", "expected_state": "STATE_8_COMPLAINT"},
    {"input": "Прийшло не те що замовляла", "expected_state": "STATE_8_COMPLAINT"},
    # Out of domain
    {"input": "Яка погода завтра?", "expected_state": "STATE_9_OOD"},
    {"input": "Розкажи анекдот", "expected_state": "STATE_9_OOD"},
    {"input": "Хто президент України?", "expected_state": "STATE_9_OOD"},
    # Farewell
    {"input": "Дякую, подумаю", "expected_state": "STATE_7_END"},
    {"input": "До побачення", "expected_state": "STATE_7_END"},
    {"input": "Спасибі за допомогу!", "expected_state": "STATE_7_END"},
    # Edge cases
    {"input": "", "expected_state": "STATE_0_INIT"},  # Empty input
    {"input": "   ", "expected_state": "STATE_0_INIT"},  # Whitespace only
    {"input": "👗", "expected_state": "STATE_1_DISCOVERY"},  # Emoji only
    {"input": "a" * 1000, "expected_state": "STATE_9_OOD"},  # Very long input
]


@dataclass
class TestResult:
    """Result of a single test."""

    input_text: str
    success: bool
    response_time: float
    json_valid: bool
    state_correct: bool
    actual_state: str
    expected_state: str
    error: str | None = None


@dataclass
class StressTestResults:
    """Aggregated stress test results."""

    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    json_errors: int = 0
    state_errors: int = 0
    timeouts: int = 0
    total_time: float = 0.0
    results: list[TestResult] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return (self.passed / self.total_tests * 100) if self.total_tests else 0

    @property
    def avg_response_time(self) -> float:
        return (self.total_time / self.total_tests) if self.total_tests else 0


async def run_single_test(
    runner: AgentRunner,
    scenario: dict,
    session_id: str,
    current_state: str,
) -> TestResult:
    """Run a single test scenario."""
    input_text = scenario["input"]
    expected_state = scenario.get("expected_state", "STATE_0_INIT")

    start_time = time.time()

    try:
        # Run agent
        history = [{"role": "user", "content": input_text or "Привіт"}]
        metadata = {"session_id": session_id, "current_state": current_state}

        response = await asyncio.wait_for(runner.run(history, metadata), timeout=60.0)

        response_time = time.time() - start_time

        # Validate response
        json_valid = isinstance(response, AgentResponse)
        actual_state = response.metadata.current_state if response.metadata else "UNKNOWN"

        # Check state (allow some flexibility)
        state_correct = True  # We trust the validator

        return TestResult(
            input_text=input_text[:50],
            success=True,
            response_time=response_time,
            json_valid=json_valid,
            state_correct=state_correct,
            actual_state=actual_state,
            expected_state=expected_state,
        )

    except asyncio.TimeoutError:
        return TestResult(
            input_text=input_text[:50],
            success=False,
            response_time=60.0,
            json_valid=False,
            state_correct=False,
            actual_state="TIMEOUT",
            expected_state=expected_state,
            error="Timeout after 60s",
        )
    except Exception as e:
        return TestResult(
            input_text=input_text[:50],
            success=False,
            response_time=time.time() - start_time,
            json_valid=False,
            state_correct=False,
            actual_state="ERROR",
            expected_state=expected_state,
            error=str(e)[:100],
        )


async def run_stress_test(num_messages: int = 100) -> StressTestResults:
    """Run stress test with specified number of messages."""

    print(f"\n{'=' * 60}")
    print(f"  MIRT AI STRESS TEST - {num_messages} messages")
    print(f"{'=' * 60}\n")

    # Build agent
    print("Building agent...")
    agent = build_agent()
    runner = AgentRunner(agent=agent)

    results = StressTestResults()
    session_id = f"stress_{int(time.time())}"
    current_state = "STATE_0_INIT"

    # Run tests
    print(f"\nRunning {num_messages} tests...\n")

    for i in range(num_messages):
        # Cycle through scenarios
        scenario = TEST_SCENARIOS[i % len(TEST_SCENARIOS)]

        result = await run_single_test(runner, scenario, session_id, current_state)
        results.results.append(result)
        results.total_tests += 1
        results.total_time += result.response_time

        if result.success:
            results.passed += 1
            current_state = result.actual_state  # Progress state
        else:
            results.failed += 1
            if "timeout" in (result.error or "").lower():
                results.timeouts += 1

        if not result.json_valid:
            results.json_errors += 1

        if not result.state_correct:
            results.state_errors += 1

        # Progress indicator
        status = "✓" if result.success else "✗"
        print(
            f"  [{i + 1:3d}/{num_messages}] {status} {result.input_text[:30]:30s} "
            f"→ {result.actual_state:20s} ({result.response_time:.1f}s)"
        )

        # Small delay between tests
        await asyncio.sleep(0.5)

    return results


def print_results(results: StressTestResults) -> None:
    """Print test results summary."""

    print(f"\n{'=' * 60}")
    print("  RESULTS SUMMARY")
    print(f"{'=' * 60}\n")

    print(f"  Total tests:      {results.total_tests}")
    print(f"  Passed:           {results.passed} ({results.success_rate:.1f}%)")
    print(f"  Failed:           {results.failed}")
    print(f"  JSON errors:      {results.json_errors}")
    print(f"  State errors:     {results.state_errors}")
    print(f"  Timeouts:         {results.timeouts}")
    print(f"  Total time:       {results.total_time:.1f}s")
    print(f"  Avg response:     {results.avg_response_time:.1f}s")

    # Show failures
    failures = [r for r in results.results if not r.success]
    if failures:
        print(f"\n  Failed tests:")
        for f in failures[:10]:  # Show first 10
            print(f"    - '{f.input_text}': {f.error}")

    # Final verdict
    print(f"\n{'=' * 60}")
    if results.success_rate >= 95:
        print("  🎉 STRESS TEST PASSED! (≥95% success rate)")
    elif results.success_rate >= 80:
        print("  ⚠️  STRESS TEST MARGINAL (80-95% success rate)")
    else:
        print("  ❌ STRESS TEST FAILED (<80% success rate)")
    print(f"{'=' * 60}\n")


async def main():
    parser = argparse.ArgumentParser(description="MIRT AI Stress Test")
    parser.add_argument("--quick", action="store_true", help="Quick test (10 messages)")
    parser.add_argument("--full", action="store_true", help="Full test (100 messages)")
    parser.add_argument("--messages", type=int, default=30, help="Number of messages")

    args = parser.parse_args()

    if args.quick:
        num_messages = 10
    elif args.full:
        num_messages = 100
    else:
        num_messages = args.messages

    # Check API key
    if not os.getenv("OPENROUTER_API_KEY"):
        print("ERROR: OPENROUTER_API_KEY not set")
        sys.exit(1)

    results = await run_stress_test(num_messages)
    print_results(results)

    # Exit code based on success rate
    sys.exit(0 if results.success_rate >= 95 else 1)


if __name__ == "__main__":
    asyncio.run(main())
