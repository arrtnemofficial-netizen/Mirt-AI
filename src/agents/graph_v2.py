"""
LangGraph v2 - багатовузлова архітектура.
=========================================
Послідовність вузлів:
1. moderation_node - перевірка безпеки вхідного повідомлення
2. tool_plan_node - планування та виконання інструментів
3. agent_node - виклик LLM агента
4. validation_node - валідація вихідних даних (price/photo_url/session_id)

Feature flag: USE_GRAPH_V2 в config
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from src.core.state_machine import State, EscalationLevel, Intent, normalize_state, get_next_state
from src.core.input_validator import InputMetadata, validate_input_metadata
from src.core.tool_planner import ToolPlanner, execute_tool_plan
from src.core.product_adapter import ProductAdapter
from src.core.models import AgentResponse, DebugInfo, Escalation, Message, Metadata
from src.services.moderation import ModerationResult, moderate_user_message
from src.services.observability import (
    log_agent_step,
    log_tool_execution,
    log_moderation_result,
    log_validation_result,
    track_metric,
    timed_operation,
)

if TYPE_CHECKING:
    from langgraph.graph.graph import CompiledGraph

logger = logging.getLogger(__name__)


# =============================================================================
# STATE
# =============================================================================

class ConversationStateV2(TypedDict):
    """Enhanced state for v2 graph."""
    messages: List[Dict[str, Any]]
    current_state: str
    metadata: Dict[str, Any]
    # V2 additions
    moderation_result: Optional[Dict[str, Any]]
    tool_plan_result: Optional[Dict[str, Any]]
    validation_errors: List[str]
    should_escalate: bool


# =============================================================================
# NODE 1: MODERATION
# =============================================================================

async def moderation_node(state: ConversationStateV2) -> ConversationStateV2:
    """
    Check user message for safety issues.
    Sets moderation_result and may trigger escalation.
    """
    start_time = time.perf_counter()
    session_id = state.get("metadata", {}).get("session_id", "")
    user_content = _get_latest_user_content(state["messages"])
    
    if not user_content:
        state["moderation_result"] = {"allowed": True, "flags": [], "redacted_text": ""}
        return state
    
    result = moderate_user_message(user_content)
    
    state["moderation_result"] = {
        "allowed": result.allowed,
        "flags": result.flags,
        "redacted_text": result.redacted_text,
        "reason": result.reason,
    }
    
    # Apply redaction if needed
    if result.redacted_text != user_content:
        _apply_redaction(state["messages"], result.redacted_text)
    
    # Track moderation flags
    state["metadata"]["moderation_flags"] = result.flags
    
    if not result.allowed:
        state["should_escalate"] = True
    
    # Log moderation result
    log_moderation_result(
        session_id=session_id,
        allowed=result.allowed,
        flags=result.flags,
        reason=result.reason,
    )
    track_metric("moderation_latency_ms", (time.perf_counter() - start_time) * 1000, {"allowed": str(result.allowed)})
    
    return state


# =============================================================================
# NODE 2: TOOL PLANNING
# =============================================================================

async def tool_plan_node(state: ConversationStateV2) -> ConversationStateV2:
    """
    Plan and execute tools BEFORE calling LLM.
    Reduces hallucination by providing real data.
    """
    start_time = time.perf_counter()
    session_id = state.get("metadata", {}).get("session_id", "")
    
    # Skip if moderation blocked
    if state.get("should_escalate"):
        return state
    
    user_content = _get_latest_user_content(state["messages"])
    metadata = validate_input_metadata(state.get("metadata", {}))
    
    # Check for image URL in metadata
    image_url = metadata.image_url
    
    # Create tool plan
    plan = ToolPlanner.create_plan(
        text=user_content or "",
        image_url=image_url,
        current_state=metadata.current_state,
        intent=metadata.intent,
    )
    
    if plan.has_tools:
        # Execute tools
        result = await execute_tool_plan(plan)
        state["tool_plan_result"] = result
        
        # Add tool results to metadata for agent
        state["metadata"]["tool_results"] = result.get("tool_results", [])
        state["metadata"]["tool_instruction"] = result.get("instruction", "")
        
        # Log tool execution
        total_results = sum(len(tr.get("result") or []) for tr in result.get("tool_results", []))
        for tool_result in result.get("tool_results", []):
            log_tool_execution(
                tool_name=tool_result.get("tool", "unknown"),
                success=result.get("success", False),
                latency_ms=(time.perf_counter() - start_time) * 1000,
                result_count=len(tool_result.get("result") or []),
            )
    else:
        state["tool_plan_result"] = {
            "tool_results": [],
            "instruction": plan.instruction,
            "success": True,
        }
    
    track_metric("tool_plan_latency_ms", (time.perf_counter() - start_time) * 1000)
    return state


# =============================================================================
# NODE 3: AGENT
# =============================================================================

async def agent_node_v2(state: ConversationStateV2, runner) -> ConversationStateV2:
    """
    Call LLM agent with prepared context.
    """
    start_time = time.perf_counter()
    session_id = state.get("metadata", {}).get("session_id", "")
    current_state = state.get("current_state", State.STATE_0_INIT.value)
    
    # Handle escalation from moderation
    if state.get("should_escalate"):
        moderation = state.get("moderation_result", {})
        response = _build_moderation_escalation(
            state["metadata"],
            current_state,
            moderation.get("reason", "Модерація заблокувала повідомлення"),
        )
        state["messages"].append({"role": "assistant", "content": response.model_dump_json()})
        
        log_agent_step(
            session_id=session_id,
            state=current_state,
            intent="moderation_blocked",
            event="escalation",
            moderation_blocked=True,
            escalation_level="L1",
            latency_ms=(time.perf_counter() - start_time) * 1000,
        )
        return state
    
    # Prepare metadata with tool results
    prepared_metadata = state.get("metadata", {}).copy()
    prepared_metadata["current_state"] = current_state
    
    # Call agent
    response = await runner(state["messages"], prepared_metadata)
    
    # Update state with FSM transition
    old_state = current_state
    intent_str = response.metadata.intent
    new_state = response.metadata.current_state
    
    state["current_state"] = new_state
    state["metadata"] = response.metadata.model_dump()
    state["messages"].append({"role": "assistant", "content": response.model_dump_json()})
    
    # Log agent step
    tool_plan = state.get("tool_plan_result") or {}
    tool_results = tool_plan.get("tool_results", [])
    total_products = sum(len(tr.get("result") or []) for tr in tool_results)
    
    log_agent_step(
        session_id=session_id,
        state=new_state,
        intent=intent_str,
        event=response.event,
        tool_results_count=total_products,
        latency_ms=(time.perf_counter() - start_time) * 1000,
        extra={"old_state": old_state, "products_count": len(response.products)},
    )
    
    return state


# =============================================================================
# NODE 4: VALIDATION
# =============================================================================

async def validation_node(state: ConversationStateV2) -> ConversationStateV2:
    """
    Validate agent output before sending.
    Checks:
    - products have valid price > 0
    - products have valid photo_url (https://)
    - session_id is preserved
    - no hallucinated products
    """
    session_id = state.get("metadata", {}).get("session_id", "")
    
    # Skip if already escalated
    if state.get("should_escalate"):
        return state
    
    errors: List[str] = []
    
    # Get latest assistant response
    assistant_response = _get_latest_assistant_response(state["messages"])
    if not assistant_response:
        return state
    
    # Validate products
    products = assistant_response.get("products", [])
    if products:
        valid_products, product_errors = ProductAdapter.batch_validate(products)
        
        for err in product_errors:
            errors.append(f"{err.field}: {err.message}")
        
        # Check against tool results (no hallucination)
        tool_results = state.get("tool_plan_result", {}).get("tool_results", [])
        tool_product_ids = set()
        for tr in tool_results:
            for item in (tr.get("result") or []):
                pid = item.get("id") or item.get("product_id")
                if pid:
                    tool_product_ids.add(int(pid))
        
        for p in products:
            pid = p.get("id") or p.get("product_id")
            if pid and int(pid) not in tool_product_ids and tool_product_ids:
                errors.append(f"Product {pid} not in tool results (possible hallucination)")
    
    # Validate session_id preserved
    input_session = state.get("metadata", {}).get("session_id", "")
    output_session = assistant_response.get("metadata", {}).get("session_id", "")
    if input_session and output_session != input_session:
        errors.append(f"session_id mismatch: input={input_session}, output={output_session}")
    
    state["validation_errors"] = errors
    
    # Log validation result
    log_validation_result(
        session_id=session_id,
        passed=len(errors) == 0,
        errors=errors,
    )
    
    return state


# =============================================================================
# NODE 5: STATE TRANSITION (FSM)
# =============================================================================

async def state_transition_node(state: ConversationStateV2) -> ConversationStateV2:
    """
    Apply FSM transition based on LLM's intent classification.
    This node ensures FSM is the source of truth for state transitions.
    """
    # Skip if escalated
    if state.get("should_escalate"):
        return state
    
    # Get current state and intent from metadata
    current_state_str = state.get("current_state", State.STATE_0_INIT.value)
    current_state = normalize_state(current_state_str)
    
    # Get intent from agent response
    assistant_response = _get_latest_assistant_response(state["messages"])
    if not assistant_response:
        return state
    
    intent_str = assistant_response.get("metadata", {}).get("intent", "UNKNOWN_OR_EMPTY")
    intent = Intent.from_string(intent_str)
    
    # Apply FSM transition
    new_state = get_next_state(current_state, intent)
    
    # Log state transition
    if new_state != current_state:
        logger.info(
            "FSM transition: %s + %s -> %s",
            current_state.value,
            intent.value,
            new_state.value,
        )
        track_metric("fsm_transitions", 1, {
            "from_state": current_state.value,
            "to_state": new_state.value,
            "intent": intent.value,
        })
    
    # Update state
    state["current_state"] = new_state.value
    
    return state


# =============================================================================
# HELPERS
# =============================================================================

def _get_latest_user_content(messages: List[Dict[str, Any]]) -> Optional[str]:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content")
    return None


def _get_latest_assistant_response(messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    import json
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            try:
                return json.loads(content)
            except:
                pass
    return None


def _apply_redaction(messages: List[Dict[str, Any]], redacted_text: str) -> None:
    for idx in range(len(messages) - 1, -1, -1):
        if messages[idx].get("role") == "user":
            messages[idx]["content"] = redacted_text
            break


def _build_moderation_escalation(metadata: Dict[str, Any], current_state: str, reason: str) -> AgentResponse:
    return AgentResponse(
        event="escalation",
        messages=[Message(content="Вибачте, я передаю запит колезі для перевірки.")],
        products=[],
        metadata=Metadata(
            session_id=metadata.get("session_id", ""),
            current_state=current_state,
            intent="moderation_blocked",
            escalation_level="L1",
            moderation_flags=metadata.get("moderation_flags", []),
        ),
        escalation=Escalation(
            level="L1",
            reason=reason,
            target="human_operator",
        ),
        debug=DebugInfo(state=current_state, intent="moderation_blocked"),
    )


# =============================================================================
# GRAPH BUILDER
# =============================================================================

def build_graph_v2(runner) -> "CompiledGraph":
    """
    Build v2 multi-node graph.
    
    Flow: moderation → tool_plan → agent → validation → state_transition → END
    """
    
    async def _moderation(state: ConversationStateV2) -> ConversationStateV2:
        return await moderation_node(state)
    
    async def _tool_plan(state: ConversationStateV2) -> ConversationStateV2:
        return await tool_plan_node(state)
    
    async def _agent(state: ConversationStateV2) -> ConversationStateV2:
        return await agent_node_v2(state, runner)
    
    async def _validation(state: ConversationStateV2) -> ConversationStateV2:
        return await validation_node(state)
    
    async def _state_transition(state: ConversationStateV2) -> ConversationStateV2:
        return await state_transition_node(state)
    
    graph = StateGraph(ConversationStateV2)
    
    # Add nodes (5 nodes total)
    graph.add_node("moderation", _moderation)
    graph.add_node("tool_plan", _tool_plan)
    graph.add_node("agent", _agent)
    graph.add_node("validation", _validation)
    graph.add_node("state_transition", _state_transition)
    
    # Define edges (sequential, no cycles)
    graph.set_entry_point("moderation")
    graph.add_edge("moderation", "tool_plan")
    graph.add_edge("tool_plan", "agent")
    graph.add_edge("agent", "validation")
    graph.add_edge("validation", "state_transition")
    graph.add_edge("state_transition", END)
    
    return graph.compile()


# =============================================================================
# LAZY GRAPH SINGLETON
# =============================================================================

_compiled_graph_v2: Optional["CompiledGraph"] = None


def get_graph_v2(runner=None) -> "CompiledGraph":
    """Get or create v2 compiled graph."""
    global _compiled_graph_v2
    if _compiled_graph_v2 is None:
        from src.agents.pydantic_agent import run_agent
        _compiled_graph_v2 = build_graph_v2(runner or run_agent)
    return _compiled_graph_v2


def get_active_graph():
    """
    Get the active graph based on USE_GRAPH_V2 feature flag.
    
    Returns v2 graph if USE_GRAPH_V2=True (default), otherwise v1.
    """
    from src.conf.config import settings
    
    if settings.USE_GRAPH_V2:
        logger.info("Using LangGraph v2 (5-node architecture)")
        return get_graph_v2()
    else:
        logger.info("Using LangGraph v1 (legacy)")
        from src.agents.graph import app as graph_v1
        return graph_v1
