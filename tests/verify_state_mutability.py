
import sys
import os
sys.path.append(os.getcwd())
from src.agents.langgraph.state import create_initial_state

def test_state_mutability():
    print("🧪 Testing ConversationState Mutability...")
    
    state = create_initial_state(session_id="123")
    
    # 1. Test Assignment
    print("Trying assignment: state['trace_id'] = 'new_trace'")
    try:
        state['trace_id'] = 'new_trace'
        print("✅ Assignment worked!")
    except TypeError as e:
        print(f"❌ Assignment failed: {e}")
        sys.exit(1)
        
    # 2. Verify Update
    assert state.trace_id == 'new_trace'
    assert state['trace_id'] == 'new_trace'
    
    print("✅ All mutability checks passed!")

if __name__ == "__main__":
    test_state_mutability()
