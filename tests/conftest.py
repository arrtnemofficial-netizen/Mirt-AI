import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch):
    """
    Make tests deterministic:
    - ensure we don't accidentally rely on developer machine env
    - allow tests to override env vars safely
    """
    # Keep existing env, but provide a predictable default for tokens
    monkeypatch.setenv("MANYCHAT_VERIFY_TOKEN", os.getenv("MANYCHAT_VERIFY_TOKEN", "test-token"))
    yield


@pytest.fixture()
def reset_sitniks_singleton(monkeypatch: pytest.MonkeyPatch):
    """Reset SitniksChatService singleton between tests."""
    import src.integrations.crm.sitniks_chat_service as mod

    monkeypatch.setattr(mod, "_chat_service", None, raising=False)
    yield
    monkeypatch.setattr(mod, "_chat_service", None, raising=False)

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
GOLDEN_DATA_PATH = TESTS_DIR / "data" / "golden_data.yaml"


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
