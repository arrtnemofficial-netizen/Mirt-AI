import os
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml


# Psycopg async doesn't support ProactorEventLoop on Windows.
if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Add project root to path
root = Path(__file__).resolve().parents[1]
project_root = str(root)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Set environment variables for testing
os.environ["CELERY_EAGER"] = "true"  # Enable eager mode for tests

# Setup Paths
TESTS_DIR = Path(__file__).parent
GOLDEN_DATA_PATH = TESTS_DIR / "golden_data.yaml"

# No shared pytest plugins loaded (mocks are disabled)


@dataclass
class TestCase:
    id: str
    input: str
    expected_state: str = None
    context_state: str = None
    must_contain: list[str] = None
    must_not_contain: list[str] = None


class GoldenLoader:
    @staticmethod
    def load_suite() -> list[dict]:
        if not GOLDEN_DATA_PATH.exists():
            return []

        with open(GOLDEN_DATA_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("suites", [])

    @staticmethod
    def extract_cases() -> list[TestCase]:
        suites = GoldenLoader.load_suite()
        cases = []
        for suite in suites:
            for c in suite["cases"]:
                cases.append(
                    TestCase(
                        id=c.get("id"),
                        input=c.get("input"),
                        expected_state=c.get("expected_state"),
                        context_state=c.get("context_state"),
                        must_contain=c.get("must_contain", []),
                        must_not_contain=c.get("must_not_contain", []),
                    )
                )
        return cases
