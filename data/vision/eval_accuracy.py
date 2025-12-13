"""
Vision Accuracy Evaluation Script.
===================================
Evaluates vision agent accuracy against a labeled dataset.

Usage:
    python scripts/eval_vision.py --dataset data/eval/vision_test_set.json
    python scripts/eval_vision.py --dataset data/eval/vision_test_set.json --verbose

Dataset format (JSON):
[
    {
        "image_url": "https://...",
        "expected_product": "Лагуна",
        "description": "Плюшевий костюм з повною блискавкою"
    },
    ...
]

Target accuracy: >= 90%
"""

import asyncio
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Any

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


async def evaluate_single_image(
    image_url: str,
    expected_product: str,
    description: str,
    verbose: bool = False,
) -> dict[str, Any]:
    """
    Evaluate vision agent on a single image.
    
    Returns:
        {"correct": bool, "predicted": str, "expected": str, "confidence": float}
    """
    from src.agents.pydantic.vision_agent import run_vision
    from src.agents.pydantic.deps import AgentDeps
    from src.services.catalog_service import CatalogService
    
    # Create deps
    catalog = CatalogService()
    deps = AgentDeps(
        session_id="eval_session",
        catalog=catalog,
        has_image=True,
        image_url=image_url,
        current_state="STATE_2_VISION",
    )
    
    try:
        response = await run_vision(
            message=f"Що це за товар? {description}",
            deps=deps,
        )
        
        predicted = ""
        if response.identified_product and response.identified_product.name:
            predicted = response.identified_product.name
        
        # Check if expected product name is in prediction
        correct = expected_product.lower() in predicted.lower()
        
        result = {
            "correct": correct,
            "predicted": predicted,
            "expected": expected_product,
            "confidence": response.confidence,
            "image_url": image_url[:50] + "..." if len(image_url) > 50 else image_url,
        }
        
        if verbose:
            status = "✅" if correct else "❌"
            logger.info(f"{status} Expected: {expected_product}, Got: {predicted} ({response.confidence:.2f})")
        
        return result
        
    except Exception as e:
        logger.error(f"Error evaluating {image_url[:50]}: {e}")
        return {
            "correct": False,
            "predicted": f"ERROR: {e}",
            "expected": expected_product,
            "confidence": 0.0,
            "image_url": image_url[:50],
        }


async def run_evaluation(dataset_path: str, verbose: bool = False) -> dict[str, Any]:
    """
    Run full evaluation on dataset.
    
    Returns:
        {
            "total": int,
            "correct": int,
            "accuracy": float,
            "results": list[dict],
            "confusion_matrix": dict,
        }
    """
    # Load dataset
    with open(dataset_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)
    
    logger.info(f"📊 Evaluating {len(dataset)} images from {dataset_path}")
    logger.info("=" * 60)
    
    results = []
    correct_count = 0
    confusion = {}  # {expected: {predicted: count}}
    
    for i, item in enumerate(dataset):
        image_url = item.get("image_url", "")
        expected = item.get("expected_product", "Unknown")
        description = item.get("description", "")
        
        if verbose:
            logger.info(f"\n[{i+1}/{len(dataset)}] Testing: {expected}")
        
        result = await evaluate_single_image(image_url, expected, description, verbose)
        results.append(result)
        
        if result["correct"]:
            correct_count += 1
        
        # Update confusion matrix
        expected_key = expected.lower()
        predicted_key = result["predicted"].lower() if result["predicted"] else "none"
        
        if expected_key not in confusion:
            confusion[expected_key] = {}
        if predicted_key not in confusion[expected_key]:
            confusion[expected_key][predicted_key] = 0
        confusion[expected_key][predicted_key] += 1
        
        # Small delay to avoid rate limiting
        await asyncio.sleep(0.5)
    
    accuracy = correct_count / len(dataset) if dataset else 0.0
    
    return {
        "total": len(dataset),
        "correct": correct_count,
        "accuracy": accuracy,
        "results": results,
        "confusion_matrix": confusion,
        "timestamp": datetime.now().isoformat(),
    }


def print_report(evaluation: dict[str, Any]) -> None:
    """Print evaluation report."""
    logger.info("\n" + "=" * 60)
    logger.info("📊 VISION EVALUATION REPORT")
    logger.info("=" * 60)
    
    accuracy = evaluation["accuracy"]
    total = evaluation["total"]
    correct = evaluation["correct"]
    
    status = "✅ PASS" if accuracy >= 0.9 else "❌ FAIL"
    logger.info(f"\n{status} Accuracy: {accuracy:.1%} ({correct}/{total})")
    logger.info(f"Target: >= 90%")
    
    # Print confusion matrix
    confusion = evaluation.get("confusion_matrix", {})
    if confusion:
        logger.info("\n📋 Confusion Matrix:")
        logger.info("-" * 40)
        for expected, predictions in sorted(confusion.items()):
            logger.info(f"  {expected}:")
            for predicted, count in sorted(predictions.items(), key=lambda x: -x[1]):
                marker = "✅" if expected in predicted else "❌"
                logger.info(f"    {marker} → {predicted}: {count}")
    
    # Print failures
    failures = [r for r in evaluation["results"] if not r["correct"]]
    if failures:
        logger.info(f"\n❌ Failures ({len(failures)}):")
        logger.info("-" * 40)
        for f in failures[:10]:  # Show max 10
            logger.info(f"  Expected: {f['expected']}")
            logger.info(f"  Got: {f['predicted']} ({f['confidence']:.2f})")
            logger.info(f"  URL: {f['image_url']}")
            logger.info("")
    
    logger.info("=" * 60)


def save_report(evaluation: dict[str, Any], output_path: str) -> None:
    """Save evaluation report to JSON."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(evaluation, f, ensure_ascii=False, indent=2)
    logger.info(f"📁 Report saved to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate vision agent accuracy")
    parser.add_argument(
        "--dataset",
        type=str,
        default="data/eval/vision_test_set.json",
        help="Path to evaluation dataset JSON",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/eval/vision_eval_results.json",
        help="Path to save evaluation results",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed output for each image",
    )
    args = parser.parse_args()
    
    # Check dataset exists
    if not Path(args.dataset).exists():
        logger.error(f"❌ Dataset not found: {args.dataset}")
        logger.info("\nCreate a dataset file with format:")
        logger.info("""
[
    {
        "image_url": "https://example.com/laguna.jpg",
        "expected_product": "Лагуна",
        "description": "Плюшевий костюм з повною блискавкою"
    }
]
        """)
        return 1
    
    # Run evaluation
    evaluation = asyncio.run(run_evaluation(args.dataset, args.verbose))
    
    # Print and save report
    print_report(evaluation)
    
    # Ensure output directory exists
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    save_report(evaluation, args.output)
    
    # Return exit code based on accuracy
    return 0 if evaluation["accuracy"] >= 0.9 else 1


if __name__ == "__main__":
    exit(main())
