#!/usr/bin/env python3
"""
Architecture Guard - Import Validator.
======================================
This script validates that the codebase follows the Clean Architecture principle:
- Services MUST NOT import from Agents (dependency inversion)
- Core MUST NOT import from Services or Agents (foundation layer)

Run this as part of CI/CD or pre-commit hook.

Usage:
    python scripts/check_imports.py

Exit codes:
    0 - All imports valid
    1 - Forbidden imports detected
"""

import re
import sys
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Forbidden import patterns: (source_folder, forbidden_pattern, description)
FORBIDDEN_IMPORTS = [
    # Services should NOT import from Agents
    (
        "src/services",
        r"from src\.agents",
        "Services MUST NOT import from Agents (violates dependency inversion)",
    ),
    (
        "src/services",
        r"import src\.agents",
        "Services MUST NOT import from Agents (violates dependency inversion)",
    ),
    # Core should NOT import from Services or Agents
    (
        "src/core",
        r"from src\.services",
        "Core MUST NOT import from Services (core is foundation layer)",
    ),
    (
        "src/core",
        r"from src\.agents",
        "Core MUST NOT import from Agents (core is foundation layer)",
    ),
    # Integrations - CRM (Adapter) MUST NOT import Agents
    (
        "src/integrations/crm",
        r"from src\.agents",
        "CRM Integration (Adapter) MUST NOT import Agents (only Agents -> CRM allowed)",
    ),
    # Note: src/integrations/manychat IS allowed to import Agents because it acts as an Entrypoint (Driver)
    # Conf is the LOWEST layer - must not import from ANY src modules
    (
        "src/conf",
        r"from src\.services",
        "Conf MUST NOT import from Services (conf is foundation layer)",
    ),
    (
        "src/conf",
        r"from src\.agents",
        "Conf MUST NOT import from Agents (conf is foundation layer)",
    ),
    (
        "src/conf",
        r"from src\.core",
        "Conf MUST NOT import from Core (conf is the lowest layer)",
    ),
    (
        "src/conf",
        r"from src\.server",
        "Conf MUST NOT import from Server (conf is the lowest layer)",
    ),
    (
        "src/conf",
        r"from src\.workers",
        "Conf MUST NOT import from Workers (conf is the lowest layer)",
    ),
]


def check_file(filepath: Path) -> list[tuple[int, str, str]]:
    """Check a single file for forbidden imports.

    Returns list of (line_number, line_content, violation_description)
    """
    violations = []

    try:
        content = filepath.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return violations

    lines = content.splitlines()
    rel_path = filepath.relative_to(PROJECT_ROOT).as_posix()

    for source_folder, pattern, description in FORBIDDEN_IMPORTS:
        if not rel_path.startswith(source_folder):
            continue

        regex = re.compile(pattern)
        for line_num, line in enumerate(lines, 1):
            if regex.search(line):
                violations.append((line_num, line.strip(), description))

    return violations


def main() -> int:
    """Main entry point."""
    print("🔍 Architecture Guard - Checking imports...")
    print("=" * 60)

    all_violations: dict[str, list[tuple[int, str, str]]] = {}

    # Scan all Python files
    for py_file in PROJECT_ROOT.rglob("*.py"):
        # Skip __pycache__ and venv
        if "__pycache__" in str(py_file) or "venv" in str(py_file) or ".venv" in str(py_file):
            continue

        violations = check_file(py_file)
        if violations:
            rel_path = py_file.relative_to(PROJECT_ROOT).as_posix()
            all_violations[rel_path] = violations

    if not all_violations:
        print("✅ All imports are valid! Architecture is ironclad.")
        print("=" * 60)
        return 0

    # Report violations
    print("❌ FORBIDDEN IMPORTS DETECTED!")
    print("-" * 60)

    for filepath, violations in all_violations.items():
        print(f"\n📁 {filepath}")
        for line_num, line_content, description in violations:
            print(f"   Line {line_num}: {line_content}")
            print(f"   ⚠️  {description}")

    print("\n" + "=" * 60)
    print(f"Total: {sum(len(v) for v in all_violations.values())} violations in {len(all_violations)} files")
    print("🔴 Architecture violation! Fix imports before committing.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
