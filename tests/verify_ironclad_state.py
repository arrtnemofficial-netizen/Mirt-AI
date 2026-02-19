
import sys
import os
sys.path.append(os.getcwd())
try:
    from src.agents.langgraph.state import create_initial_state
    from src.core.state_schema import StateSchema
except ImportError:
    print("❌ Failed to import!")
    sys.exit(1)

def test_full_dict_emulation():
    print("🛡️ Testing Ironclad State (Dict Emulation)...")
    
    state = create_initial_state(session_id="ironclad_test")
    
    # 1. Assignment
    state['new_key'] = 'custom_val'
    assert state['new_key'] == 'custom_val'
    assert state['legacy_extra']['new_key'] == 'custom_val'
    
    # 2. Update()
    state.update({'dialog_phase': 'TEST_PHASE', 'trace_id': 'xyz'})
    assert state.dialog_phase == 'TEST_PHASE'
    assert state['trace_id'] == 'xyz'
    
    # 3. Keys / Items / Values
    keys = list(state.keys())
    assert 'session_id' in keys
    assert 'legacy_extra' in keys
    
    # 4. Length
    assert len(state) > 10
    
    # 5. Iteration
    items = dict(state)
    assert items['session_id'] == "ironclad_test"
    
    print("✅ Concrete (Zhiezobetonno) Compatibility Proven!")

    print("\n🛡️ Testing to_schema recursion...")
    from src.agents.langgraph.routers.base import to_schema
    # Converting Schema -> Schema should work now
    schema1 = to_schema(state)
    schema2 = to_schema(schema1) 
    assert schema2.session_id == schema1.session_id
    print("✅ to_schema recursion worked!")


if __name__ == "__main__":
    test_full_dict_emulation()
