#!/usr/bin/env python
"""Lint registry keys referenced in code.

Scans src/ for registry.get("...") and load_yaml_from_registry("...")
and verifies that each key resolves to an existing prompt file.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"

REGISTRY_GET_RE = re.compile(r"registry\.get\(\"([^\"]+)\"\)")
YAML_GET_RE = re.compile(r"load_yaml_from_registry\(\"([^\"]+)\"\)")


def _collect_keys() -> set[str]:
    keys: set[str] = set()
    for path in SRC_DIR.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        keys.update(REGISTRY_GET_RE.findall(text))
        keys.update(YAML_GET_RE.findall(text))
    return keys


def main() -> int:
    sys.path.insert(0, str(ROOT))
    try:
        from src.core.prompt_registry import registry
    except Exception as exc:
        print(f"Failed to import prompt_registry: {exc}")
        return 2

    missing: list[str] = []
    for key in sorted(_collect_keys()):
        try:
            registry.get(key)
        except Exception:
            missing.append(key)

    if missing:
        print("Missing prompt keys:")
        for key in missing:
            print(f"- {key}")
        return 1

    print("OK: all registry keys resolved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
