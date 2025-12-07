# src/core/prompt_registry.py
"""
Prompt Registry - Single Source of Truth for all prompts.
==========================================================

Versioning convention:
- Each prompt file can have a version comment at the top: `<!-- version: 1.0 -->`
- Or in YAML: `# version: 1.0`
- Version is tracked in metadata and logged for observability

Changes to prompts should:
1. Increment version in the file
2. NOT change OUTPUT_CONTRACT schema (only text/examples)
"""

import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel


logger = logging.getLogger(__name__)

# Version extraction patterns
VERSION_PATTERN_MD = re.compile(r"<!--\s*version:\s*([\d.]+)\s*-->", re.IGNORECASE)
VERSION_PATTERN_YAML = re.compile(r"#\s*version:\s*([\d.]+)", re.IGNORECASE)
VERSION_PATTERN_GENERIC = re.compile(r"version[:\s]+([\d.]+)", re.IGNORECASE)


class PromptConfig(BaseModel):
    key: str
    content: str
    metadata: dict[str, Any] = {}
    path: Path
    version: str = "1.0"  # Default version


class PromptRegistry:
    """
    Single Source of Truth for all prompts.
    Loads prompts from data/prompts structure.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.base_dir = Path(__file__).parent.parent.parent / "data" / "prompts"
        self._cache: dict[str, PromptConfig] = {}
        self._initialized = True

    def get(self, key: str) -> PromptConfig:
        """
        Get a prompt by key (e.g., 'system.main', 'state.STATE_0_INIT').
        """
        if key in self._cache:
            return self._cache[key]

        parts = key.split(".")
        if len(parts) < 2:
            raise ValueError(f"Invalid prompt key format: {key}. Expected 'category.name'")

        category, name = parts[0], parts[1]

        if category == "system":
            path = self.base_dir / "system" / f"{name}.md"
        elif category == "state":
            path = self.base_dir / "states" / f"{name}.md"
        elif category == "vision":
            path = self.base_dir / "vision" / f"{name}.md"  # Assuming vision_main -> vision.main
            if name == "main":
                path = self.base_dir / "vision" / "vision_main.md"
        else:
            # Try generic match
            path = self.base_dir / category / f"{name}.md"

        if not path.exists():
            # Try yaml?
            path_yaml = path.with_suffix(".yaml")
            if path_yaml.exists():
                path = path_yaml
            else:
                raise FileNotFoundError(f"Prompt file not found for key: {key} at {path}")

        content = self._load_file(path)
        version = self._extract_version(content, path)

        config = PromptConfig(
            key=key,
            content=content,
            path=path,
            version=version,
            metadata={"version": version, "file": str(path.name)},
        )

        self._cache[key] = config
        logger.debug("Loaded prompt %s@v%s from %s", key, version, path.name)
        return config

    def _load_file(self, path: Path) -> str:
        with open(path, encoding="utf-8") as f:
            return f.read()

    def _extract_version(self, content: str, path: Path) -> str:
        """Extract version from prompt content."""
        # Check first 500 chars for version comment
        header = content[:500]

        # Try MD format: <!-- version: 1.0 -->
        match = VERSION_PATTERN_MD.search(header)
        if match:
            return match.group(1)

        # Try YAML format: # version: 1.0
        match = VERSION_PATTERN_YAML.search(header)
        if match:
            return match.group(1)

        # Try generic: version: 1.0
        match = VERSION_PATTERN_GENERIC.search(header)
        if match:
            return match.group(1)

        # Default version
        return "1.0"

    def get_version(self, key: str) -> str:
        """Get prompt version by key."""
        return self.get(key).version

    def get_all_versions(self) -> dict[str, str]:
        """Get all loaded prompt versions."""
        return {k: v.version for k, v in self._cache.items()}


# Global Registry Instance
registry = PromptRegistry()


def validate_all_states_have_prompts() -> list[str]:
    """
    Validate that all FSM states have corresponding prompt files.
    Returns list of missing states (empty = all good).

    Call this at app startup to catch misconfigurations early.
    """
    from src.core.state_machine import State

    missing = []
    for state in State:
        try:
            registry.get(f"state.{state.value}")
        except FileNotFoundError:
            missing.append(state.value)

    if missing:
        logger.warning("Missing prompt files for states: %s", missing)

    return missing
