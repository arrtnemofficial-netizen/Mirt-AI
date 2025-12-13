import pytest
from src.core.prompt_registry import PromptRegistry

# GoldenLoader imported but not used in this file - remove unused import

# Load Registry (Subject Under Test)
registry = PromptRegistry()

class TestPromptStaticCompliance:
    """Verifies that the static prompt text contains critical business logic instructions."""
    
    def test_payment_template_presence(self):
        """STATE_5 must contain essential payment information."""
        prompt_content = registry.get("state.STATE_5_PAYMENT_DELIVERY").content
        
        # Check for essential payment elements
        assert "200 грн" in prompt_content, "Prepayment amount should be mentioned"
        assert "IBAN" in prompt_content, "Bank details should be present"
        assert "customer_data" in prompt_content, "Customer data extraction instructions should be present"

    def test_size_boundary_table_presence(self):
        """STATE_3 must contain the exact size mapping table text."""
        prompt_content = registry.get("state.STATE_3_SIZE_COLOR").content
        
        # Check for critical boundary line
        # "112-119 см (Межа!) -> 122" matches the markdown format
        assert "112-119 см (Межа!)" in prompt_content
        assert "**122**" in prompt_content

    def test_video_priority_rule(self):
        """STATE_1 must NOT contain 'VIDEO PRIORITY' as per latest user request."""
        prompt_content = registry.get("state.STATE_1_DISCOVERY").content
        assert "VIDEO PRIORITY" not in prompt_content, "Video Priority rule wasn't removed!"

    def test_white_milk_rule(self):
        """STATE_3 must contain White/Milk explanation."""
        prompt_content = registry.get("state.STATE_3_SIZE_COLOR").content
        assert "White/Milk Equivalence" in prompt_content
        assert "ЗАБОРОНЕНО писати \"білого немає" in prompt_content
