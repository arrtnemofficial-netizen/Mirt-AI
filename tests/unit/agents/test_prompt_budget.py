"""
Tests for prompt budget and deduplication.

Ensures prompts don't exceed reasonable size limits and don't duplicate core rules.
"""

import pytest

from src.core.prompt_registry import PromptRegistry


@pytest.fixture
def registry():
    """Get prompt registry instance."""
    return PromptRegistry()


class TestPromptBudget:
    """Test prompt size limits."""
    
    def test_base_identity_size(self, registry):
        """Base identity should be comprehensive but not excessive."""
        prompt = registry.get("system.base_identity")
        # Base identity contains all core rules, so it can be larger
        assert len(prompt.content) < 5000, f"Base identity too large: {len(prompt.content)} chars"
        assert len(prompt.content) > 500, "Base identity too small (missing rules?)"
    
    def test_system_main_size(self, registry):
        """System main (domain-specific) should be focused."""
        prompt = registry.get("system.main")
        # Domain-specific should be smaller than base
        assert len(prompt.content) < 4000, f"System main too large: {len(prompt.content)} chars"
        assert len(prompt.content) > 500, "System main too small (missing domain context?)"
    
    def test_main_main_size(self, registry):
        """Main domain logic should be focused on examples and domain rules."""
        prompt = registry.get("main.main")
        assert len(prompt.content) < 5000, f"Main domain logic too large: {len(prompt.content)} chars"
        assert len(prompt.content) > 500, "Main domain logic too small"


class TestPromptDeduplication:
    """Test that core rules are not duplicated across layers."""
    
    def test_no_catalog_duplication(self, registry):
        """EMBEDDED CATALOG / SSOT Catalog should be in base_identity only."""
        base_identity = registry.get("system.base_identity").content
        system_main = registry.get("system.main").content
        main_main = registry.get("main.main").content
        
        # Check that "SSOT Catalog" or "EMBEDDED CATALOG" appears in base_identity
        assert "SSOT CATALOG" in base_identity or "EMBEDDED CATALOG" in base_identity.upper(), \
            "SSOT Catalog rule missing from base_identity"
        
        # Check that it's NOT duplicated in domain prompts (can mention it, but not redefine)
        catalog_mentions_in_main = system_main.count("SSOT Catalog") + system_main.count("EMBEDDED CATALOG")
        catalog_mentions_in_domain = main_main.count("SSOT Catalog") + main_main.count("EMBEDDED CATALOG")
        
        # Allow 1-2 mentions (for reference), but not full rule duplication
        assert catalog_mentions_in_main <= 2, \
            f"SSOT Catalog rule duplicated in system.main ({catalog_mentions_in_main} times)"
        assert catalog_mentions_in_domain <= 2, \
            f"SSOT Catalog rule duplicated in main.main ({catalog_mentions_in_domain} times)"
    
    def test_no_markdown_duplication(self, registry):
        """Markdown prohibition should be in base_identity only."""
        base_identity = registry.get("system.base_identity").content
        system_main = registry.get("system.main").content
        main_main = registry.get("main.main").content
        
        # Check that Markdown rule is in base_identity
        assert "Markdown" in base_identity and "заборонен" in base_identity.lower(), \
            "Markdown prohibition missing from base_identity"
        
        # Check that it's NOT duplicated (can mention, but not redefine)
        markdown_rules_in_main = system_main.count("Markdown") + system_main.count("markdown")
        markdown_rules_in_domain = main_main.count("Markdown") + main_main.count("markdown")
        
        # Allow 0-1 mentions (for reference only)
        assert markdown_rules_in_main <= 1, \
            f"Markdown rule duplicated in system.main ({markdown_rules_in_main} times)"
        assert markdown_rules_in_domain <= 1, \
            f"Markdown rule duplicated in main.main ({markdown_rules_in_domain} times)"
    
    def test_no_do_not_duplication(self, registry):
        """DO NOT rules should be primarily in base_identity."""
        base_identity = registry.get("system.base_identity").content
        system_main = registry.get("system.main").content
        
        # base_identity should have comprehensive DO NOT
        assert "DO NOT" in base_identity or "ЗАБОРОНЕНО" in base_identity, \
            "DO NOT section missing from base_identity"
        
        # system.main should NOT have full DO NOT section (only domain-specific exceptions)
        do_not_sections_in_main = system_main.count("## DO NOT") + system_main.count("## DO NOT")
        # Allow 0-1 (for domain-specific exceptions only)
        assert do_not_sections_in_main <= 1, \
            f"DO NOT section duplicated in system.main ({do_not_sections_in_main} times)"


class TestStatePromptStructure:
    """Test that state prompts are state-specific and don't duplicate core rules."""
    
    @pytest.mark.parametrize("state_name", [
        "STATE_0_INIT", "STATE_1_DISCOVERY", "STATE_2_VISION",
        "STATE_3_SIZE_COLOR", "STATE_4_OFFER", "STATE_5_PAYMENT_DELIVERY",
        "STATE_6_UPSELL", "STATE_7_END", "STATE_8_COMPLAINT", "STATE_9_OOD"
    ])
    def test_state_prompt_has_do_section(self, registry, state_name):
        """Each state prompt should have DO section."""
        prompt = registry.get(f"state.{state_name}")
        assert "## DO" in prompt.content, f"{state_name} missing DO section"
    
    @pytest.mark.parametrize("state_name", [
        "STATE_0_INIT", "STATE_1_DISCOVERY", "STATE_2_VISION",
        "STATE_3_SIZE_COLOR", "STATE_4_OFFER", "STATE_5_PAYMENT_DELIVERY",
        "STATE_6_UPSELL", "STATE_7_END", "STATE_8_COMPLAINT", "STATE_9_OOD"
    ])
    def test_state_prompt_has_transitions(self, registry, state_name):
        """Each state prompt should have TRANSITIONS section."""
        prompt = registry.get(f"state.{state_name}")
        assert "## TRANSITIONS" in prompt.content, f"{state_name} missing TRANSITIONS section"
    
    @pytest.mark.parametrize("state_name", [
        "STATE_0_INIT", "STATE_1_DISCOVERY", "STATE_2_VISION",
        "STATE_3_SIZE_COLOR", "STATE_4_OFFER", "STATE_5_PAYMENT_DELIVERY",
        "STATE_6_UPSELL", "STATE_7_END", "STATE_8_COMPLAINT", "STATE_9_OOD"
    ])
    def test_state_prompt_no_core_rule_duplication(self, registry, state_name):
        """State prompts should NOT duplicate core rules from base_identity."""
        prompt = registry.get(f"state.{state_name}").content
        base_identity = registry.get("system.base_identity").content
        
        # Check that state prompt doesn't redefine core rules
        # (it can mention them, but not copy-paste)
        
        # "Не вигадуй" should be in base_identity, not redefined in state
        if "Не вигадуй" in prompt and "Якщо товару немає в каталозі" in prompt:
            # This is a core rule, should reference base_identity, not redefine
            # Allow 1 mention (for state-specific context), but not full rule
            assert prompt.count("Не вигадуй") <= 2, \
                f"{state_name} duplicates 'Не вигадуй' core rule"
        
        # Markdown prohibition should not be redefined
        if "Markdown" in prompt and "заборонен" in prompt.lower():
            assert prompt.count("Markdown") <= 1, \
                f"{state_name} duplicates Markdown prohibition"

