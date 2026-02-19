"""Tests for memory trigger states configuration."""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MEMORY_NODE_PATH = ROOT / "src/agents/langgraph/nodes/memory.py"
STATE_MACHINE_PATH = ROOT / "src/core/state_machine.py"


def _load_state_enum_values() -> set[str]:
    spec = importlib.util.spec_from_file_location("state_machine", STATE_MACHINE_PATH)
    assert spec and spec.loader

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    return {state.value for state in module.State}


def _extract_trigger_state_names() -> list[str]:
    tree = ast.parse(MEMORY_NODE_PATH.read_text(encoding="utf-8"))

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue

        if any(isinstance(target, ast.Name) and target.id == "MEMORY_TRIGGER_STATES" for target in node.targets):
            assert isinstance(node.value, ast.Set)

            members: list[str] = []
            for elt in node.value.elts:
                assert isinstance(elt, ast.Attribute)
                assert isinstance(elt.value, ast.Name) and elt.value.id == "State"
                members.append(elt.attr)
            return members

    raise AssertionError("MEMORY_TRIGGER_STATES was not found")


def test_memory_trigger_states_are_defined_via_state_enum_and_are_valid():
    valid_states = _load_state_enum_values()
    trigger_member_names = _extract_trigger_state_names()

    for member_name in trigger_member_names:
        assert member_name in valid_states
