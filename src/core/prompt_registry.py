# src/core/prompt_registry.py

import logging
from pathlib import Path
from typing import Any

# Pydantic is assumed to be available
from pydantic import BaseModel


logger = logging.getLogger(__name__)

class PromptConfig(BaseModel):
    key: str
    content: str
    metadata: dict[str, Any] = {}
    path: Path

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
            path = self.base_dir / "vision" / f"{name}.md" # Assuming vision_main -> vision.main
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

        config = PromptConfig(
            key=key,
            content=content,
            path=path,
            metadata={} # Could extract frontmatter later
        )

        self._cache[key] = config
        return config

    def _load_file(self, path: Path) -> str:
        with open(path, encoding="utf-8") as f:
            return f.read()

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
