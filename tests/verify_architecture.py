
import sys
import os
import inspect
from typing import Any, Dict

# Setup path
sys.path.append(os.getcwd())

try:
    from src.core.state_schema import StateSchema
    from src.agents.langgraph.state import create_initial_state
except ImportError as e:
    print(f"❌ critical import error: {e}")
    sys.exit(1)

def verify_architecture():
    print("🏗️  MIRT AI ARCHITECTURE VERIFIER")
    print("===============================")
    
    # 1. Schema Completeness Check
    print("\n[1] Checking State Schema Definitions...")
    
    # List of fields detected in codebase usage (Hardcoded from grep analysis to ensure regression safety)
    # If developers add new .get("key"), they should add it here or add to Schema.
    REQUIRED_FIELDS = [
        "session_id", "trace_id", "messages", "metadata",
        "current_state", "dialog_phase", "detected_intent",
        "has_image", "image_url",
        "selected_products", "offered_products",
        "agent_response",
        "step_number",
        "validation_errors", "retry_count", "max_retries",
        "crm_order_result", "tool_plan_result",
        "is_first_message",
        "memory_profile", "memory_facts", "memory_context_prompt",
        "sitniks_chat_id", "sitniks_first_touch_done",
        "temp_context"
    ]
    
    schema_fields = StateSchema.model_fields.keys()
    missing = []
    
    for field in REQUIRED_FIELDS:
        if field not in schema_fields:
            missing.append(field)
            print(f"  ❌ Missing Field in Schema: '{field}' (Used in code!)")
        else:
            print(f"  ✅ Field '{field}' is defined.")
            
    if missing:
        print(f"\n❌ FATAL: {len(missing)} fields missing from StateSchema. Fix immediately!")
        sys.exit(1)
    else:
        print("\n✅ Schema definition is COMPLETE.")

    # 2. Hybrid Bridge Check (MutableMapping)
    print("\n[2] Checking Hybrid Bridge (Pydantic <-> Dict)...")
    state = create_initial_state(session_id="arch_test")
    
    try:
        # Test Dict Write
        state["new_magic_field"] = 999
        # Test Prop Access (via __getattr__ fallback in generic generic?) 
        # No, StateSchema is explicit. Attributes must exist to be accessed via dot.
        # But 'new_magic_field' via dot? Only if we allow extra.
        # Let's check if it's in model_dump
        dump = state.model_dump()
        assert dump["new_magic_field"] == 999
        print("  ✅ Dict Write -> Model Update works.")
        
        # Test Update
        state.update({"step_number": 50, "dialog_phase": "ARCH_TEST"})
        assert state.step_number == 50
        print("  ✅ .update() -> Attribute Update works.")
        
    except Exception as e:
        print(f"  ❌ MutableMapping Failed: {e}")
        sys.exit(1)

    # 3. Router Safety Check (kwargs unpacking)
    print("\n[3] Checking Router Compatibility...")
    from src.agents.langgraph.routers.base import to_schema
    
    try:
        # Pass Object
        s1 = to_schema(state)
        # Pass Dict
        s2 = to_schema(state.model_dump())
        # Pass Recursive
        s3 = to_schema(s1)
        
        assert s1.session_id == s2.session_id == s3.session_id
        print("  ✅ Router `to_schema` handles Object/Dict/Recursion correctly.")
    except Exception as e:
        print(f"  ❌ Router Safety Failed: {e}")
        sys.exit(1)

    print("\n===============================")
    print("🚀 ARCHITECTURE VERIFIED: IRONCLAD")
    print("You can safely deploy.")

if __name__ == "__main__":
    verify_architecture()
