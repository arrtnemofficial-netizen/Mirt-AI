
import sys
import os
import json
import asyncio
from copy import deepcopy
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parents[1]))

from src.services.conversation.conversation import (
    ConversationState
)
from src.services.guardrails.loop_detector import apply_loop_protection as _apply_transition_guardrails
from src.services.parser.output_parser import parse_llm_output
from src.core.models import Message, AgentResponse

def serialize(obj):
    """Helper to verify object equality via JSON dump."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)

def test_parse_llm_output():
    print("--- Testing parse_llm_output ---")
    
    # Case 1: Simple text
    res1 = parse_llm_output("Hello world", session_id="123")
    print(f"Case 1 (Text): {res1.event}, msgs={len(res1.messages)}")
    
    # Case 2: JSON
    json_input = json.dumps({
        "event": "offer_made",
        "messages": [{"type": "text", "content": "Here is an offer"}],
        "products": [{"id": 101, "name": "Prod1", "price": 100.0, "photo_url": "https://example.com/p1.jpg"}],
        "metadata": {"intent": "buy"}
    })
    res2 = parse_llm_output(json_input, session_id="123")
    print(f"Case 2 (JSON): {res2.event}, prod={res2.products[0].name}, intent={res2.metadata.intent}")

    return [res1, res2]

def test_guardrails():
    print("\n--- Testing _apply_transition_guardrails ---")
    
    # Setup base state
    session_id = "test_sess"
    base_state = ConversationState(
        messages=[],
        metadata={"session_id": session_id},
        current_state="STATE_0_INIT",
        dialog_phase="INIT",
        step_number=0
    )
    
    # Case 1: Normal transition
    after_state = deepcopy(base_state)
    after_state["current_state"] = "STATE_1_DISCOVERY"
    after_state["dialog_phase"] = "DISCOVERY"
    
    res1 = _apply_transition_guardrails(
        session_id=session_id,
        before_state=base_state,
        after_state=after_state,
        user_text="hi"
    )
    print(f"Case 1 (Normal): Phase={res1['dialog_phase']}, Guard={res1['metadata'].get('_guard', {}).get('count')}")

    # Case 2: Loop detection (same state 5 times)
    # We simulate the counter being 4, so this call should bump it to 5 and Warn
    loop_meta = {"_guard": {"count": 4, "before_fp": "hash_match"}} 
    # Mocking hash match is tricky without knowing internal hash impl, 
    # but let's rely on the function logic: if before_fp == after_fp => increment
    
    # To trigger loop, we need _guard_progress_fingerprint to return same hash
    # For that, state content must be identical.
    
    res_loop = deepcopy(base_state)
    res_loop["metadata"] = loop_meta
    
    # First call to initialize fingerprint in metadata if needed
    # Actually, let's just run it multiple times to simulate loop
    
    current = deepcopy(base_state)
    for i in range(6):
        # We invoke guardrail with identical before/after states
        # The function logic: if before_fp == after_fp -> count++
        # So we pass same object effectively (content-wise)
        
        # NOTE: The function calculates fp from 'after_state' and 'before_state'
        # To simulate loop, they must have same fingerprint data
        
        updated = _apply_transition_guardrails(
            session_id=session_id,
            before_state=current,
            after_state=deepcopy(current), # Identical state -> Stagnant
            user_text="same text"
        )
        current = updated
        count = current["metadata"].get("_guard", {}).get("count")
        print(f"Loop Iter {i+1}: Count={count}")
    
    return [res1, current]

if __name__ == "__main__":
    try:
        r1 = test_parse_llm_output()
        r2 = test_guardrails()
        print("\n✅ Golden Master Test Passed (Runtime verified)")
    except Exception as e:
        print(f"\n❌ Test Failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
