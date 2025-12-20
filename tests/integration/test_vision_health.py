"""
Vision Health Tests
====================

Validates integrity of generated vision artifacts (test_set.json).
These tests run WITHOUT calling LLM or DB — pure schema/data checks.

Run:
    pytest tests/test_vision_health.py -v
"""

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------

TEST_SET_PATH = Path(__file__).parents[2] / "data" / "vision" / "generated" / "test_set.json"
CANONICAL_NAMES_PATH = (
    Path(__file__).parents[2] / "data" / "vision" / "generated" / "canonical_names.json"
)


@pytest.fixture(scope="module")
def test_set() -> list[dict]:
    """Load test_set.json."""
    if not TEST_SET_PATH.exists():
        pytest.fail(f"Test set not found at {TEST_SET_PATH}")
    with open(TEST_SET_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def canonical_names() -> dict:
    """Load canonical_names.json."""
    if not CANONICAL_NAMES_PATH.exists():
        pytest.fail(f"Canonical names not found at {CANONICAL_NAMES_PATH}")
    with open(CANONICAL_NAMES_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# HEALTH TESTS
# ---------------------------------------------------------------------------


class TestVisionArtifactsExist:
    """Verify all generated artifacts exist."""

    def test_test_set_exists(self):
        assert TEST_SET_PATH.exists(), f"Missing: {TEST_SET_PATH}"

    def test_canonical_names_exists(self):
        assert CANONICAL_NAMES_PATH.exists(), f"Missing: {CANONICAL_NAMES_PATH}"

    def test_model_rules_exists(self):
        path = TEST_SET_PATH.parent / "model_rules.yaml"
        assert path.exists(), f"Missing: {path}"

    def test_vision_guide_exists(self):
        path = TEST_SET_PATH.parent / "vision_guide.json"
        assert path.exists(), f"Missing: {path}"


class TestTestSetIntegrity:
    """Validate test_set.json structure and data."""

    def test_not_empty(self, test_set):
        assert len(test_set) > 0, "test_set.json is empty"

    def test_minimum_products(self, test_set):
        """Should have at least 10 test cases."""
        assert len(test_set) >= 10, f"Only {len(test_set)} test cases, expected >= 10"

    def test_required_fields(self, test_set):
        """Each test case must have required fields."""
        required = {"id", "product_id", "expected_product", "expected_color"}
        for i, case in enumerate(test_set):
            missing = required - set(case.keys())
            assert not missing, f"Test case {i} ({case.get('id', '?')}) missing: {missing}"

    def test_product_ids_are_integers(self, test_set):
        """product_id must be int."""
        for case in test_set:
            assert isinstance(case["product_id"], int), f"{case['id']}: product_id not int"

    def test_prices_valid(self, test_set):
        """Price must be positive int or valid range."""
        for case in test_set:
            if "expected_price" in case:
                assert isinstance(case["expected_price"], (int, float)), (
                    f"{case['id']}: bad price type"
                )
                assert case["expected_price"] >= 0, f"{case['id']}: negative price"
            elif "expected_price_range" in case:
                rng = case["expected_price_range"]
                assert "min" in rng and "max" in rng, f"{case['id']}: bad price_range"
                assert rng["min"] <= rng["max"], f"{case['id']}: min > max"

    def test_image_urls_not_empty(self, test_set):
        """image_url should be present (can be empty for some)."""
        with_url = [c for c in test_set if c.get("image_url")]
        assert len(with_url) >= len(test_set) * 0.8, "Too many test cases without image_url"


class TestCanonicalNamesIntegrity:
    """Validate canonical_names.json structure."""

    def test_has_canonical_names_key(self, canonical_names):
        assert "canonical_names" in canonical_names

    def test_has_valid_product_names_key(self, canonical_names):
        assert "valid_product_names" in canonical_names

    def test_mappings_not_empty(self, canonical_names):
        assert len(canonical_names["canonical_names"]) > 0

    def test_valid_names_not_empty(self, canonical_names):
        assert len(canonical_names["valid_product_names"]) > 0

    def test_all_mappings_point_to_valid_names(self, canonical_names):
        """Every mapping value must be in valid_product_names."""
        valid = set(canonical_names["valid_product_names"])
        for key, value in canonical_names["canonical_names"].items():
            assert value in valid, f"Mapping '{key}' -> '{value}' not in valid_product_names"


class TestCrossValidation:
    """Cross-validate test_set against canonical_names."""

    def test_all_expected_products_are_canonical(self, test_set, canonical_names):
        """Every expected_product in test_set must be a valid canonical name."""
        valid = set(canonical_names["valid_product_names"])
        for case in test_set:
            product = case["expected_product"]
            assert product in valid, f"Test case '{case['id']}': '{product}' not canonical"
