"""
Tool Planner - вибір інструментів у коді.
=========================================
Винесення логіки вибору tool з промпта в код.
LLM отримує вже tool_result або інструкцію.

Логіка (EMBEDDED CATALOG MODE):
- Supabase tools ВИМКНЕНІ.
- Завжди повертає instruction: "Використовуй EMBEDDED CATALOG з промпта."
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.core.state_machine import State, Intent, ToolName

logger = logging.getLogger(__name__)


# =============================================================================
# TOOL PLAN
# =============================================================================

@dataclass
class ToolCall:
    """Single tool call specification."""
    tool: ToolName
    params: Dict[str, Any]
    reason: str  # Why this tool was selected


@dataclass
class ToolPlan:
    """Plan of tool calls to execute before LLM."""
    calls: List[ToolCall] = field(default_factory=list)
    skip_llm_tools: bool = False  # If True, LLM should not call tools itself
    instruction: str = ""  # Instruction for LLM about tool results
    
    @property
    def has_tools(self) -> bool:
        return len(self.calls) > 0
    
    def add_call(self, tool: ToolName, params: Dict[str, Any], reason: str) -> None:
        self.calls.append(ToolCall(tool=tool, params=params, reason=reason))


# =============================================================================
# TOOL PLANNER
# =============================================================================

class ToolPlanner:
    """
    Determines which tools to call based on input.
    Runs BEFORE LLM to pre-fetch data.
    """
    
    @classmethod
    def create_plan(
        cls,
        text: str,
        image_url: Optional[str],
        current_state: State,
        intent: Optional[Intent] = None,
        product_id: Optional[int] = None,
    ) -> ToolPlan:
        """
        Create tool execution plan based on input.
        
        EMBEDDED CATALOG MODE:
        Always returns no tools. Instruction points to Embedded Catalog.
        """
        plan = ToolPlan()
        
        # Force skip tools and use prompt catalog
        plan.skip_llm_tools = True
        plan.instruction = (
            "CATALOG MODE: Інструменти пошуку вимкнені. "
            "Використовуй EMBEDDED CATALOG (Block 2) в промпті для пошуку товарів, "
            "цін та розмірів. "
            "Якщо товар не знайдено в промпті - його немає."
        )
        
        return plan


# =============================================================================
# TOOL EXECUTOR
# =============================================================================

async def execute_tool_plan(plan: ToolPlan) -> Dict[str, Any]:
    """
    Execute tool plan and return results.
    
    EMBEDDED MODE:
    Returns empty success result.
    """
    # Supabase imports removed intentionally
    
    results = {
        "tool_results": [],
        "instruction": plan.instruction,
        "success": True,
        "errors": [],
    }
    
    return results
