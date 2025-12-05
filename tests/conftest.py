import sys
from pathlib import Path
import yaml
from typing import List, Dict
from dataclasses import dataclass
import pytest

# Add project root to path
root = Path(__file__).resolve().parents[1]
project_root = str(root)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Setup Paths
TESTS_DIR = Path(__file__).parent
GOLDEN_DATA_PATH = TESTS_DIR / "data" / "golden_data.yaml"

@dataclass
class TestCase:
    id: str
    input: str
    expected_state: str = None
    context_state: str = None
    must_contain: List[str] = None
    must_not_contain: List[str] = None

class GoldenLoader:
    @staticmethod
    def load_suite() -> List[Dict]:
        if not GOLDEN_DATA_PATH.exists():
            return []
        
        with open(GOLDEN_DATA_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("suites", [])

    @staticmethod
    def extract_cases() -> List[TestCase]:
        suites = GoldenLoader.load_suite()
        cases = []
        for suite in suites:
            for c in suite["cases"]:
                cases.append(TestCase(
                    id=c.get("id"),
                    input=c.get("input"),
                    expected_state=c.get("expected_state"),
                    context_state=c.get("context_state"),
                    must_contain=c.get("must_contain", []),
                    must_not_contain=c.get("must_not_contain", [])
                ))
        return cases
