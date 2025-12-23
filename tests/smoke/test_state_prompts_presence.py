"""
SMOKE: Test all required state prompts exist.
============================================
Ensures all state prompts and payment sub-phases are present in data/prompts/states/.
This prevents runtime errors in production when prompts are missing.
"""

import os
from pathlib import Path

import pytest

from src.agents.langgraph.state_prompts import PAYMENT_SUB_PHASES, validate_payment_subphase_prompts
from src.core.state_machine import State


@pytest.mark.smoke
@pytest.mark.critical
class TestStatePromptsPresence:
    """Verify all required state prompts exist."""

    @pytest.fixture
    def prompts_dir(self) -> Path:
        """Path to state prompts directory."""
        project_root = Path(__file__).resolve().parents[2]
        return project_root / "data" / "prompts" / "states"

    def test_all_fsm_states_have_prompts(self, prompts_dir: Path):
        """All FSM states must have corresponding .md prompt files."""
        missing = []
        for state in State:
            prompt_file = prompts_dir / f"{state.value}.md"
            if not prompt_file.exists():
                missing.append(state.value)

        assert not missing, (
            f"Missing prompt files for states: {missing}. "
            f"Create data/prompts/states/{{state}}.md for each missing state."
        )

    def test_payment_subphases_have_prompts(self, prompts_dir: Path):
        """All payment sub-phases must have corresponding .md prompt files."""
        missing = []
        for sub_phase_key in PAYMENT_SUB_PHASES.values():
            prompt_file = prompts_dir / f"{sub_phase_key}.md"
            if not prompt_file.exists():
                missing.append(sub_phase_key)

        assert not missing, (
            f"Missing prompt files for payment sub-phases: {missing}. "
            f"Create data/prompts/states/{{sub_phase}}.md for each missing sub-phase."
        )

    def test_payment_subphase_validation_function(self):
        """validate_payment_subphase_prompts should return empty list if all present."""
        missing = validate_payment_subphase_prompts()
        assert missing == [], (
            f"validate_payment_subphase_prompts() found missing prompts: {missing}. "
            f"Create data/prompts/states/{{sub_phase}}.md for each."
        )

    def test_prompts_are_not_empty(self, prompts_dir: Path):
        """All prompt files must have content (not empty)."""
        empty = []
        for state in State:
            prompt_file = prompts_dir / f"{state.value}.md"
            if prompt_file.exists():
                content = prompt_file.read_text(encoding="utf-8").strip()
                if not content:
                    empty.append(state.value)

        # Check payment sub-phases too
        for sub_phase_key in PAYMENT_SUB_PHASES.values():
            prompt_file = prompts_dir / f"{sub_phase_key}.md"
            if prompt_file.exists():
                content = prompt_file.read_text(encoding="utf-8").strip()
                if not content:
                    empty.append(sub_phase_key)

        assert not empty, (
            f"Empty prompt files found: {empty}. "
            f"Each prompt file must contain instructions for the LLM."
        )

    def test_prompts_loadable_via_registry(self):
        """All prompts must be loadable via PromptRegistry."""
        from src.core.prompt_registry import registry

        missing = []
        for state in State:
            try:
                prompt_config = registry.get(f"state.{state.value}")
                if not prompt_config.content.strip():
                    missing.append(f"{state.value} (empty)")
            except (FileNotFoundError, ValueError):
                missing.append(f"{state.value} (not found)")

        # Check payment sub-phases
        for sub_phase_key in PAYMENT_SUB_PHASES.values():
            try:
                prompt_config = registry.get(f"state.{sub_phase_key}")
                if not prompt_config.content.strip():
                    missing.append(f"{sub_phase_key} (empty)")
            except (FileNotFoundError, ValueError):
                missing.append(f"{sub_phase_key} (not found)")

        assert not missing, (
            f"Prompts not loadable via registry: {missing}. "
            f"Check data/prompts/states/ directory structure."
        )

