from __future__ import annotations

import ast
from pathlib import Path


MODULES_UNDER_RULE = [
    Path("src/agents/langgraph/nodes/agent.py"),
    Path("src/agents/langgraph/nodes/memory.py"),
    Path("src/agents/langgraph/routers/master.py"),
]


def _find_forbidden_state_get_calls(path: Path) -> list[tuple[int, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[tuple[int, int]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func = node.func
        if not isinstance(func, ast.Attribute):
            continue

        if func.attr != "get":
            continue

        target = func.value
        if isinstance(target, ast.Name) and target.id == "state":
            violations.append((node.lineno, node.col_offset))

    return violations


def test_business_state_access_uses_schema_fields() -> None:
    """Business logic must not use state.get(...); use StateSchema/ConversationState fields."""
    errors: list[str] = []

    for path in MODULES_UNDER_RULE:
        violations = _find_forbidden_state_get_calls(path)
        for line, col in violations:
            errors.append(f"{path}:{line}:{col} uses forbidden state.get(...)")

    assert not errors, "\n".join(errors)
