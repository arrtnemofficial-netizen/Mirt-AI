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
        Get a prompt by key (e.g., 'main.main', 'state.STATE_0_INIT').
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
            path = self.base_dir / "vision_agent" / f"{name}.md"
            if name == "main":
                path = self.base_dir / "vision_agent" / "vision_main.md"
        else:
            # Try generic match
            path = self.base_dir / category / f"{name}.md"

        # Backward-compatible fallback for legacy vision path
        if category == "vision" and not path.exists():
            legacy = self.base_dir / "vision" / f"{name}.md"
            if name == "main":
                legacy = self.base_dir / "vision" / "vision_main.md"
            if legacy.exists():
                path = legacy

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


def get_snippet_by_header(header_name: str) -> list[str] | None:
    """Get snippet by exact header name from registry tables.

    Searches in:
    - system.snippets (dialogs)
    - system.fallbacks (errors)
    - system.intents (patterns)
    - system.system_messages (bot/notifications)
    """
    # Registry keys to search in order
    sources = [
        "system.snippets",
        "system.fallbacks",
        "system.intents",
        "system.system_messages",
        "system.vision",
        "system.automation",
    ]

    for source_key in sources:
        try:
            content = registry.get(source_key).content
        except Exception:
            continue

        if not content:
            continue

        # Parse file content
        lines = content.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]

            # Look for ### header with exact match
            if line.startswith("### ") and line[4:].strip() == header_name:
                # Found exact match! Extract the snippet body
                body_lines = []
                i += 1
                while i < len(lines) and not lines[i].startswith("### "):
                    body_lines.append(lines[i])
                    i += 1

                # Parse body: skip КОЛИ/НЕ КОЛИ lines, split by ---
                text_lines = []
                for bl in body_lines:
                    bl_stripped = bl.strip()
                    if bl_stripped.startswith("КОЛИ:") or bl_stripped.startswith("НЕ КОЛИ:"):
                        continue
                    text_lines.append(bl_stripped)

                # Join and split by ---
                full_text = "\n".join(text_lines).strip()
                if not full_text:
                    return None

                bubbles = [b.strip() for b in full_text.split("---") if b.strip()]
                if bubbles:
                    logger.debug("📋 Found snippet '%s' in %s", header_name, source_key)
                    return bubbles
                return None
            i += 1

    return None


def get_product_snippet(product_name: str) -> list[str] | None:
    """Get presentation snippet for a product from snippets.md.

    Returns list of bubbles (split by ---) or None if not found.
    Universal: works for ANY product that has a snippet in snippets.md.
    """
    try:
        content = registry.get("system.snippets").content
    except Exception:
        return None

    if not content:
        return None

    # Normalize product name for matching
    pn_lower = (product_name or "").lower().strip()
    if not pn_lower:
        return None

    # Extract key words (e.g., "сукня анна" -> ["сукня", "анна"])
    keywords = [w for w in pn_lower.split() if len(w) > 2]
    if not keywords:
        return None

    # Parse snippets.md - find sections matching product
    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for ### headers that contain product keywords
        if line.startswith("### "):
            header_lower = line[4:].lower()

            # Check if this header matches our product (all keywords present)
            if all(kw in header_lower for kw in keywords):
                # Found a match! Look for "презентація" or first snippet for this product
                if "презентація" in header_lower or "відповідь" in header_lower:
                    # Extract the snippet body (until next ### or EOF)
                    body_lines = []
                    i += 1
                    while i < len(lines) and not lines[i].startswith("### "):
                        body_lines.append(lines[i])
                        i += 1

                    # Parse body: skip КОЛИ/НЕ КОЛИ lines, split by ---
                    text_lines = []
                    for bl in body_lines:
                        bl_stripped = bl.strip()
                        if (
                            bl_stripped.startswith("КОЛИ:")
                            or bl_stripped.startswith("НЕ КОЛИ:")
                            or bl_stripped.startswith("ПРІОРИТЕТ:")
                        ):
                            continue
                        text_lines.append(bl_stripped)

                    # Join and split by ---
                    full_text = "\n".join(text_lines).strip()
                    if not full_text:
                        return None

                    bubbles = [b.strip() for b in full_text.split("---") if b.strip()]
                    if bubbles:
                        logger.info(
                            "📋 Found snippet for '%s': %d bubbles", product_name, len(bubbles)
                        )
                        return bubbles
                    return None
        i += 1

    return None
