"""
Vision Evaluation Harness.
==========================
Evaluates vision agent performance on test_set.json.

Metrics:
- Top-1 accuracy (correct product identified)
- Color accuracy (correct color when product matches)
- Confidence distribution
- Clarification rate (needs_clarification=True)
- Enrichment success rate (product found in DB)
- Latency (p50, p95, p99)

Run:
    python tests/eval/run_vision_eval.py [--dataset test_set.json] [--limit N]
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Add project root to path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.agents.pydantic.deps import AgentDeps
from src.agents.pydantic.vision_agent import run_vision


async def load_test_set(dataset_path: Path) -> list[dict[str, Any]]:
    """Load test set from JSON file."""
    if not dataset_path.exists():
        raise FileNotFoundError(f"Test set not found: {dataset_path}")
    
    with open(dataset_path, encoding="utf-8") as f:
        data = json.load(f)
    
    # Handle both list and dict formats
    if isinstance(data, dict) and "test_cases" in data:
        return data["test_cases"]
    elif isinstance(data, list):
        return data
    else:
        raise ValueError(f"Unexpected test set format in {dataset_path}")


async def evaluate_vision_case(
    case: dict[str, Any],
    case_idx: int,
    total: int,
) -> dict[str, Any]:
    """
    Evaluate a single vision test case.
    
    Returns:
        {
            "case_id": str,
            "expected_product": str,
            "expected_color": str | None,
            "identified_product": str | None,
            "identified_color": str | None,
            "confidence": float,
            "needs_clarification": bool,
            "enrichment_success": bool,
            "latency_ms": float,
            "correct_product": bool,
            "correct_color": bool | None,
            "error": str | None,
        }
    """
    case_id = case.get("id", f"case_{case_idx}")
    image_url = case.get("image_url", "")
    expected_product = case.get("expected_product", "")
    expected_color = case.get("expected_color")
    expected_price = case.get("expected_price")
    
    if not image_url:
        return {
            "case_id": case_id,
            "expected_product": expected_product,
            "expected_color": expected_color,
            "identified_product": None,
            "identified_color": None,
            "confidence": 0.0,
            "needs_clarification": True,
            "enrichment_success": False,
            "latency_ms": 0.0,
            "correct_product": False,
            "correct_color": None,
            "error": "No image_url in test case",
        }
    
    # Prepare deps
    deps = AgentDeps(
        session_id=f"eval_{case_id}",
        trace_id=f"eval_trace_{case_id}",
        image_url=image_url,
        language="uk",
        channel="eval",
    )
    
    # Run vision
    start_time = time.perf_counter()
    try:
        response = await run_vision(message="Що це?", deps=deps)
        latency_ms = (time.perf_counter() - start_time) * 1000
        
        identified_product = None
        identified_color = None
        confidence = response.confidence or 0.0
        needs_clarification = response.needs_clarification or False
        
        if response.identified_product:
            identified_product = response.identified_product.name
            identified_color = response.identified_product.color
        
        # Check enrichment success (product should be in DB)
        enrichment_success = False
        if identified_product:
            try:
                from src.services.catalog_service import CatalogService
                catalog = CatalogService()
                results = await catalog.search_products(query=identified_product, limit=1)
                enrichment_success = len(results) > 0
            except Exception:
                enrichment_success = False
        
        # Evaluate correctness
        correct_product = False
        correct_color = None
        
        if identified_product and expected_product:
            # Normalize product names for comparison
            id_norm = identified_product.lower().strip()
            exp_norm = expected_product.lower().strip()
            correct_product = id_norm == exp_norm or exp_norm in id_norm or id_norm in exp_norm
            
            if correct_product and expected_color and identified_color:
                id_color_norm = identified_color.lower().strip()
                exp_color_norm = expected_color.lower().strip()
                correct_color = id_color_norm == exp_color_norm or exp_color_norm in id_color_norm
        
        return {
            "case_id": case_id,
            "expected_product": expected_product,
            "expected_color": expected_color,
            "identified_product": identified_product,
            "identified_color": identified_color,
            "confidence": confidence,
            "needs_clarification": needs_clarification,
            "enrichment_success": enrichment_success,
            "latency_ms": latency_ms,
            "correct_product": correct_product,
            "correct_color": correct_color,
            "error": None,
        }
    except Exception as e:
        latency_ms = (time.perf_counter() - start_time) * 1000
        return {
            "case_id": case_id,
            "expected_product": expected_product,
            "expected_color": expected_color,
            "identified_product": None,
            "identified_color": None,
            "confidence": 0.0,
            "needs_clarification": True,
            "enrichment_success": False,
            "latency_ms": latency_ms,
            "correct_product": False,
            "correct_color": None,
            "error": str(e),
        }


def calculate_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate aggregate metrics from evaluation results."""
    total = len(results)
    if total == 0:
        return {}
    
    correct_products = sum(1 for r in results if r.get("correct_product", False))
    correct_colors = sum(1 for r in results if r.get("correct_color") is True)
    color_evaluated = sum(1 for r in results if r.get("correct_color") is not None)
    
    clarifications = sum(1 for r in results if r.get("needs_clarification", False))
    enrichment_successes = sum(1 for r in results if r.get("enrichment_success", False))
    
    latencies = [r["latency_ms"] for r in results if r.get("latency_ms", 0) > 0]
    latencies.sort()
    
    confidences = [r["confidence"] for r in results if r.get("confidence") is not None]
    confidences.sort()
    
    errors = sum(1 for r in results if r.get("error"))
    
    metrics = {
        "total_cases": total,
        "top1_accuracy": correct_products / total if total > 0 else 0.0,
        "color_accuracy": correct_colors / color_evaluated if color_evaluated > 0 else None,
        "clarification_rate": clarifications / total if total > 0 else 0.0,
        "enrichment_success_rate": enrichment_successes / total if total > 0 else 0.0,
        "error_rate": errors / total if total > 0 else 0.0,
        "latency_ms": {
            "p50": latencies[len(latencies) // 2] if latencies else 0.0,
            "p95": latencies[int(len(latencies) * 0.95)] if len(latencies) > 0 else 0.0,
            "p99": latencies[int(len(latencies) * 0.99)] if len(latencies) > 0 else 0.0,
            "mean": sum(latencies) / len(latencies) if latencies else 0.0,
            "max": max(latencies) if latencies else 0.0,
        },
        "confidence": {
            "mean": sum(confidences) / len(confidences) if confidences else 0.0,
            "min": min(confidences) if confidences else 0.0,
            "max": max(confidences) if confidences else 0.0,
            "p50": confidences[len(confidences) // 2] if confidences else 0.0,
        },
    }
    
    return metrics


async def main():
    """Run vision evaluation."""
    parser = argparse.ArgumentParser(description="Evaluate vision agent on test set")
    parser.add_argument(
        "--dataset",
        type=str,
        default="data/vision/generated/test_set.json",
        help="Path to test set JSON file",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of test cases (for quick testing)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output JSON file for results (default: print to stdout)",
    )
    
    args = parser.parse_args()
    
    dataset_path = project_root / args.dataset
    test_cases = await load_test_set(dataset_path)
    
    if args.limit:
        test_cases = test_cases[: args.limit]
    
    print(f"Evaluating {len(test_cases)} vision test cases...")
    print("=" * 60)
    
    results = []
    for idx, case in enumerate(test_cases):
        print(f"[{idx + 1}/{len(test_cases)}] Evaluating {case.get('id', f'case_{idx}')}...", end=" ")
        result = await evaluate_vision_case(case, idx, len(test_cases))
        results.append(result)
        
        if result.get("error"):
            print(f"ERROR: {result['error']}")
        elif result.get("correct_product"):
            print(f"✓ Product correct (confidence={result['confidence']:.0%})")
        else:
            print(f"✗ Product mismatch: expected '{result['expected_product']}', got '{result['identified_product']}'")
    
    print("\n" + "=" * 60)
    print("METRICS:")
    print("=" * 60)
    
    metrics = calculate_metrics(results)
    print(f"Total cases: {metrics['total_cases']}")
    print(f"Top-1 accuracy: {metrics['top1_accuracy']:.1%}")
    if metrics.get("color_accuracy") is not None:
        print(f"Color accuracy: {metrics['color_accuracy']:.1%}")
    print(f"Clarification rate: {metrics['clarification_rate']:.1%}")
    print(f"Enrichment success rate: {metrics['enrichment_success_rate']:.1%}")
    print(f"Error rate: {metrics['error_rate']:.1%}")
    print(f"\nLatency (ms):")
    print(f"  Mean: {metrics['latency_ms']['mean']:.0f}")
    print(f"  P50: {metrics['latency_ms']['p50']:.0f}")
    print(f"  P95: {metrics['latency_ms']['p95']:.0f}")
    print(f"  P99: {metrics['latency_ms']['p99']:.0f}")
    print(f"  Max: {metrics['latency_ms']['max']:.0f}")
    print(f"\nConfidence:")
    print(f"  Mean: {metrics['confidence']['mean']:.1%}")
    print(f"  Min: {metrics['confidence']['min']:.1%}")
    print(f"  Max: {metrics['confidence']['max']:.1%}")
    print(f"  P50: {metrics['confidence']['p50']:.1%}")
    
    # Save results if output specified
    if args.output:
        output_path = project_root / args.output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "metrics": metrics,
                    "results": results,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )
        print(f"\nResults saved to {output_path}")
    
    # Exit with error code if accuracy is too low
    if metrics["top1_accuracy"] < 0.7:
        print("\n⚠️  WARNING: Top-1 accuracy below 70%!")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

