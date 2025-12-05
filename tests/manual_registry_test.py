import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from src.core.prompt_registry import registry

def test_registry():
    print("Testing PromptRegistry...")
    
    # Test system prompt
    try:
        sys_prompt = registry.get("system.main")
        print(f"✅ Loaded system.main ({len(sys_prompt.content)} chars)")
    except Exception as e:
        print(f"❌ Failed to load system.main: {e}")

    # Test state prompt
    try:
        state_prompt = registry.get("state.STATE_0_INIT")
        print(f"✅ Loaded state.STATE_0_INIT ({len(state_prompt.content)} chars)")
    except Exception as e:
        print(f"❌ Failed to load state.STATE_0_INIT: {e}")

    # Test vision prompt
    try:
        vision_prompt = registry.get("vision.main")
        print(f"✅ Loaded vision.main ({len(vision_prompt.content)} chars)")
    except Exception as e:
        print(f"❌ Failed to load vision.main: {e}")
        
    # Test yaml
    try:
        rules = registry.get("vision.model_rules")
        print(f"✅ Loaded vision.model_rules ({len(rules.content)} chars)")
    except Exception as e:
        print(f"❌ Failed to load vision.model_rules: {e}")

if __name__ == "__main__":
    test_registry()
