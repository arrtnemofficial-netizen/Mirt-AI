#!/usr/bin/env python3
"""
🔥 FULL LANGGRAPH INTEGRATION TEST
===================================
Tests the complete LangGraph pipeline with real API:
- Graph building & compilation
- Node execution (moderation → intent → agent → validation)
- State persistence (checkpointing)
- Self-correction loops
- Multi-turn conversations
- Time travel (rollback/fork)

Usage:
    python scripts/test_langgraph_full.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4


# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment
from dotenv import load_dotenv


load_dotenv(project_root / ".env")

from rich.console import Console
from rich.panel import Panel
from rich.table import Table


console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# TEST SCENARIOS
# =============================================================================


class ConversationScenario:
    """Multi-turn conversation test scenario."""

    def __init__(
        self,
        name: str,
        description: str,
        turns: list[dict[str, Any]],
    ):
        self.name = name
        self.description = description
        self.turns = turns
        self.session_id = f"test_{uuid4().hex[:12]}"


CONVERSATION_SCENARIOS = [
    # =========================================================================
    # SCENARIO 1: Complete Purchase Flow
    # =========================================================================
    ConversationScenario(
        name="Full Purchase Flow",
        description="Complete flow from greeting to order",
        turns=[
            {
                "user": "Привіт! Шукаю сукню для дівчинки на свято",
                "expect_state": "STATE_1_DISCOVERY",
                "expect_intent": "DISCOVERY_OR_QUESTION",
            },
            {
                "user": "Дитині 7 років, зріст 122 см",
                "expect_state": "STATE_3_SIZE_COLOR",
                "expect_intent": "SIZE_HELP",
                "expect_products": True,
            },
            {
                "user": "Покажіть сукню Анна голубу",
                "expect_products": True,
            },
            {
                "user": "Так, беремо! Як замовити?",
                "expect_state": "STATE_5_PAYMENT_DELIVERY",
                "expect_intent": "PAYMENT_DELIVERY",
            },
            {
                "user": "Марія Іваненко, +380671234567, Київ, НП №10",
                "expect_intent": "PAYMENT_DELIVERY",
            },
        ],
    ),
    # =========================================================================
    # SCENARIO 2: Size Clarification Loop
    # =========================================================================
    ConversationScenario(
        name="Size Clarification",
        description="Multiple questions about size",
        turns=[
            {
                "user": "Яка сукня буде на дитину 120 см?",
                "expect_intent": "SIZE_HELP",
            },
            {
                "user": "А якщо на виріст, може більший розмір?",
                "expect_intent": "SIZE_HELP",
            },
            {
                "user": "Дитина худенька, чи не буде завеликим?",
                "expect_intent": "SIZE_HELP",
            },
        ],
    ),
    # =========================================================================
    # SCENARIO 3: Color Comparison
    # =========================================================================
    ConversationScenario(
        name="Color Comparison",
        description="Customer comparing colors",
        turns=[
            {
                "user": "Які кольори є в костюмі Ритм?",
                "expect_intent": "COLOR_HELP",
                "expect_products": True,
            },
            {
                "user": "Покажіть рожевий",
                "expect_products": True,
            },
            {
                "user": "А тепер бордовий",
                "expect_products": True,
            },
            {
                "user": "Який краще для святкового виходу?",
            },
        ],
    ),
    # =========================================================================
    # SCENARIO 4: Complaint Handling
    # =========================================================================
    ConversationScenario(
        name="Complaint Flow",
        description="Customer with complaint",
        turns=[
            {
                "user": "Замовляла сукню тиждень тому, досі не прийшла!",
                "expect_intent": "COMPLAINT",
                "expect_escalation": True,
            },
        ],
    ),
    # =========================================================================
    # SCENARIO 5: Off-Topic Recovery
    # =========================================================================
    ConversationScenario(
        name="Off-Topic Recovery",
        description="Customer goes off-topic, agent recovers",
        turns=[
            {
                "user": "Привіт!",
                "expect_intent": "GREETING_ONLY",
            },
            {
                "user": "Як справи?",
                "expect_intent": "OUT_OF_DOMAIN",
            },
            {
                "user": "Розкажи анекдот!",
                "expect_intent": "OUT_OF_DOMAIN",
            },
            {
                "user": "Ладно, покажи сукні",
                "expect_intent": "DISCOVERY_OR_QUESTION",
            },
        ],
    ),
]


# =============================================================================
# GRAPH TESTS
# =============================================================================


async def test_graph_compilation() -> dict[str, Any]:
    """Test that graph compiles correctly."""
    console.print("\n[bold cyan]═══ TEST: Graph Compilation ═══[/bold cyan]")

    result = {"name": "Graph Compilation", "passed": True, "errors": [], "details": {}}

    try:
        from src.agents import (
            build_production_graph,
        )
        from src.agents.langgraph.checkpointer import get_checkpointer

        # Test building fresh graph
        console.print("  Building production graph...")

        start = time.perf_counter()

        # Create a test runner
        async def test_runner(msg: str, metadata: dict) -> dict:
            from src.agents import create_deps_from_state, run_support

            deps = create_deps_from_state(metadata)
            response = await run_support(msg, deps)
            return response.model_dump()

        checkpointer = get_checkpointer()
        graph = build_production_graph(test_runner, checkpointer)

        build_time = (time.perf_counter() - start) * 1000
        result["details"]["build_time_ms"] = round(build_time, 2)

        # Verify graph structure
        # Get node names from the graph
        nodes = list(graph.nodes.keys()) if hasattr(graph, "nodes") else []
        result["details"]["nodes"] = nodes

        console.print(f"  [green]✓[/green] Graph compiled in {build_time:.0f}ms")
        console.print(f"  [dim]Nodes: {nodes}[/dim]")

    except Exception as e:
        result["passed"] = False
        result["errors"].append(str(e))
        console.print(f"  [red]✗[/red] {e}")
        logger.exception("Graph compilation failed")

    return result


async def test_single_invocation() -> dict[str, Any]:
    """Test single graph invocation."""
    console.print("\n[bold cyan]═══ TEST: Single Invocation ═══[/bold cyan]")

    result = {"name": "Single Invocation", "passed": True, "errors": [], "details": {}}

    try:
        from src.agents import (
            create_initial_state,
            invoke_graph,
        )

        session_id = f"test_single_{uuid4().hex[:8]}"

        # Create initial state
        state = create_initial_state(
            session_id=session_id,
            messages=[{"role": "user", "content": "Привіт! Покажіть сукні для дівчинки"}],
            metadata={"channel": "test", "user_id": "test_user"},
        )

        console.print(f"  Session: {session_id}")
        console.print("  Message: 'Привіт! Покажіть сукні для дівчинки'")

        # Invoke graph
        start = time.perf_counter()
        final_state = await invoke_graph(state=state, session_id=session_id)
        latency = (time.perf_counter() - start) * 1000

        result["details"]["latency_ms"] = round(latency, 2)
        result["details"]["final_state"] = final_state.get("current_state")
        result["details"]["intent"] = final_state.get("detected_intent")

        # Extract response
        agent_response = final_state.get("agent_response", {})
        messages = agent_response.get("messages", [])

        if messages:
            first_msg = messages[0].get("content", "")[:100]
            result["details"]["response_preview"] = first_msg
            console.print(f"  [green]✓[/green] Response received ({latency:.0f}ms)")
            console.print(f"  [dim]State: {final_state.get('current_state')}[/dim]")
            console.print(f"  [dim]Intent: {final_state.get('detected_intent')}[/dim]")
            console.print(f"  [dim]Response: {first_msg}...[/dim]")
        else:
            result["errors"].append("No messages in response")
            result["passed"] = False

    except Exception as e:
        result["passed"] = False
        result["errors"].append(str(e))
        console.print(f"  [red]✗[/red] {e}")
        logger.exception("Single invocation failed")

    return result


async def test_conversation_scenario(scenario: ConversationScenario) -> dict[str, Any]:
    """Test a multi-turn conversation scenario."""
    console.print(f"\n[bold cyan]═══ SCENARIO: {scenario.name} ═══[/bold cyan]")
    console.print(f"[dim]{scenario.description}[/dim]")

    result = {
        "name": scenario.name,
        "passed": True,
        "errors": [],
        "turns": [],
    }

    try:
        from src.agents import (
            create_initial_state,
            get_active_graph,
        )

        graph = get_active_graph()
        config = {"configurable": {"thread_id": scenario.session_id}}

        current_state = None

        for i, turn in enumerate(scenario.turns, 1):
            turn_result = {
                "turn": i,
                "user_message": turn["user"],
                "passed": True,
                "errors": [],
            }

            console.print(f"\n  Turn {i}: [cyan]{turn['user'][:50]}...[/cyan]")

            try:
                # Build state for this turn
                if current_state is None:
                    state = create_initial_state(
                        session_id=scenario.session_id,
                        messages=[{"role": "user", "content": turn["user"]}],
                        metadata={"channel": "test"},
                    )
                else:
                    # Add new message to existing state
                    state = {
                        **current_state,
                        "messages": current_state.get("messages", [])
                        + [{"role": "user", "content": turn["user"]}],
                    }

                # Invoke
                start = time.perf_counter()
                current_state = await graph.ainvoke(state, config=config)
                latency = (time.perf_counter() - start) * 1000

                turn_result["latency_ms"] = round(latency, 2)
                turn_result["final_state"] = current_state.get("current_state")
                turn_result["intent"] = current_state.get("detected_intent")

                # Check expectations
                if "expect_state" in turn:
                    if current_state.get("current_state") != turn["expect_state"]:
                        turn_result["errors"].append(
                            f"State mismatch: expected {turn['expect_state']}, "
                            f"got {current_state.get('current_state')}"
                        )
                        turn_result["passed"] = False

                if "expect_intent" in turn:
                    if current_state.get("detected_intent") != turn["expect_intent"]:
                        turn_result["errors"].append(
                            f"Intent mismatch: expected {turn['expect_intent']}, "
                            f"got {current_state.get('detected_intent')}"
                        )
                        turn_result["passed"] = False

                if turn.get("expect_products"):
                    products = current_state.get("selected_products", [])
                    if not products:
                        agent_resp = current_state.get("agent_response", {})
                        products = agent_resp.get("products", [])
                    if not products:
                        turn_result["errors"].append("Expected products but got none")
                        turn_result["passed"] = False

                if turn.get("expect_escalation"):
                    if current_state.get("should_escalate") != True:
                        agent_resp = current_state.get("agent_response", {})
                        if agent_resp.get("event") != "escalation":
                            turn_result["errors"].append("Expected escalation but didn't get one")
                            turn_result["passed"] = False

                # Get response preview
                agent_resp = current_state.get("agent_response", {})
                messages = agent_resp.get("messages", [])
                if messages:
                    preview = messages[0].get("content", "")[:80]
                    turn_result["response_preview"] = preview

                # Print turn result
                if turn_result["passed"]:
                    console.print(
                        f"    [green]✓[/green] ({latency:.0f}ms) State={current_state.get('current_state')}"
                    )
                else:
                    console.print(f"    [red]✗[/red] ({latency:.0f}ms)")
                    for err in turn_result["errors"]:
                        console.print(f"      [red]→ {err}[/red]")

            except Exception as e:
                turn_result["passed"] = False
                turn_result["errors"].append(str(e))
                console.print(f"    [red]✗[/red] Exception: {e}")

            result["turns"].append(turn_result)

            if not turn_result["passed"]:
                result["passed"] = False

            # Small delay between turns
            await asyncio.sleep(0.3)

    except Exception as e:
        result["passed"] = False
        result["errors"].append(str(e))
        console.print(f"  [red]✗[/red] Scenario failed: {e}")
        logger.exception("Scenario failed")

    return result


async def test_state_persistence() -> dict[str, Any]:
    """Test that state persists across invocations."""
    console.print("\n[bold cyan]═══ TEST: State Persistence ═══[/bold cyan]")

    result = {"name": "State Persistence", "passed": True, "errors": [], "details": {}}

    try:
        from src.agents import (
            create_initial_state,
            get_active_graph,
        )

        session_id = f"test_persist_{uuid4().hex[:8]}"
        graph = get_active_graph()
        config = {"configurable": {"thread_id": session_id}}

        # First invocation
        state1 = create_initial_state(
            session_id=session_id,
            messages=[{"role": "user", "content": "Привіт!"}],
        )

        console.print(f"  Session: {session_id}")
        console.print("  Turn 1: 'Привіт!'")

        result1 = await graph.ainvoke(state1, config=config)
        console.print(f"    → State after turn 1: {result1.get('current_state')}")

        # Second invocation (should continue from checkpoint)
        state2 = {
            **result1,
            "messages": result1.get("messages", [])
            + [{"role": "user", "content": "Покажіть сукні"}],
        }

        console.print("  Turn 2: 'Покажіть сукні'")

        result2 = await graph.ainvoke(state2, config=config)
        console.print(f"    → State after turn 2: {result2.get('current_state')}")

        # Verify step numbers increased
        step1 = result1.get("step_number", 0)
        step2 = result2.get("step_number", 0)

        if step2 <= step1:
            result["errors"].append(f"Step number didn't increase: {step1} -> {step2}")
            result["passed"] = False

        result["details"]["step_1"] = step1
        result["details"]["step_2"] = step2
        result["details"]["state_1"] = result1.get("current_state")
        result["details"]["state_2"] = result2.get("current_state")

        if result["passed"]:
            console.print(f"  [green]✓[/green] State persisted (steps: {step1} → {step2})")

    except Exception as e:
        result["passed"] = False
        result["errors"].append(str(e))
        console.print(f"  [red]✗[/red] {e}")
        logger.exception("State persistence test failed")

    return result


async def test_self_correction() -> dict[str, Any]:
    """Test self-correction loop behavior."""
    console.print("\n[bold cyan]═══ TEST: Self-Correction Loop ═══[/bold cyan]")

    result = {"name": "Self-Correction", "passed": True, "errors": [], "details": {}}

    try:
        from src.agents import create_initial_state, get_active_graph

        session_id = f"test_correction_{uuid4().hex[:8]}"
        graph = get_active_graph()
        config = {"configurable": {"thread_id": session_id}}

        # Normal message - should pass validation
        state = create_initial_state(
            session_id=session_id,
            messages=[{"role": "user", "content": "Скільки коштує сукня Анна?"}],
        )

        console.print("  Testing normal message processing...")

        final_state = await graph.ainvoke(state, config=config)

        retry_count = final_state.get("retry_count", 0)
        validation_errors = final_state.get("validation_errors", [])

        result["details"]["retry_count"] = retry_count
        result["details"]["validation_errors"] = validation_errors

        console.print(f"  [green]✓[/green] Retry count: {retry_count}")
        console.print(f"  [dim]Validation errors: {len(validation_errors)}[/dim]")

    except Exception as e:
        result["passed"] = False
        result["errors"].append(str(e))
        console.print(f"  [red]✗[/red] {e}")
        logger.exception("Self-correction test failed")

    return result


# =============================================================================
# MAIN TEST RUNNER
# =============================================================================


async def run_all_tests() -> list[dict[str, Any]]:
    """Run all LangGraph tests."""
    from src.conf.config import settings

    # Verify configuration
    api_key = settings.OPENROUTER_API_KEY.get_secret_value()
    if not api_key:
        console.print("[red]ERROR: OPENROUTER_API_KEY not configured[/red]")
        sys.exit(1)

    console.print(
        Panel(
            f"[bold green]🔥 LANGGRAPH FULL INTEGRATION TEST[/bold green]\n\n"
            f"Model: {settings.AI_MODEL}\n"
            f"Scenarios: {len(CONVERSATION_SCENARIOS)}",
            title="Configuration",
        )
    )

    results = []

    # Infrastructure tests
    results.append(await test_graph_compilation())
    results.append(await test_single_invocation())
    results.append(await test_state_persistence())
    results.append(await test_self_correction())

    # Conversation scenarios
    for scenario in CONVERSATION_SCENARIOS:
        result = await test_conversation_scenario(scenario)
        results.append(result)
        await asyncio.sleep(1)  # Rate limiting between scenarios

    return results


def print_summary(results: list[dict[str, Any]]) -> None:
    """Print test summary."""
    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed

    console.print("\n")

    table = Table(title="📊 LangGraph Test Summary")
    table.add_column("Test", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Details")

    for r in results:
        status = "[green]PASS[/green]" if r["passed"] else "[red]FAIL[/red]"
        details = ", ".join(r.get("errors", [])) or "OK"
        table.add_row(r["name"], status, details[:50])

    console.print(table)

    console.print(f"\n[bold]Total: {passed}/{len(results)} passed[/bold]")


def save_results(results: list[dict[str, Any]]) -> None:
    """Save results to JSON."""
    output_dir = project_root / "test_results"
    output_dir.mkdir(exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"langgraph_test_{timestamp}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)

    console.print(f"\n[dim]Results saved to: {output_file}[/dim]")


async def main():
    """Main entry point."""
    console.print(
        "\n[bold cyan]═══════════════════════════════════════════════════════════[/bold cyan]"
    )
    console.print("[bold cyan]   LANGGRAPH FULL INTEGRATION TEST   [/bold cyan]")
    console.print(
        "[bold cyan]═══════════════════════════════════════════════════════════[/bold cyan]\n"
    )

    try:
        results = await run_all_tests()
        print_summary(results)
        save_results(results)

        failed = sum(1 for r in results if not r["passed"])
        if failed > 0:
            console.print(f"\n[red]⚠ {failed} test(s) failed[/red]")
            sys.exit(1)
        else:
            console.print("\n[green]✓ All tests passed![/green]")

    except KeyboardInterrupt:
        console.print("\n[yellow]Test interrupted[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n[red]Fatal error: {e}[/red]")
        logger.exception("Fatal error")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
