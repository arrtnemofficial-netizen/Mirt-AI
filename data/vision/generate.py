#!/usr/bin/env python3
"""
MIRT Vision Artifacts Generator
================================

Читає products_master.yaml і генерує всі артефакти в generated/

Запуск:
    python data/vision/generate.py

    або з кореня проекту:
    python -m data.vision.generate
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


# Paths - все в одній папці!
VISION_DIR = Path(__file__).parent
MASTER_CATALOG = VISION_DIR / "products_master.yaml"
GENERATED_DIR = VISION_DIR / "generated"

# Output files
MODEL_RULES_OUTPUT = GENERATED_DIR / "model_rules.yaml"
VISION_GUIDE_OUTPUT = GENERATED_DIR / "vision_guide.json"
TEST_SET_OUTPUT = GENERATED_DIR / "test_set.json"
CANONICAL_NAMES_OUTPUT = GENERATED_DIR / "canonical_names.json"


def load_master_catalog() -> dict:
    """Load master catalog from YAML."""
    with open(MASTER_CATALOG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def compute_catalog_hash(catalog: dict) -> str:
    """Compute hash of catalog for version tracking."""
    catalog_str = json.dumps(catalog, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(catalog_str.encode()).hexdigest()[:12]


def generate_model_rules(catalog: dict) -> dict:
    """Generate model_rules.yaml content from master catalog."""
    products = catalog.get("products", {})
    decision_tree = catalog.get("decision_tree", {})

    rules = {
        "_generated": {
            "source": "products_master.yaml",
            "timestamp": datetime.now().isoformat(),
            "catalog_hash": compute_catalog_hash(catalog),
            "warning": "НЕ РЕДАГУЙ! Зміни в products_master.yaml → python generate.py",
        },
        "MODEL_RULES": {},
    }

    for product_key, product in products.items():
        name = product["name"]
        visual = product.get("visual", {})
        distinction = product.get("distinction", {})

        # Get price info
        if product.get("price_type") == "uniform":
            price_info = product.get("price")
        else:
            prices = product.get("prices_by_size", {})
            if prices:
                min_p = min(prices.values())
                max_p = max(prices.values())
                price_info = f"{min_p}-{max_p}"
            else:
                price_info = "N/A"

        # Get colors
        colors = list(product.get("colors", {}).keys())

        rule = {
            "category": product.get("category", ""),
            "fabric_type": visual.get("fabric_type", ""),
            "price": price_info,
            "visual_markers": visual.get("key_markers", []),
            "identify_by": distinction.get("unique_identifier", ""),
            "colors": colors,
        }

        # Add confusion info if exists
        if distinction.get("confused_with"):
            rule["confused_with"] = distinction["confused_with"]
            rule["how_to_distinguish"] = distinction.get("how_to_distinguish", "")
            rule["critical_check"] = distinction.get("critical_check", "")

        rules["MODEL_RULES"][name] = rule

    # Add decision tree
    rules["DECISION_TREE"] = _format_decision_tree(decision_tree)

    return rules


def _format_decision_tree(tree: dict) -> str:
    """Format decision tree as readable text for prompt."""
    lines = []

    for step_key in sorted(tree.keys()):
        step = tree[step_key]
        step_num = step_key.replace("step_", "")
        lines.append(f"{step_num}. {step['question']}")

        for opt in step.get("options", []):
            if "result" in opt:
                lines.append(f"   - {opt['condition']} → {opt['result']}")
            elif "next" in opt:
                next_step = opt["next"].replace("step_", "п.")
                lines.append(f"   - {opt['condition']} → див. {next_step}")

        lines.append("")

    return "\n".join(lines)


def generate_vision_guide(catalog: dict) -> dict:
    """Generate vision_guide.json content from master catalog."""
    products = catalog.get("products", {})

    guide = {
        "_generated": {
            "source": "products_master.yaml",
            "timestamp": datetime.now().isoformat(),
            "catalog_hash": compute_catalog_hash(catalog),
        },
        "visual_recognition_guide": {
            "description": "Детальні візуальні характеристики товарів MIRT",
            "products": {},
        },
    }

    for product_key, product in products.items():
        product_id = str(product["id"])
        visual = product.get("visual", {})
        distinction = product.get("distinction", {})

        guide_entry = {
            "name": product["name"],
            "colors": list(product.get("colors", {}).keys()),
            "key_features": {
                "fabric": visual.get("fabric_type", ""),
                "markers": visual.get("key_markers", []),
            },
            "recognition_by_angle": visual.get("recognition_by_angle", {}),
            "low_quality_markers": visual.get("low_quality_markers", []),
            "texture_description": visual.get("texture_description", ""),
            "distinction": {
                "confused_with": distinction.get("confused_with", []),
                "how_to_distinguish": distinction.get("how_to_distinguish", ""),
                "critical_check": distinction.get("critical_check", ""),
                "unique_identifier": distinction.get("unique_identifier", ""),
            },
        }

        guide["visual_recognition_guide"]["products"][product_id] = guide_entry

    return guide


def generate_test_set(catalog: dict) -> list:
    """Generate test_set.json content from master catalog."""
    products = catalog.get("products", {})
    test_cases = []

    for product_key, product in products.items():
        name = product["name"]
        colors = product.get("colors", {})

        # Get price
        if product.get("price_type") == "uniform":
            price = product.get("price", 0)
            price_range = None
        else:
            prices = product.get("prices_by_size", {})
            if prices:
                price = 0
                price_range = {"min": min(prices.values()), "max": max(prices.values())}
            else:
                price = 0
                price_range = None

        # Create test case for each color
        for color, color_info in colors.items():
            test_id = f"{product_key}_{color}".replace(" ", "_").lower()

            test_case = {
                "id": test_id,
                "product_id": product["id"],
                "image_url": color_info.get("photo_url", ""),
                "expected_product": name,
                "expected_color": color,
                "sku": color_info.get("sku", ""),
            }

            if price_range:
                test_case["expected_price_range"] = price_range
            else:
                test_case["expected_price"] = price

            visual = product.get("visual", {})
            test_case["description"] = f"{name} {color} - {visual.get('fabric_type', '')}"

            distinction = product.get("distinction", {})
            if distinction.get("critical_check"):
                test_case["critical_check"] = distinction["critical_check"]

            test_cases.append(test_case)

    return test_cases


def generate_canonical_names(catalog: dict) -> dict:
    """Generate canonical names mapping for fuzzy matching."""
    metadata = catalog.get("metadata", {})
    products = catalog.get("products", {})

    canonical = dict(metadata.get("canonical_names", {}))

    for product_key, product in products.items():
        name = product["name"]
        name_lower = name.lower()

        canonical[name_lower] = name

        if name_lower.startswith("костюм "):
            short_name = name_lower.replace("костюм ", "")
            canonical[short_name] = name

        if name_lower.startswith("сукня "):
            short_name = name_lower.replace("сукня ", "")
            canonical[short_name] = name

        for color in product.get("colors", {}).keys():
            with_color = f"{name_lower} {color}"
            canonical[with_color] = name

            if name_lower.startswith("костюм "):
                short_with_color = f"{name_lower.replace('костюм ', '')} {color}"
                canonical[short_with_color] = name

    return {
        "_generated": {
            "source": "products_master.yaml",
            "timestamp": datetime.now().isoformat(),
        },
        "canonical_names": canonical,
        "valid_product_names": list(set(canonical.values())),
    }


def save_yaml(data: dict, path: Path):
    """Save data as YAML."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"  ✅ {path.name}")


