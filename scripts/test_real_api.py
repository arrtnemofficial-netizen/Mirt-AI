#!/usr/bin/env python3
"""
🔥 HARDCORE TEST: PydanticAI + LangGraph with REAL API
=======================================================
Comprehensive test of the entire agent pipeline using real OpenRouter API.
Tests the most difficult, edge-case scenarios.

Usage:
    python scripts/test_real_api.py

Requirements:
    - OPENROUTER_API_KEY in .env
    - All dependencies installed
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment BEFORE importing anything else
from dotenv import load_dotenv


load_dotenv(project_root / ".env")

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table


console = Console()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# TEST CASES - HARDCORE SCENARIOS
# =============================================================================


@dataclass
class TestCase:
    """Single test case definition."""

    name: str
    description: str
    messages: list[str]
    expected_intent: str | None = None
    expected_state: str | None = None
    expected_event: str | None = None
    expect_products: bool = False
    expect_escalation: bool = False
    current_state: str = "STATE_0_INIT"
    metadata: dict[str, Any] | None = None


# HARDCORE TEST SCENARIOS
HARDCORE_TESTS = [
    # =========================================================================
    # 1. BASIC GREETINGS & DISCOVERY
    # =========================================================================
    TestCase(
        name="Greeting - Simple Hello",
        description="Basic Ukrainian greeting",
        messages=["Привіт!"],
        expected_intent="GREETING_ONLY",
        expected_state="STATE_0_INIT",
        expected_event="simple_answer",
    ),
    TestCase(
        name="Greeting - With Question",
        description="Greeting with immediate question",
        messages=["Вітаю, чи є у вас сукні для дівчинки 7 років?"],
        expected_intent="DISCOVERY_OR_QUESTION",
        expected_state="STATE_1_DISCOVERY",
        expect_products=True,
    ),
    # =========================================================================
    # 2. PRODUCT SEARCH - COMPLEX QUERIES
    # =========================================================================
    TestCase(
        name="Product Search - Specific Item",
        description="Search for specific dress model",
        messages=["Покажіть мені сукню Анна голубого кольору"],
        expected_intent="DISCOVERY_OR_QUESTION",
        expect_products=True,
        current_state="STATE_1_DISCOVERY",
    ),
    TestCase(
        name="Product Search - Size Query",
        description="Search with height for size recommendation",
        messages=["Дитина 125 см, потрібна святкова сукня"],
        expected_intent="SIZE_HELP",
        expect_products=True,
        current_state="STATE_1_DISCOVERY",
    ),
    TestCase(
        name="Product Search - Color Question",
        description="Ask about available colors",
        messages=["Які кольори є в костюмі Ритм?"],
        expected_intent="COLOR_HELP",
        expect_products=True,
        current_state="STATE_1_DISCOVERY",
    ),
    TestCase(
        name="Product Search - Multiple Criteria",
        description="Complex search with multiple requirements",
        messages=["Потрібен теплий костюм для дівчинки 8 років, 130 см, на школу, бажано рожевий"],
        expected_intent="SIZE_HELP",
        expect_products=True,
        current_state="STATE_1_DISCOVERY",
    ),
    # =========================================================================
    # 3. SIZE RECOMMENDATION - EDGE CASES
    # =========================================================================
    TestCase(
        name="Size - Border Height 120cm",
        description="Height at border - should recommend BIGGER size",
        messages=["Дитина рівно 120 см, який розмір краще?"],
        expected_intent="SIZE_HELP",
        current_state="STATE_3_SIZE_COLOR",
    ),
    TestCase(
        name="Size - Very Small Child",
        description="Child below catalog range",
        messages=["Малюку 70 см, чи є щось для нього?"],
        expected_intent="SIZE_HELP",
        current_state="STATE_3_SIZE_COLOR",
    ),
    TestCase(
        name="Size - Very Tall Child",
        description="Child above catalog range",
        messages=["Дитина 170 см, чи є щось на такий зріст?"],
        expected_intent="SIZE_HELP",
        current_state="STATE_3_SIZE_COLOR",
    ),
    # =========================================================================
    # 4. PAYMENT & DELIVERY FLOW
    # =========================================================================
    TestCase(
        name="Payment - Initial Request",
        description="Customer ready to order",
        messages=["Хочу замовити сукню Анна голубу 122-128"],
        expected_intent="PAYMENT_DELIVERY",
        current_state="STATE_4_OFFER",
        metadata={
            "selected_products": [
                {
                    "id": 3443041,
                    "name": "Сукня Анна",
                    "size": "122-128",
                    "color": "голубий",
                    "price": 1850,
                }
            ]
        },
    ),
    TestCase(
        name="Payment - With Delivery Data",
        description="Customer provides all delivery info",
        messages=["Марія Петренко, +380671234567, Київ, відділення НП №5"],
        expected_intent="PAYMENT_DELIVERY",
        current_state="STATE_5_PAYMENT_DELIVERY",
    ),
    TestCase(
        name="Payment - Partial Data",
        description="Customer provides only some data",
        messages=["Мене звати Оксана, телефон 0671112233"],
        expected_intent="PAYMENT_DELIVERY",
        current_state="STATE_5_PAYMENT_DELIVERY",
    ),
    # =========================================================================
    # 5. COMPLAINTS & ESCALATION
    # =========================================================================
    TestCase(
        name="Complaint - Product Quality",
        description="Customer complaint about product",
        messages=["Отримала сукню, вона порвана! Хочу повернення!"],
        expected_intent="COMPLAINT",
        expected_event="escalation",
        expect_escalation=True,
        current_state="STATE_7_END",
    ),
    TestCase(
        name="Complaint - Wrong Item",
        description="Customer received wrong item",
        messages=["Замовляла голубу сукню, прийшла чорна! Що за справи?!"],
        expected_intent="COMPLAINT",
        expected_event="escalation",
        expect_escalation=True,
    ),
    TestCase(
        name="Escalation - Request Human",
        description="Customer explicitly asks for human",
        messages=["Хочу поговорити з живою людиною, не з ботом!"],
        expected_event="escalation",
        expect_escalation=True,
    ),
    # =========================================================================
    # 6. OFF-TOPIC & IDENTITY
    # =========================================================================
    TestCase(
        name="Identity - Bot Question",
        description="Customer asks if talking to bot",
        messages=["Ти бот чи людина?"],
        expected_intent="OUT_OF_DOMAIN",
        expected_event="simple_answer",
    ),
    TestCase(
        name="Off-Topic - Weather",
        description="Customer asks about weather",
        messages=["Яка сьогодні погода в Києві?"],
        expected_intent="OUT_OF_DOMAIN",
        expected_event="simple_answer",
    ),
    TestCase(
        name="Off-Topic - Joke Request",
        description="Customer asks for a joke",
        messages=["Розкажи смішний анекдот!"],
        expected_intent="OUT_OF_DOMAIN",
    ),
    # =========================================================================
    # 7. EDGE CASES & STRESS TESTS
    # =========================================================================
    TestCase(
        name="Edge - Empty Message",
        description="Empty message handling",
        messages=["   "],
        expected_intent="UNKNOWN_OR_EMPTY",
    ),
    TestCase(
        name="Edge - Special Characters",
        description="Message with only special chars",
        messages=["@#$%^&*()"],
        expected_intent="UNKNOWN_OR_EMPTY",
    ),
    TestCase(
        name="Edge - Very Long Message",
        description="Extremely long message",
        messages=["Привіт! " * 100 + "Мені потрібна сукня для дівчинки 7 років"],
        expected_intent="DISCOVERY_OR_QUESTION",
    ),
    TestCase(
        name="Edge - Multiple Questions",
        description="Multiple questions in one message",
        messages=["Скільки коштує сукня Анна? Які розміри є? А доставка безкоштовна?"],
        expected_intent="DISCOVERY_OR_QUESTION",
    ),
    # =========================================================================
    # 8. MULTI-TURN CONVERSATION
    # =========================================================================
    TestCase(
        name="Multi-turn - Size Clarification",
        description="Follow-up on size after initial answer",
        messages=["А якщо дитина швидко росте, може взяти на розмір більше?"],
        expected_intent="SIZE_HELP",
        current_state="STATE_3_SIZE_COLOR",
    ),
    TestCase(
        name="Multi-turn - Color Change",
        description="Customer changes color preference",
        messages=["Насправді, краще покажіть малинову, а не голубу"],
        expected_intent="COLOR_HELP",
        current_state="STATE_4_OFFER",
        expect_products=True,
    ),
    # =========================================================================
    # 9. HALLUCINATION PREVENTION
    # =========================================================================
    TestCase(
        name="Hallucination - Non-existent Product",
        description="Ask about product not in catalog",
        messages=["Чи є у вас дитячі кросівки Nike?"],
        expected_intent="DISCOVERY_OR_QUESTION",
        # Should NOT return products (not in catalog)
    ),
    TestCase(
        name="Hallucination - Wrong Price",
        description="Customer challenges price",
        messages=["Ви сказали що сукня 2000 грн, але на сайті 1850?"],
        # Should acknowledge and check catalog
    ),
    # =========================================================================
    # 10. UKRAINIAN LANGUAGE SPECIFICS
    # =========================================================================
    TestCase(
        name="Ukrainian - Slang",
        description="Customer uses informal Ukrainian",
        messages=["Йо, є шось прикольне для доні?"],
        expected_intent="DISCOVERY_OR_QUESTION",
    ),
    TestCase(
        name="Ukrainian - Surzhyk",
        description="Mixed Ukrainian-Russian",
        messages=["Єсть какіесь плаття для дівчінки?"],
        expected_intent="DISCOVERY_OR_QUESTION",
    ),
]


# =============================================================================
# TEST RUNNER
# =============================================================================


async def run_single_test(test: TestCase) -> dict[str, Any]:
    """Run a single test case and return results."""
    from src.agents import AgentDeps, SupportResponse, run_support
    from src.agents.pydantic.models import SupportResponse

    # Create deps
    deps = AgentDeps(
        session_id=f"test_{test.name.lower().replace(' ', '_')[:20]}",
        user_id="test_user",
        current_state=test.current_state,
        channel="test",
        language="uk",
    )

    # Add metadata if provided
    if test.metadata:
        if "selected_products" in test.metadata:
            deps.selected_products = test.metadata["selected_products"]

    results = {
        "name": test.name,
        "description": test.description,
        "passed": True,
        "errors": [],
        "response": None,
        "latency_ms": 0,
    }

    try:
        # Run the agent
        start_time = time.perf_counter()

        # Combine all messages into one (simulating conversation)
        message = " ".join(test.messages)

        response: SupportResponse = await run_support(message, deps)

        latency_ms = (time.perf_counter() - start_time) * 1000
        results["latency_ms"] = round(latency_ms, 2)

        # Store response for analysis
        results["response"] = {
            "event": response.event,
            "messages": [m.content for m in response.messages],
            "products_count": len(response.products),
            "products": [{"id": p.id, "name": p.name, "price": p.price} for p in response.products],
            "metadata": {
                "current_state": response.metadata.current_state,
                "intent": response.metadata.intent,
                "escalation_level": response.metadata.escalation_level,
            },
            "escalation": response.escalation.reason if response.escalation else None,
            "customer_data": response.customer_data.model_dump()
            if response.customer_data
            else None,
        }

        # Validate expectations
        if test.expected_intent and response.metadata.intent != test.expected_intent:
            results["errors"].append(
                f"Intent mismatch: expected {test.expected_intent}, got {response.metadata.intent}"
            )
            results["passed"] = False

        if test.expected_event and response.event != test.expected_event:
            results["errors"].append(
                f"Event mismatch: expected {test.expected_event}, got {response.event}"
            )
            results["passed"] = False

        if test.expect_products and len(response.products) == 0:
            results["errors"].append("Expected products but got none")
            results["passed"] = False

        if test.expect_escalation and response.event != "escalation":
            results["errors"].append("Expected escalation but didn't get one")
            results["passed"] = False

        # Check message quality
        if response.messages:
            msg_content = response.messages[0].content

            # Check for markdown (forbidden)
            if "**" in msg_content or "##" in msg_content or "```" in msg_content:
                results["errors"].append("Response contains forbidden markdown")
                results["passed"] = False

            # Check length
            if len(msg_content) > 900:
                results["errors"].append(f"Response too long: {len(msg_content)} chars (max 900)")
                results["passed"] = False

    except Exception as e:
        results["passed"] = False
        results["errors"].append(f"Exception: {e!s}")
        logger.exception("Test failed: %s", test.name)

    return results


async def run_all_tests() -> list[dict[str, Any]]:
    """Run all test cases."""
    from src.conf.config import settings

    # Verify API key is configured
    api_key = settings.OPENROUTER_API_KEY.get_secret_value()
    if not api_key:
        console.print("[red]ERROR: OPENROUTER_API_KEY not configured in .env[/red]")
        sys.exit(1)

    console.print(
        Panel(
            f"[bold green]🔥 HARDCORE API TEST[/bold green]\n\n"
            f"Model: {settings.AI_MODEL}\n"
            f"Provider: OpenRouter\n"
            f"Tests: {len(HARDCORE_TESTS)}",
            title="Test Configuration",
        )
    )

    results = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Running tests...", total=len(HARDCORE_TESTS))

        for test in HARDCORE_TESTS:
            progress.update(task, description=f"Testing: {test.name}")

            result = await run_single_test(test)
            results.append(result)

            # Show immediate result
            if result["passed"]:
                console.print(f"  [green]✓[/green] {test.name} ({result['latency_ms']}ms)")
            else:
                console.print(f"  [red]✗[/red] {test.name}")
                for error in result["errors"]:
                    console.print(f"    [red]→ {error}[/red]")

            progress.advance(task)

            # Small delay between tests to avoid rate limiting
            await asyncio.sleep(0.5)

    return results


def print_summary(results: list[dict[str, Any]]) -> None:
    """Print test summary."""
    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed
    avg_latency = sum(r["latency_ms"] for r in results) / len(results) if results else 0

    console.print("\n")

    # Summary table
    table = Table(title="📊 Test Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")

    table.add_row("Total Tests", str(len(results)))
    table.add_row("Passed", f"[green]{passed}[/green]")
    table.add_row("Failed", f"[red]{failed}[/red]" if failed else "0")
    table.add_row("Pass Rate", f"{(passed / len(results) * 100):.1f}%")
    table.add_row("Avg Latency", f"{avg_latency:.0f}ms")

    console.print(table)

    # Failed tests details
    if failed > 0:
        console.print("\n[bold red]Failed Tests:[/bold red]")
        for r in results:
            if not r["passed"]:
                console.print(f"\n[red]✗ {r['name']}[/red]")
                console.print(f"  Description: {r['description']}")
                for error in r["errors"]:
                    console.print(f"  [red]→ {error}[/red]")
                if r["response"]:
                    console.print(f"  Response event: {r['response']['event']}")
                    console.print(f"  Response intent: {r['response']['metadata']['intent']}")
                    if r["response"]["messages"]:
                        preview = r["response"]["messages"][0][:100]
                        console.print(f"  Message preview: {preview}...")


def save_results(results: list[dict[str, Any]]) -> None:
    """Save results to JSON file."""
    output_dir = project_root / "test_results"
    output_dir.mkdir(exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"api_test_{timestamp}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    console.print(f"\n[dim]Results saved to: {output_file}[/dim]")


async def main():
    """Main entry point."""
    console.print(
        "\n[bold cyan]═══════════════════════════════════════════════════════════[/bold cyan]"
    )
    console.print("[bold cyan]   PydanticAI + LangGraph REAL API TEST   [/bold cyan]")
    console.print(
        "[bold cyan]═══════════════════════════════════════════════════════════[/bold cyan]\n"
    )

    try:
        results = await run_all_tests()
        print_summary(results)
        save_results(results)

        # Exit with error code if any test failed
        failed = sum(1 for r in results if not r["passed"])
        if failed > 0:
            console.print(f"\n[red]⚠ {failed} test(s) failed[/red]")
            sys.exit(1)
        else:
            console.print("\n[green]✓ All tests passed![/green]")

    except KeyboardInterrupt:
        console.print("\n[yellow]Test interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[red]Fatal error: {e}[/red]")
        logger.exception("Fatal error during testing")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
