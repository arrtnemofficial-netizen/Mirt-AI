"""
FSM (Finite State Machine) - SSOT для переходов состояний.
==========================================================
Единый источник правды для:
- Переходов между состояниями (next_state из core.state_machine)
- Вычисления dialog_phase (не хранится, всегда вычисляется)
- Response policy (какие snippets отправлять и когда)
- Инварианты (no duplicate snippet, derived dialog_phase, one-turn-one-response)
"""

from .facts import compute_facts
from .transition_reducer import (
    TransitionDecision,
    compute_transition,
    derive_dialog_phase,
)

__all__ = [
    "TransitionDecision",
    "compute_transition",
    "derive_dialog_phase",
    "compute_facts",
]