def save_json(data: Any, path: Path):
    """Save data as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  ✅ {path.name}")


def main():
    print("=" * 50)
    print("🔧 MIRT Vision Generator")
    print("=" * 50)

    print(f"\n📂 Loading: {MASTER_CATALOG.name}")
    catalog = load_master_catalog()

    products_count = len(catalog.get("products", {}))
    catalog_hash = compute_catalog_hash(catalog)

    print(f"📦 Products: {products_count}")
    print(f"🔑 Hash: {catalog_hash}")

    print(f"\n📁 Generating to: {GENERATED_DIR.name}/")
    GENERATED_DIR.mkdir(exist_ok=True)

    # 1. Model rules
    model_rules = generate_model_rules(catalog)
    save_yaml(model_rules, MODEL_RULES_OUTPUT)

    # 2. Vision guide
    vision_guide = generate_vision_guide(catalog)
    save_json(vision_guide, VISION_GUIDE_OUTPUT)

    # 3. Test set
    test_set = generate_test_set(catalog)
    save_json(test_set, TEST_SET_OUTPUT)
    print(f"     ({len(test_set)} test cases)")

    # 4. Canonical names
    canonical_names = generate_canonical_names(catalog)
    save_json(canonical_names, CANONICAL_NAMES_OUTPUT)
    print(f"     ({len(canonical_names['canonical_names'])} mappings)")

    print("\n" + "=" * 50)
    print("✅ DONE! Run tests: pytest tests/test_product_matcher.py -v")
    print("=" * 50)


if __name__ == "__main__":
    main()
